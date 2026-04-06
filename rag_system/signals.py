# rag_system/signals.py
"""
Auto-sync: whenever a Project or any Resume model is saved in the admin / shell,
its RAG embeddings are automatically rebuilt in a daemon background thread.
No manual `ingest_from_db` needed after the first setup.
"""
import threading
import logging

logger = logging.getLogger(__name__)


# ── Background helpers ────────────────────────────────────────────────────────

def _bg(fn, *args) -> None:
    """Fire-and-forget: run fn(*args) in a daemon thread."""
    threading.Thread(target=fn, args=args, daemon=True).start()


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

        # ── B: uploaded rag_document (thesis PDF, report, etc.) ───────────────
        if getattr(project, 'rag_document', None) and not project.rag_document_processed:
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
                    logger.info('RAG: embedded uploaded doc for "%s"', project.title)
                except Exception as exc:
                    logger.warning('RAG: could not process uploaded file for "%s": %s', project.title, exc)

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
            parts.append(
                f"Experience: {e.position} at {e.company} ({yr})"
                + (f"\n{e.description}" if getattr(e, 'description', None) else '')
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
    from projects.models import Projects

    @receiver(post_save, sender=Projects, dispatch_uid='rag_auto_sync_project')
    def on_project_saved(sender, instance, **kwargs):
        _bg(_embed_project, instance.pk)

except ImportError:
    logger.debug('RAG signals: projects app not available, skipping.')

# Resume models — each triggers a full resume re-embed (fast, single document)
try:
    from resume.models import ResumeSetting, Education, Experience, Skill, Certification, Language

    for _model in (ResumeSetting, Education, Experience, Skill, Certification, Language):
        @receiver(post_save, sender=_model, dispatch_uid=f'rag_auto_sync_resume_{_model.__name__}')
        def on_resume_model_saved(sender, instance, **kwargs):
            _bg(_embed_resume)

except ImportError:
    logger.debug('RAG signals: resume app not available, skipping.')
