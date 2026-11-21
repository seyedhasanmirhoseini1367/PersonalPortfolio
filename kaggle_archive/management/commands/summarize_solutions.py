"""Build learning cards and comparisons for archived Kaggle competitions.

    python manage.py summarize_solutions            # fill what is missing
    python manage.py summarize_solutions --all      # rebuild everything
    python manage.py summarize_solutions --competition <slug>

Runs in the background on start-up (fills only what is missing), so cards
appear on the live site without a manual step.
"""
from django.core.management.base import BaseCommand

from kaggle_archive.models import Competition
from kaggle_archive.summarizer import summarize


class Command(BaseCommand):
    help = 'Summarise winners\' writeups into comparable learning cards.'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Rebuild cards that already exist.')
        parser.add_argument('--competition', help='Only this competition (slug).')

    def handle(self, *args, **options):
        qs = Competition.objects.all()
        if options['competition']:
            qs = qs.filter(slug=options['competition'])
        for comp in qs:
            self.stdout.write(f'{comp.name}:')
            made, refreshed = summarize(comp, only_missing=not options['all'], log=self.stdout.write)
            self.stdout.write(f'  {made} card(s), insights {"updated" if refreshed else "unchanged"}')
