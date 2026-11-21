"""Export public portfolio content from the local DB to a JSON fixture.

Usage (from D:/PersonalPortfolio, local SQLite):
    python scripts/export_content.py projects/fixtures/site_content.json
Leaves out users, comments, likes/views and every uploaded file.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'PersonalPortfolio.settings')
os.environ['DATABASE_URL'] = ''
import django  # noqa: E402

django.setup()
from django.core import serializers  # noqa: E402
from projects.models import Projects  # noqa: E402
from stories.models import Story, Tag  # noqa: E402
from kaggle_archive.models import Competition, Solution, Technique  # noqa: E402

FILE_FIELDS = {'featured_image', 'trained_model', 'rag_document', 'image', 'file', 'document', 'cv_pdf'}
USER_FIELDS = {'owner', 'author', 'user'}

groups = [
    Tag.objects.all(),
    Story.objects.filter(status=Story.Status.PUBLISHED),
    Projects.objects.filter(is_public=True),
    Technique.objects.all(),
    Competition.objects.all(),
    Solution.objects.all(),
]
out = []
for qs in groups:
    for obj in json.loads(serializers.serialize('json', qs)):
        for f in list(obj['fields']):
            if f in FILE_FIELDS:
                obj['fields'][f] = ''
            elif f in USER_FIELDS:
                obj['fields'][f] = None
        if obj['model'] == 'stories.story':
            for f in ('view_count', 'like_count'):
                if f in obj['fields']:
                    obj['fields'][f] = 0
        out.append(obj)

with open(sys.argv[1], 'w', encoding='utf-8') as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print(len(out), 'objects')
