#!/bin/bash
set -e

# Print resolved database engine for debugging
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
" 2>&1 || echo "  (could not read settings)"
echo "=============================="

# Check if using PostgreSQL or SQLite
DB_ENGINE=$(python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms_project.settings')
django.setup()
from django.conf import settings
print(settings.DATABASES.get('default', {}).get('ENGINE', ''))
" 2>/dev/null || echo "unknown")

if echo "$DB_ENGINE" | grep -q "postgresql"; then
  # Wait for PostgreSQL to be ready (max 60 seconds)
  echo "Waiting for PostgreSQL to be ready..."
  RETRIES=0
  MAX_RETRIES=30
  DB_READY=false
  while [ $RETRIES -lt $MAX_RETRIES ]; do
    # Show the actual error on each attempt
    DB_ERROR=$(python -c "import django; django.setup(); from django.db import connection; connection.cursor(); print('OK')" 2>&1)
    if echo "$DB_ERROR" | grep -q "OK"; then
      DB_READY=true
      break
    fi
    RETRIES=$((RETRIES + 1))
    echo "PostgreSQL is unavailable (attempt $RETRIES/$MAX_RETRIES): $DB_ERROR"
    sleep 2
  done

  if [ "$DB_READY" = true ]; then
    echo "PostgreSQL is up!"
  else
    echo "WARNING: PostgreSQL did not become available after 60 seconds."
    echo "Last error: $DB_ERROR"
    echo "Continuing anyway — daphne will retry connections lazily..."
  fi
else
  echo "Using non-PostgreSQL database ($DB_ENGINE) - skipping wait"
fi

echo "PostgreSQL is up - running migrations"
if python manage.py migrate --noinput; then
  echo "Migrations completed successfully"
else
  echo "Error running migrations"
  exit 1
fi

echo "Creating admin user if not exists"
if python manage.py create_admin; then
  echo "Admin user creation completed"
else
  echo "Warning: Admin user creation failed, but continuing..."
fi

echo "Creating media directory"
mkdir -p media/letters/attachments

echo "Collecting static files"
if python manage.py collectstatic --noinput; then
  echo "Static files collected successfully"
else
  echo "Warning: Static file collection failed, but continuing..."
fi

# ---------------------------------------------------------------------------
# Auto-backup daemon (runs every 6 hours, keeps last 30 backups)
# ---------------------------------------------------------------------------
if [ "$AUTO_BACKUP_ENABLED" = "True" ] || [ "$AUTO_BACKUP_ENABLED" = "true" ] || [ "$AUTO_BACKUP_ENABLED" = "1" ] || \
   [ "$USE_R2_STORAGE" = "True" ] || [ "$USE_R2_STORAGE" = "true" ] || [ "$USE_R2_STORAGE" = "1" ] || \
   [ -n "$R2_ACCESS_KEY_ID" ]; then

  # Attempt runtime postgresql-client install if pg_dump is missing
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

echo "Starting daphne (ASGI server for WebSocket support)"
exec daphne -b 0.0.0.0 -p $PORT lms_project.asgi:application
