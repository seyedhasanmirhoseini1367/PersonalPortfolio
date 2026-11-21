from django.conf import settings
from django.db import migrations


def set_domain(apps, schema_editor):
    """The sitemap used the Sites default "example.com"."""
    Site = apps.get_model('sites', 'Site')
    domain = getattr(settings, 'SITE_DOMAIN', 'hasanai.net')
    Site.objects.update_or_create(pk=getattr(settings, 'SITE_ID', 1),
                                  defaults={'domain': domain, 'name': 'HasanAI'})


class Migration(migrations.Migration):
    dependencies = [
        ('projects', '0025_alter_projects_featured_image'),
        ('sites', '0002_alter_domain_unique'),
    ]
    operations = [migrations.RunPython(set_domain, migrations.RunPython.noop)]
