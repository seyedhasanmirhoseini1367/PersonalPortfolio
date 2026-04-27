import os
from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'monitoring'
    verbose_name = 'Model Monitoring'

    def ready(self):
        # RUN_MAIN is set by Django's autoreloader for the child process only.
        # Without this guard, ready() fires twice in development and you'd get
        # two schedulers running the same job in parallel.
        if os.environ.get('RUN_MAIN') != 'true':
            return

        try:
            from django.conf import settings
            cfg = getattr(settings, 'SYNTHETIC_MONITOR', {})
            interval = cfg.get('INTERVAL_MINUTES', 30)

            from apscheduler.schedulers.background import BackgroundScheduler
            from django.core.management import call_command

            scheduler = BackgroundScheduler()
            scheduler.add_job(
                lambda: call_command('run_synthetic_monitor'),
                trigger='interval',
                minutes=interval,
                id='synthetic_monitor',
                replace_existing=True,
            )
            scheduler.start()
        except Exception:
            pass  # never crash the server if the scheduler fails to start
