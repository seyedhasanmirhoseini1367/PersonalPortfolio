from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Create superuser if it does not exist'

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username='seyed',
            defaults={'email': 'seyed@example.com'},
        )
        if created:
            user.set_password('Seyed@2024')
            self.stdout.write('Superuser created.')
        else:
            self.stdout.write('Superuser already exists — skipping password update.')
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=['is_staff', 'is_superuser'])
