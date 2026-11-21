# rag_system/signals.py
"""
Auto-sync: whenever a Project or any Resume model is saved in the admin / shell,
its RAG embeddings are automatically rebuilt in a daemon background thread.
No manual `ingest_from_db` needed after the first setup.

Rebuilds are debounced per document: many saves in a row (e.g. the populate
commands on start-up) lead to one rebuild a moment after the last save, and
the same document is never rebuilt by two threads at once.
"""
import threading
import logging

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)


# ── Background helpers ────────────────────────────────────────────────────────

_lock = threading.Lock()
_jobs = {}  # key -> {'timer': Timer | None, 'running': bool, 'again': bool}


def _delay() -> float:
    return getattr(settings, 'RAG_SYNC_DELAY', 3.0)


def _schedule(key, fn, *args) -> None:
    """Run fn(*args) in the background once things go quiet for `key`.

    A new request restarts the wait. If a run for `key` is in progress, one
    more run is queued for when it finishes (so the latest data is used).
    """
    with _lock:
        job = _jobs.setdefault(key, {'timer': None, 'running': False, 'again': False})
        if job['running']:
            job['again'] = True
            return
        if job['timer'] is not None:
            job['timer'].cancel()
        timer = threading.Timer(_delay(), _run, args=(key, fn, args))
        timer.daemon = True
        job['timer'] = timer
        timer.start()


def _run(key, fn, args) -> None:
    with _lock:
        job = _jobs[key]
        job['timer'] = None
        job['running'] = True
    try:
        fn(*args)
    finally:
        connection.close()  # this thread's own DB connection
        with _lock:
            job['running'] = False
            again, job['again'] = job['again'], False
        if again:
            _schedule(key, fn, *args)


def _bg(fn, *args) -> None:
    """Debounced background run, one queue per function + arguments."""
    _schedule((fn.__name__,) + args, fn, *args)


# Saves that only record processing state must not start another rebuild.
_STATE_FIELDS_FILE = {'status', 'error_message', 'processed_at'}
_STATE_FIELDS_PROJECT = {'rag_document_processed'}


def _state_only(kwargs, fields) -> bool:
    update_fields = kwargs.get('update_fields')
    return bool(update_fields) and set(update_fields) <= fields


def _embed_project(project_id: int) -> None:
    """Rebuild embeddings for one project (text fields + optional uploaded file)."""
    try:
        from projects.models import Projects
        from rag_system.services.document_processor import DocumentProcessor
        from rag_system.services.embedding_service import EmbeddingService
        from rag_system.models import Document
        import os

        project = Projects.objects.get(pk=project_id)
        proc = DocumentProcessor()
        emb  = EmbeddingService()

        # If project went private, purge its documents from the knowledge base
        if not project.is_public:
            deleted, _ = Document.objects.filter(
                source__startswith=f'db:projects:{project_id}:'
            ).delete()
            if deleted:
                logger.info('RAG: purged %d doc(s) for private project "%s"', deleted, project.title)
            return

        # ── A: text fields ────────────────────────────────────────────────────
        fields = [
            ('Project',            project.title),
            ('Type',               project.get_project_type_display() if project.project_type else ''),
            ('Summary',            project.short_description or ''),
            ('Description',        project.description or ''),
            ('Problem it solves',  project.business_problem or ''),
            ('Technical approach', project.technical_approach or ''),
            ('Challenges',         project.challenges or ''),
            ('Key achievements',   project.key_achievements or ''),
            ('Lessons learned',    project.lessons_learned or ''),
            ('Skills used',        project.skills_used or ''),
            ('Libraries',          project.libraries_used or ''),
            ('Target variable',    project.target_feature or ''),
            ('Accuracy',           str(project.accuracy_score) if project.accuracy_score else ''),
        ]
        text = '\n\n'.join(
            f'{label}:\n{value}' for label, value in fields
            if value and str(value).strip() not in ('', 'None')
        )
        if text.strip():
            doc = proc.ingest_text(
                content=text,
                title=project.title,
                document_type='project',
                source=f'db:projects:{project_id}:text',
            )
            emb.embed_document_chunks(list(doc.chunks.all()))
            logger.info('RAG: embedded project "%s" (%d chunks)', project.title, doc.chunks.count())

        # ── B: multi-file RAG attachments (ProjectRAGFile) ───────────────────
        from projects.models import ProjectRAGFile
        from django.utils import timezone as tz
        for rag_file in project.rag_files.all():
            file_path = rag_file.file.path if rag_file.file else None
            if not file_path or not os.path.exists(file_path):
                rag_file.status = ProjectRAGFile.STATUS_ERROR
                rag_file.error_message = 'File missing on disk'
                rag_file.save(update_fields=['status', 'error_message'])
                continue
            try:
                label = rag_file.label or rag_file.filename
                doc2 = proc.process_document(
                    file_path=file_path,
                    document_type='project_documentation',
                    title=f'{project.title} — {label}',
                )
                emb.embed_document_chunks(list(doc2.chunks.all()))
                rag_file.status = ProjectRAGFile.STATUS_PROCESSED
                rag_file.error_message = ''
                rag_file.processed_at = tz.now()
                rag_file.save(update_fields=['status', 'error_message', 'processed_at'])
                logger.info('RAG: embedded file "%s" for project "%s"', label, project.title)
            except Exception as exc:
                rag_file.status = ProjectRAGFile.STATUS_ERROR
                rag_file.error_message = str(exc)
                rag_file.save(update_fields=['status', 'error_message'])
                logger.warning('RAG: could not process "%s" for "%s": %s', rag_file.filename, project.title, exc)

        # ── C: legacy single rag_document (fallback if no rag_files) ─────────
        if getattr(project, 'rag_document', None) and not project.rag_document_processed \
                and not project.rag_files.exists():
            file_path = project.rag_document.path
            if os.path.exists(file_path):
                try:
                    doc2 = proc.process_document(
                        file_path=file_path,
                        document_type='project_documentation',
                        title=f'{project.title} — uploaded document',
                    )
                    emb.embed_document_chunks(list(doc2.chunks.all()))
                    project.rag_document_processed = True
                    project.save(update_fields=['rag_document_processed'])
                    logger.info('RAG: embedded legacy uploaded doc for "%s"', project.title)
                except Exception as exc:
                    logger.warning('RAG: could not process legacy file for "%s": %s', project.title, exc)

    except Exception as exc:
        logger.exception('RAG: _embed_project(%s) failed: %s', project_id, exc)


