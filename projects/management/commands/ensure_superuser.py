from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Create superuser if it does not exist'

    def handle(self, *args, **options):
        User = get_user_model()
        if not User.objects.filter(username='seyed').exists():
            User.objects.create_superuser('seyed', 'seyed@example.com', 'Seyed@2024')
            self.stdout.write('Superuser created.')
        else:
            self.stdout.write('Superuser already exists.')
