from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0010_alter_projects_skills_used'),
    ]

    operations = [
        migrations.AddField(
            model_name='projects',
            name='prediction_input_type',
            field=models.CharField(
                choices=[('manual', 'Manual feature entry (form fields)'), ('file', 'File upload (CSV, EDF, JSON signal)')],
                default='manual',
                help_text='How the user provides input data for prediction',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='projects',
            name='file_input_config',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Configuration for file-based prediction input (JSON)',
            ),
        ),
    ]
