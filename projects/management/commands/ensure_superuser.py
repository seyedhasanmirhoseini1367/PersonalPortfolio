import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Create superuser if it does not exist, always sync password'

    def handle(self, *args, **kwargs):
        User = get_user_model()
        username = os.environ.get('SUPERUSER_USERNAME', 'seyed')
        password = os.environ.get('SUPERUSER_PASSWORD', 'Seyed@2024')
        email    = os.environ.get('SUPERUSER_EMAIL', 'seyed@example.com')

        user, created = User.objects.get_or_create(username=username,
                                                   defaults={'email': email})
        user.set_password(password)
        user.is_staff     = True
        user.is_superuser = True
        user.save()
        label = 'Superuser created.' if created else 'Superuser updated.'
        self.stdout.write(label)
