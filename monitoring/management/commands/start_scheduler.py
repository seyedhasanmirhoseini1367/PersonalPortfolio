"""
Runs the synthetic monitor on a fixed interval — no Task Scheduler needed.

Usage:
    python manage.py start_scheduler              # every 30 min (default)
    python manage.py start_scheduler --interval 5 # every 5 min
    python manage.py start_scheduler --interval 1 # every 1 min (testing)

Keep this running in a separate terminal alongside your Django server.
Press Ctrl+C to stop.
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command
from apscheduler.schedulers.blocking import BlockingScheduler


class Command(BaseCommand):
    help = 'Run synthetic EEG monitor on a timed interval'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval', type=int, default=30,
            help='How often to run the monitor, in minutes (default: 30)',
        )

    def handle(self, *_, **options):
        interval = options['interval']
        scheduler = BlockingScheduler()

        scheduler.add_job(
            self._run,
            trigger='interval',
            minutes=interval,
            id='synthetic_monitor',
        )

        self.stdout.write(self.style.SUCCESS(
            f'Scheduler started — running every {interval} minute(s).\n'
            'Press Ctrl+C to stop.'
        ))

        # Run once immediately on startup, then repeat on the interval
        self._run()
        scheduler.start()

    def _run(self):
        self.stdout.write('\n--- Running synthetic monitor ---')
        call_command('run_synthetic_monitor')
