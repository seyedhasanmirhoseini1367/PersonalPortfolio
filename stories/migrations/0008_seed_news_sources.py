"""Seed the news sources the daily digest used to have hard-coded."""
from django.db import migrations

SOURCES = [
    # (name, kind, url, only keep AI items)
    ('Hugging Face Daily Papers', 'hf_papers', 'https://huggingface.co/api/daily_papers', False),
    ('Hacker News', 'hn', 'https://hacker-news.firebaseio.com/v0/topstories.json', True),
    ('OpenAI', 'rss', 'https://openai.com/news/rss.xml', False),
    ('Google DeepMind', 'rss', 'https://deepmind.google/blog/rss.xml', False),
    ('Google Research', 'rss', 'https://research.google/blog/rss/', False),
    ('Hugging Face', 'rss', 'https://huggingface.co/blog/feed.xml', False),
    ('NVIDIA', 'rss', 'https://blogs.nvidia.com/feed/', True),
    ('Berkeley AI Research', 'rss', 'https://bair.berkeley.edu/blog/feed.xml', False),
    ('MIT News', 'rss', 'https://news.mit.edu/rss/topic/artificial-intelligence2', False),
    ('MIT Technology Review', 'rss', 'https://www.technologyreview.com/topic/artificial-intelligence/feed', False),
]


def seed(apps, schema_editor):
    NewsSource = apps.get_model('stories', 'NewsSource')
    for name, kind, url, ai in SOURCES:
        NewsSource.objects.get_or_create(name=name, defaults={'kind': kind, 'url': url, 'ai_filter': ai})


class Migration(migrations.Migration):
    dependencies = [('stories', '0007_news_sources_weekly')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
