#!/bin/bash
set -e

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" 2>/dev/null; do
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
