from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rag_system', '0003_chat_sessions'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatsession',
            name='session_key',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Django session key — scopes this chat to one browser session',
                max_length=40,
                null=True,
            ),
        ),
    ]
