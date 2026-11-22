"""Kaggle Playground Series: import episodes and analyse a few now.

    python manage.py playground_sync                 # import + analyse today's batch
    python manage.py playground_sync --import-only   # just the calendar
    python manage.py playground_sync --limit 5
"""
from django.core.management.base import BaseCommand

from kaggle_archive import playground


class Command(BaseCommand):
    help = 'Import Kaggle Playground Series episodes and analyse finished ones.'

    def add_arguments(self, parser):
        parser.add_argument('--import-only', action='store_true')
        parser.add_argument('--limit', type=int, default=None)

    def handle(self, *args, **options):
        api = playground._api()
        playground.import_episodes(api, log=self.stdout.write)
        if options['import_only']:
            return
        n = playground.analyze_next(limit=options['limit'], log=self.stdout.write)
        self.stdout.write(f'{n} episode(s) analysed')
