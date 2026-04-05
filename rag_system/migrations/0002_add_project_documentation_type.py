from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rag_system', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='document',
            name='document_type',
            field=models.CharField(
                max_length=30,
                choices=[
                    ('project', 'Project'),
                    ('resume', 'Resume'),
                    ('blog', 'Blog Post'),
                    ('skill', 'Technical Skill'),
                    ('project_documentation', 'Project Documentation (uploaded file)'),
                ],
            ),
        ),
    ]
