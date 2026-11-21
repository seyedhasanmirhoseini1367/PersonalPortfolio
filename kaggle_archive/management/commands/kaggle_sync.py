"""Run the archive's monthly auto-update now.

    python manage.py kaggle_sync              # only if due (30 days since the last run)
    python manage.py kaggle_sync --force      # run now
    python manage.py kaggle_sync --force --limit 5
"""
from django.core.management.base import BaseCommand

from kaggle_archive.auto import is_due, run_sync


class Command(BaseCommand):
    help = 'Archive recently finished Featured/Research Kaggle competitions.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Run even if a run happened recently.')
        parser.add_argument('--limit', type=int, default=None, help='Max competitions to extract this run.')

    def handle(self, *args, **options):
        if not options['force'] and not is_due():
            self.stdout.write('Not due yet (a run happened in the last 30 days). Use --force to run anyway.')
            return
        run = run_sync('manual', limit=options['limit'], log=self.stdout.write)
        self.stdout.write(f'Run {run.status}: {run.processed} competition(s) processed.')
