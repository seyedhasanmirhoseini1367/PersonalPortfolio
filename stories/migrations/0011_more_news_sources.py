"""More places the digest looks: AI news sites, Google's AI blog, new GitHub repos."""
from django.db import migrations

SOURCES = [
    # (name, kind, url, only keep AI items)
    ('GitHub trending AI repos', 'github', '', False),
    ('The Decoder', 'rss', 'https://the-decoder.com/feed/', False),
    ('MarkTechPost', 'rss', 'https://www.marktechpost.com/feed/', False),
    ('Google AI blog', 'rss', 'https://blog.google/technology/ai/rss/', False),
    ('AWS Machine Learning Blog', 'rss', 'https://aws.amazon.com/blogs/machine-learning/feed/', False),
]


def seed(apps, schema_editor):
    NewsSource = apps.get_model('stories', 'NewsSource')
    for name, kind, url, ai in SOURCES:
        NewsSource.objects.get_or_create(name=name, defaults={'kind': kind, 'url': url, 'ai_filter': ai})


class Migration(migrations.Migration):
    dependencies = [('stories', '0010_persian_suggested_links')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
