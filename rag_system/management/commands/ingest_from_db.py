# rag_system/management/commands/ingest_from_db.py
"""
Build the RAG knowledge base from:
  1. Project text fields  (description, technical_approach, etc.)
  2. rag_document upload  (thesis PDF, Word, TXT, MD attached to a project)
  3. Resume data          (ResumeSetting, Education, Experience, Skill, etc.)

Usage:
    python manage.py ingest_from_db                        # everything
    python manage.py ingest_from_db --type project         # projects only
    python manage.py ingest_from_db --type resume          # resume only
    python manage.py ingest_from_db --project "Seizure Detection"  # one project
    python manage.py ingest_from_db --clear                # wipe then rebuild
"""

import os
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from rag_system.models import Document, DocumentChunk
from rag_system.services.embedding_service import EmbeddingService
from rag_system.services.document_processor import DocumentProcessor


class Command(BaseCommand):
    help = 'Build RAG knowledge base from DB content and uploaded project files'

    def add_arguments(self, parser):
        parser.add_argument('--type', choices=['project', 'resume', 'all'], default='all')
        parser.add_argument('--project', type=str, default=None,
                            help='Ingest a single project by exact title')
        parser.add_argument('--clear', action='store_true',
                            help='Delete existing documents of the chosen type first')

    def handle(self, *args, **options):
        doc_type   = options['type']
        clear      = options['clear']
        proj_title = options['project']
        emb  = EmbeddingService()
        proc = DocumentProcessor()

        if proj_title:
            self._ingest_one_project_by_title(proj_title, emb, proc)
            return

        if doc_type in ('project', 'all'):
            if clear:
                n = Document.objects.filter(
                    document_type__in=['project', 'project_documentation']
                ).delete()[0]
                self.stdout.write(f'Cleared {n} existing project document(s).')
            self._ingest_all_projects(emb, proc)

        if doc_type in ('resume', 'all'):
            if clear:
                n = Document.objects.filter(document_type='resume').delete()[0]
                self.stdout.write(f'Cleared {n} existing resume document(s).')
            self._ingest_resume(emb, proc)

        self.stdout.write(self.style.SUCCESS('\nRAG knowledge base is ready.'))

    # ── Projects ──────────────────────────────────────────────────────────────

    def _ingest_all_projects(self, emb, proc):
        from projects.models import Projects
        qs = Projects.objects.filter(is_public=True)
        self.stdout.write(f'\nIngesting {qs.count()} public project(s)...')
        for project in qs:
            self._ingest_project(project, emb, proc)
        emb.save_embeddings_to_file('project')
        emb.save_embeddings_to_file('project_documentation')

    def _ingest_one_project_by_title(self, title, emb, proc):
        from projects.models import Projects
        try:
            project = Projects.objects.get(title=title)
        except Projects.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Project "{title}" not found.'))
            return
        # Wipe old docs for this project only
        Document.objects.filter(
            source__startswith=f'db:projects:{project.id}:'
        ).delete()
        self._ingest_project(project, emb, proc)
        emb.save_embeddings_to_file('project')
        emb.save_embeddings_to_file('project_documentation')

    def _ingest_project(self, project, emb, proc):
        """
        Ingest one project:
          A) All text fields combined  → document_type='project'
          B) Uploaded rag_document     → document_type='project_documentation'
        """
        # ── A: text fields ────────────────────────────────────────────────────
        text = self._project_text(project)
        if text.strip():
            doc = proc.ingest_text(
                content=text,
                title=project.title,
                document_type='project',
                source=f'db:projects:{project.id}:text',
            )
            self._embed_doc(doc, emb)

        # ── B: multi-file RAG attachments (ProjectRAGFile) ────────────────────
        from projects.models import ProjectRAGFile
        rag_files = project.rag_files.all()
        processed_files, failed_files = [], []

        for rag_file in rag_files:
            file_path = rag_file.file.path if rag_file.file else None
            if not file_path or not os.path.exists(file_path):
                rag_file.status        = ProjectRAGFile.STATUS_ERROR
                rag_file.error_message = 'File missing on disk'
                rag_file.save(update_fields=['status', 'error_message'])
                failed_files.append(rag_file.filename)
                continue
            try:
                label = rag_file.label or rag_file.filename
                doc = proc.process_document(
                    file_path=file_path,
                    document_type='project_documentation',
                    title=f'{project.title} — {label}',
                )
                self._embed_doc(doc, emb)
                rag_file.status       = ProjectRAGFile.STATUS_PROCESSED
                rag_file.error_message = ''
                rag_file.processed_at  = timezone.now()
                rag_file.save(update_fields=['status', 'error_message', 'processed_at'])
                processed_files.append(rag_file.filename)
            except Exception as e:
                rag_file.status        = ProjectRAGFile.STATUS_ERROR
                rag_file.error_message = str(e)
                rag_file.save(update_fields=['status', 'error_message'])
                failed_files.append(f'{rag_file.filename} ({e})')
                self.stdout.write(self.style.WARNING(
                    f'    Could not process {rag_file.filename}: {e}'
                ))

        # ── C: legacy single rag_document field ───────────────────────────────
        if project.rag_document and not rag_files.exists():
            file_path = project.rag_document.path
            if os.path.exists(file_path):
                try:
                    doc = proc.process_document(
                        file_path=file_path,
                        document_type='project_documentation',
                        title=f'{project.title} — uploaded document',
                    )
                    self._embed_doc(doc, emb)
                    project.rag_document_processed    = True
                    project.rag_document_uploaded_at  = timezone.now()
                    project.save(update_fields=['rag_document_processed',
                                                'rag_document_uploaded_at'])
                    processed_files.append(os.path.basename(file_path))
                except Exception as e:
                    failed_files.append(str(e))

        file_summary = (
            f'{len(processed_files)} file(s) OK' if processed_files else 'no files'
        ) + (f', {len(failed_files)} failed' if failed_files else '')

        self.stdout.write(self.style.SUCCESS(
            f'  ✔  {project.title}  (text fields | {file_summary})'
        ))

    def _project_text(self, project) -> str:
        fields = [
            ('Project',            project.title),
            ('Type',               project.get_project_type_display() if project.project_type else ''),
            ('Summary',            project.short_description),
            ('Description',        project.description),
            ('Problem it solves',  project.business_problem),
            ('Technical approach', project.technical_approach),
            ('Challenges',         project.challenges),
            ('Key achievements',   project.key_achievements),
            ('Lessons learned',    project.lessons_learned),
            ('Skills used',        project.skills_used),
            ('Libraries',          project.libraries_used),
            ('Target variable',    project.target_feature),
            ('Accuracy',           str(project.accuracy_score) if project.accuracy_score else ''),
        ]
        return '\n\n'.join(
            f'{label}:\n{value}' for label, value in fields
            if value and str(value).strip() not in ('', 'None')
        )

    # ── Resume ────────────────────────────────────────────────────────────────

    def _ingest_resume(self, emb, proc):
        self.stdout.write('\nIngesting resume...')
        content = self._build_resume_text()
        if not content.strip():
            self.stdout.write(self.style.WARNING(
                '  No resume data — fill in the Resume section in admin first.'
            ))
            return
        doc = proc.ingest_text(
            content=content,
            title='Resume — Hasan Mirhoseini',
            document_type='resume',
            source='db:resume',
        )
        self._embed_doc(doc, emb)
        emb.save_embeddings_to_file('resume')
        self.stdout.write(self.style.SUCCESS('  ✔  Resume'))

    def _build_resume_text(self) -> str:
        parts = []
        try:
            from resume.models import (
                ResumeSetting, Education, Experience,
                Skill, Certification, Language,
            )
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
                    + (f"\n{e.description}" if e.description else '')
                )
            for e in Experience.objects.all():
                yr = f"{e.start_date.year}–{e.end_date.year if e.end_date else 'present'}"
                parts.append(
                    f"Experience: {e.position} at {e.company} ({yr})"
                    + (f"\n{e.description}" if e.description else '')
                )
            by_cat = {}
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
                    f"{l.language} ({l.proficiency})" for l in langs
                ))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  Resume models error: {e}'))
        return '\n\n'.join(parts)

    # ── Embedding helper ──────────────────────────────────────────────────────

    def _embed_doc(self, doc: Document, emb: EmbeddingService):
        """Generate embeddings for all chunks of a document."""
        chunks = list(doc.chunks.all())
        if chunks:
            emb.embed_document_chunks(chunks)
