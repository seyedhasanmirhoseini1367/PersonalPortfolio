from django.db import migrations

# The five example stories shipped with the site (by request: Stories now
# holds the AI & ML news digests). Comments, likes and views cascade.
SAMPLE_SLUGS = [
    'deep-learning-unveiled-neural-networks-that-are-changing-the-world',
    'natural-language-processing-in-2025-from-tokenization-to-large-language-models',
    'data-science-from-scratch-a-practical-end-to-end-workflow',
    'machine-learning-demystified-algorithms-every-practitioner-should-know',
    'the-rise-of-artificial-intelligence-transforming-every-industry',
]


def remove(apps, schema_editor):
    apps.get_model('stories', 'Story').objects.filter(slug__in=SAMPLE_SLUGS).delete()


class Migration(migrations.Migration):
    dependencies = [('stories', '0005_daily_digest')]
    operations = [migrations.RunPython(remove, migrations.RunPython.noop)]
