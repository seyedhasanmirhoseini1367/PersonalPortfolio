from django.db import migrations


def clear_default_profile_picture(apps, schema_editor):
    CustomUser = apps.get_model('accounts', 'CustomUser')
    CustomUser.objects.filter(
        profile_picture='profile_pics/default.png'
    ).update(profile_picture='')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_alter_customuser_profile_picture'),
    ]

    operations = [
        migrations.RunPython(
            clear_default_profile_picture,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
