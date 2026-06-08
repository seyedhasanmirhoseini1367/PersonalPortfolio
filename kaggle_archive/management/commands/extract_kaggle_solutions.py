"""
Kaggle Winners Archive — Solution Extractor (CLI wrapper)

Usage:
    python manage.py extract_kaggle_solutions <url-or-slug>
    python manage.py extract_kaggle_solutions <url-or-slug> --top 10
    python manage.py extract_kaggle_solutions <url-or-slug> --top 5 --update

Examples:
    python manage.py extract_kaggle_solutions https://www.kaggle.com/competitions/titanic
    python manage.py extract_kaggle_solutions jane-street-market-prediction --top 10

Note: --update is accepted for backwards compatibility but is a no-op.
KaggleExtractor always uses update_or_create, so existing records are always refreshed.
"""

from django.core.management.base import BaseCommand, CommandError
from kaggle_archive.extractor import KaggleExtractor


class Command(BaseCommand):
    help = 'Extract top Kaggle solutions by pasting a competition URL or slug.'

    def add_arguments(self, parser):
        parser.add_argument(
            'competition',
            type=str,
            help='Kaggle competition URL or slug  (e.g. https://www.kaggle.com/competitions/titanic  OR  titanic)',
        )
        parser.add_argument(
            '--top', type=int, default=10,
            help='Number of top leaderboard positions to archive  (default: 10, max: 50)',
        )
        parser.add_argument(
            '--update', action='store_true',
            help='[deprecated, no-op] KaggleExtractor always does update_or_create.',
        )

    def handle(self, **options):
        raw = options['competition']
        top = min(options['top'], 50)

        self._section('Kaggle Winners Archive — Extractor')
        self._log(f'Input : {raw}')
        self._log(f'Top   : {top}\n')

        try:
            extractor = KaggleExtractor(url=raw, top_n=top, log_fn=self._log)
            result    = extractor.run()
        except RuntimeError as exc:
            raise CommandError(str(exc))

        comp = result['competition']
        self._section('Done')
        self.stdout.write(
            self.style.SUCCESS(
                f'Saved {result["saved"]} solutions for "{comp.name}"\n'
                f'    View at: /kaggle-winners-archive/{comp.slug}/'
            )
        )

    def _section(self, msg):
        self.stdout.write(self.style.HTTP_INFO(f'\n-- {msg} '))

    def _ok(self, msg):
        self.stdout.write(self.style.SUCCESS(f'  [OK] {msg}'))

    def _log(self, msg):
        self.stdout.write(f'  {msg}')

    def _warn(self, msg):
        self.stdout.write(self.style.WARNING(f'  [!] {msg}'))
