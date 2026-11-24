"""Rewrite the resume from the owner's CV (resume/cv_data.py).

Also forgets the old CV PDF path: it pointed at Render's wiped disk. The PDF is
now uploaded again in the admin and kept in the database.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from resume import cv_data
    models = {name: apps.get_model('resume', name) for name in
              ('ResumeSetting', 'Education', 'Experience', 'ProjectHighlight', 'Language', 'Skill')}
    resume = cv_data.apply(models)
    resume.cv_pdf = ''
    resume.save(update_fields=['cv_pdf'])


class Migration(migrations.Migration):
    dependencies = [('resume', '0006_cv_storage_and_categories')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
