import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Make sure the site owner's admin account exists. Runs on every server start.

    The password is only written when the account is created or when SUPERUSER_PASSWORD no longer
    matches it. Writing it on every start gave the hash a new salt each time, and Django then signed
    the admin out of every browser after each deploy.
    """
    help = 'Create the superuser if missing; change its password only when SUPERUSER_PASSWORD changed'

    def handle(self, *args, **kwargs):
        User = get_user_model()
        username = os.environ.get('SUPERUSER_USERNAME', 'seyed')
        password = os.environ.get('SUPERUSER_PASSWORD', '')
        email = os.environ.get('SUPERUSER_EMAIL', 'seyed@example.com')

        user, created = User.objects.get_or_create(username=username, defaults={'email': email})
        changed = []
        if created or not user.is_staff or not user.is_superuser:
            user.is_staff = user.is_superuser = True
            changed += ['is_staff', 'is_superuser']
        if password and not user.check_password(password):
            user.set_password(password)
            changed.append('password')
        elif created and not password:
            user.set_unusable_password()   # no default password in the code: set SUPERUSER_PASSWORD
            changed.append('password')
        if changed:
            user.save(update_fields=None if created else changed)
        self.stdout.write('Superuser created.' if created else
                          ('Superuser updated: ' + ', '.join(changed) + '.') if changed else 'Superuser unchanged.')
