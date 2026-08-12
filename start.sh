#!/bin/bash
set -e

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
until python -c "import django; django.setup(); from django.db import connection; connection.cursor()" 2>/dev/null; do
  echo "PostgreSQL is unavailable - sleeping"
  sleep 2
done

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
if [ "$USE_R2_STORAGE" = "True" ] || [ "$USE_R2_STORAGE" = "true" ] || [ "$USE_R2_STORAGE" = "1" ]; then
  # Install pg_dump if not available
  if ! command -v pg_dump &> /dev/null; then
    echo "Installing postgresql-client for backups..."
    apt-get update -qq && apt-get install -y -qq postgresql-client > /dev/null 2>&1 || true
  fi

  if command -v pg_dump &> /dev/null; then
    echo "Starting auto-backup daemon (every 6 hours)..."
    python manage.py auto_backup --daemon --interval 6 --keep 30 &
    BACKUP_PID=$!
    echo "Backup daemon started (PID: $BACKUP_PID)"
  else
    echo "WARNING: pg_dump not available — auto-backup skipped"
  fi
else
  echo "R2 storage not enabled — auto-backup skipped"
fi

echo "Starting daphne (ASGI server for WebSocket support)"
exec daphne -b 0.0.0.0 -p $PORT lms_project.asgi:application
