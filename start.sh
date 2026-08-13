#!/bin/bash
set -e

# Print database configuration info
echo "=== Database Configuration ==="
python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms_project.settings')
django.setup()
from django.conf import settings
db = settings.DATABASES.get('default', {})
print(f'  ENGINE: {db.get(\"ENGINE\", \"unknown\")}')
print(f'  NAME:   {db.get(\"NAME\", \"unknown\")}')
print(f'  HOST:   {db.get(\"HOST\", \"N/A\")}')
print(f'  PORT:   {db.get(\"PORT\", \"N/A\")}')
" || true
echo "=============================="

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Creating default admin user..."
python manage.py create_admin || true

echo "Creating media directories..."
mkdir -p media/letters/attachments

echo "Collecting static files..."
python manage.py collectstatic --noinput || true

# ---------------------------------------------------------------------------
# Auto-backup daemon (runs every 6 hours, keeps last 30 backups)
# ---------------------------------------------------------------------------
if [ "$AUTO_BACKUP_ENABLED" = "True" ] || [ "$AUTO_BACKUP_ENABLED" = "true" ] || [ "$AUTO_BACKUP_ENABLED" = "1" ] || \
   [ "$USE_R2_STORAGE" = "True" ] || [ "$USE_R2_STORAGE" = "true" ] || [ "$USE_R2_STORAGE" = "1" ] || \
   [ -n "$R2_ACCESS_KEY_ID" ]; then

  if ! command -v pg_dump &> /dev/null; then
    echo "pg_dump binary not detected in PATH. Attempting runtime installation..."
    apt-get update -qq && apt-get install -y -qq postgresql-client > /dev/null 2>&1 || true
  fi

  echo "Starting auto-backup daemon (every 6 hours)..."
  python manage.py auto_backup --daemon --interval 6 --keep 30 > /tmp/auto_backup.log 2>&1 &
  BACKUP_PID=$!
  echo "Backup daemon started (PID: $BACKUP_PID)"
else
  echo "Auto-backup disabled (set R2 credentials or AUTO_BACKUP_ENABLED=true to enable)"
fi

echo "Starting daphne (ASGI server for WebSocket support)..."
exec daphne -b 0.0.0.0 -p $PORT lms_project.asgi:application
