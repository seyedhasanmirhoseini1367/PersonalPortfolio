#!/bin/bash
# Azure WebJob: run synthetic EEG monitor
cd "$WEBROOT_PATH"
python manage.py run_synthetic_monitor --triggered-by scheduler
