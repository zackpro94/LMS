#!/bin/bash
set -e

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
until python -c "import django; django.setup(); from django.db import connection; connection.cursor()" 2>/dev/null; do
  echo "PostgreSQL is unavailable - sleeping"
  sleep 2
done

echo "PostgreSQL is up - running migrations"
python manage.py migrate --noinput

echo "Collecting static files"
python manage.py collectstatic --noinput

echo "Starting gunicorn"
exec gunicorn lms_project.wsgi:application --bind 0.0.0.0:$PORT
