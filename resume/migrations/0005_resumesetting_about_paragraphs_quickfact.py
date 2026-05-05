import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('resume', '0004_link_resume_models_to_setting'),
    ]

    operations = [
        migrations.AddField(
            model_name='resumesetting',
            name='about_paragraph_1',
            field=models.TextField(blank=True, default='', help_text='First paragraph of the About Me section on the homepage.'),
        ),
        migrations.AddField(
            model_name='resumesetting',
            name='about_paragraph_2',
            field=models.TextField(blank=True, default='', help_text='Second paragraph (focus / specialisation). You can use <strong> for bold.'),
        ),
        migrations.AddField(
            model_name='resumesetting',
            name='about_paragraph_3',
            field=models.TextField(blank=True, default='', help_text='Third paragraph (what you are looking for). You can use <strong> for bold.'),
        ),
        migrations.CreateModel(
            name='QuickFact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('icon', models.CharField(default='📌', help_text='Emoji icon shown before the fact, e.g. 🎓', max_length=10)),
                ('text', models.CharField(help_text='The fact text. You can use HTML e.g. <strong>bold</strong>.', max_length=300)),
                ('link_text', models.CharField(blank=True, help_text="Optional: label of an inline link, e.g. 'see docs'", max_length=100)),
                ('link_url', models.CharField(blank=True, help_text='Optional: URL for the inline link (relative or absolute)', max_length=300)),
                ('display_order', models.IntegerField(default=0)),
                ('resume', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quick_facts', to='resume.resumesetting')),
            ],
            options={
                'verbose_name': 'Quick Fact',
                'verbose_name_plural': 'Quick Facts',
                'ordering': ['display_order'],
            },
        ),
    ]
