"""
Management command: fill the resume from the CV (resume/cv_data.py).

Usage:
    python manage.py populate_resume            # rewrite the resume from the CV
    python manage.py populate_resume --if-empty # only when there is no resume yet (startup)
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Fill the resume pages from the CV data in resume/cv_data.py."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Kept for compatibility; the CV always replaces the entries.")
        parser.add_argument("--if-empty", action="store_true",
                            help="Skip silently if Education entries already exist (safe for repeated deploys).")

    def handle(self, **options):
        from resume import cv_data
        from resume.models import Education, Experience, Language, ProjectHighlight, ResumeSetting, Skill

        if options.get("if_empty") and Education.objects.exists():
            self.stdout.write("Resume data already present — skipping.")
            return
        cv_data.apply({'ResumeSetting': ResumeSetting, 'Education': Education, 'Experience': Experience,
                       'ProjectHighlight': ProjectHighlight, 'Language': Language, 'Skill': Skill})
        self.stdout.write(self.style.SUCCESS("Resume filled from the CV."))