def _embed_resume() -> None:
    """Rebuild the full resume embedding from all resume models."""
    try:
        from rag_system.services.document_processor import DocumentProcessor
        from rag_system.services.embedding_service import EmbeddingService
        from resume.models import (
            ResumeSetting, Education, Experience,
            Skill, Certification, Language,
        )

        parts = []

        s = ResumeSetting.objects.first()
        if s:
            parts.append(
                f"Name: {s.full_name}\nTitle: {s.job_title}\n"
                f"Location: {s.location}\nEmail: {s.email}\n"
                f"Summary:\n{s.professional_summary}"
            )

        for e in Education.objects.all():
            yr = f"{e.start_date.year}–{e.end_date.year if e.end_date else 'present'}"
            parts.append(
                f"Education: {e.get_degree_display()} in {e.field_of_study} "
                f"at {e.institution} ({yr})"
                + (f"\n{e.description}" if getattr(e, 'description', None) else '')
            )

        for e in Experience.objects.all():
            yr = f"{e.start_date.year}–{e.end_date.year if e.end_date else 'present'}"
            achievements = getattr(e, 'achievements', None) or []
            bullet_text = ('\n' + '\n'.join(f'  - {a}' for a in achievements)) if achievements else ''
            parts.append(
                f"Experience: {e.position} at {e.company} ({yr})"
                + (f" [{e.employment_type}]" if getattr(e, 'employment_type', None) else '')
                + (f" — {e.location}" if getattr(e, 'location', None) else '')
                + bullet_text
            )

        by_cat: dict = {}
        for sk in Skill.objects.all():
            by_cat.setdefault(sk.category, []).append(sk.name)
        if by_cat:
            parts.append('Skills:\n' + '\n'.join(
                f'  {cat}: {", ".join(names)}' for cat, names in by_cat.items()
            ))

        for c in Certification.objects.all():
            parts.append(f"Certification: {c.name} — {c.issuing_organization}")

        langs = Language.objects.all()
        if langs.exists():
            parts.append('Languages: ' + ', '.join(
                f"{lng.language} ({lng.proficiency})" for lng in langs
            ))

        from resume.models import ProjectHighlight
        highlights = ProjectHighlight.objects.all()
        if highlights.exists():
            proj_lines = ['Selected Projects:']
            for ph in highlights:
                tech = ', '.join(ph.technologies_used) if ph.technologies_used else ''
                proj_lines.append(
                    f"  Project: {ph.title}"
                    + (f"\n    Technologies: {tech}" if tech else '')
                    + (f"\n    Description: {ph.description}" if ph.description else '')
                )
            parts.append('\n'.join(proj_lines))

        content = '\n\n'.join(parts)
        if not content.strip():
            logger.warning('RAG: _embed_resume: no resume content found.')
            return

        proc = DocumentProcessor()
        emb  = EmbeddingService()
        doc  = proc.ingest_text(
            content=content,
            title='Resume — Hasan Mirhoseini',
            document_type='resume',
            source='db:resume',
        )
        emb.embed_document_chunks(list(doc.chunks.all()))
        logger.info('RAG: embedded resume (%d chunks)', doc.chunks.count())

    except Exception as exc:
        logger.exception('RAG: _embed_resume failed: %s', exc)


# ── Signal receivers ──────────────────────────────────────────────────────────
# Imported by apps.py RagSystemConfig.ready() — this is the Django-standard pattern.

from django.db.models.signals import post_save
from django.dispatch import receiver

# Projects
try:
    from projects.models import Projects, ProjectRAGFile

    @receiver(post_save, sender=Projects, dispatch_uid='rag_auto_sync_project')
    def on_project_saved(sender, instance, **kwargs):
        if _state_only(kwargs, _STATE_FIELDS_PROJECT):
            return
        _bg(_embed_project, instance.pk)

    @receiver(post_save, sender=ProjectRAGFile, dispatch_uid='rag_auto_sync_rag_file')
    def on_rag_file_saved(sender, instance, **kwargs):
        """Re-ingest the project when a file is uploaded or re-saved."""
        if _state_only(kwargs, _STATE_FIELDS_FILE):
            return
        _bg(_embed_project, instance.project_id)

except ImportError:
    logger.debug('RAG signals: projects app not available, skipping.')

# Resume models — each triggers a full resume re-embed (fast, single document)
try:
    from resume.models import ResumeSetting, Education, Experience, Skill, Certification, Language, ProjectHighlight

    for _model in (ResumeSetting, Education, Experience, Skill, Certification, Language, ProjectHighlight):
        @receiver(post_save, sender=_model, dispatch_uid=f'rag_auto_sync_resume_{_model.__name__}')
        def on_resume_model_saved(sender, instance, **kwargs):  # noqa: ARG001
            _bg(_embed_resume)

except ImportError:
    logger.debug('RAG signals: resume app not available, skipping.')
