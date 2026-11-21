"""Load the portfolio's public content (projects, stories, Kaggle archive).

The content lives in projects/fixtures/site_content.json (text only: no users,
comments or uploaded files). Run on every start-up with --if-empty: each
section is loaded only while its table is still empty, so edits made later in
the admin are never overwritten.

Authors/owners are set to the site superuser (SUPERUSER_USERNAME, default
"seyed"). Rebuild the file from a local database with
scripts/export_content.py (see that file).
"""
import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.management.base import BaseCommand
from django.core.management.color import no_style
from django.db import connection, transaction

FIXTURE = Path(__file__).resolve().parents[2] / 'fixtures' / 'site_content.json'

# section name -> (models it contains, model whose table decides "empty")
SECTIONS = {
    'stories': (('stories.tag', 'stories.story'), 'stories.story'),
    'projects': (('projects.projects',), 'projects.projects'),
    'kaggle': (('kaggle_archive.technique', 'kaggle_archive.competition', 'kaggle_archive.solution'),
               'kaggle_archive.competition'),
}


class Command(BaseCommand):
    help = 'Load public projects, stories and the Kaggle archive from the content fixture.'

    def add_arguments(self, parser):
        parser.add_argument('--if-empty', action='store_true',
                            help='Only load a section while its table is empty (safe on every start-up).')

    def handle(self, *args, **options):
        from django.apps import apps

        if not FIXTURE.exists():
            self.stdout.write('populate_content: no fixture, skipping.')
            return
        owner = (get_user_model().objects
                 .filter(username=os.environ.get('SUPERUSER_USERNAME', 'seyed')).first()
                 or get_user_model().objects.filter(is_superuser=True).order_by('pk').first())

        with open(FIXTURE, encoding='utf-8') as fh:
            objects = list(serializers.deserialize('json', fh, ignorenonexistent=True))

        for section, (labels, gate) in SECTIONS.items():
            gate_model = apps.get_model(gate)
            if options['if_empty'] and gate_model.objects.exists():
                self.stdout.write(f'populate_content: {section} already present, skipping.')
                continue
            chosen = [o for o in objects if o.object._meta.label_lower in labels]
            with transaction.atomic():
                for item in chosen:
                    obj = item.object
                    for field in ('author', 'owner'):
                        if hasattr(obj, f'{field}_id') and getattr(obj, f'{field}_id') is None:
                            setattr(obj, f'{field}_id', owner.pk if owner else None)
                    item.save()
                # Explicit primary keys: move each table's id sequence past them (Postgres).
                models = [apps.get_model(label) for label in labels]
                with connection.cursor() as cursor:
                    for sql in connection.ops.sequence_reset_sql(no_style(), models):
                        cursor.execute(sql)
            self.stdout.write(f'populate_content: loaded {len(chosen)} {section} objects.')
