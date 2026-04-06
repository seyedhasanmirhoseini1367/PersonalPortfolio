"""
Management command: send daily monitoring digest email.

Schedule via cron (runs at 8 AM daily):
    0 8 * * * cd /app && python manage.py send_monitoring_digest

Or with django-crontab in settings:
    CRONJOBS = [('0 8 * * *', 'django.core.management.call_command', ['send_monitoring_digest'])]
"""
from django.core.management.base import BaseCommand
from monitoring.notifications import send_daily_digest


class Command(BaseCommand):
    help = 'Send daily ML model activity digest email'

    def handle(self, *args, **options):
        self.stdout.write('Sending daily monitoring digest...')
        send_daily_digest()
        self.stdout.write(self.style.SUCCESS('Done.'))
