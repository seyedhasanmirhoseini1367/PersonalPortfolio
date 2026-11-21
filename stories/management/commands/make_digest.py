"""Build today's AI & ML digest story.

    python manage.py make_digest --dry-run   # show what would be picked, publish nothing
    python manage.py make_digest             # publish today's digest now (if not done yet)
    python manage.py make_digest --force     # rebuild today's digest
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from stories.digest import HELSINKI, make_digest, run_today
from stories.models import DailyDigest


class Command(BaseCommand):
    help = "Publish today's AI & ML digest in Stories."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Only show the selection.')
        parser.add_argument('--force', action='store_true', help="Rebuild even if today's digest exists.")

    def handle(self, *args, **options):
        if options['dry_run']:
            make_digest(dry_run=True, log=self.stdout.write)
            return
        today = timezone.now().astimezone(HELSINKI).date()
        if not options['force'] and DailyDigest.objects.filter(date=today, status='done').exists():
            self.stdout.write("Today's digest already exists. Use --force to rebuild it.")
            return
        rec = run_today(log=self.stdout.write)
        self.stdout.write(f'{rec.status}: {rec.items} item(s)'
                          + (f' — /stories/story/{rec.story.slug}/' if rec.story else ''))
