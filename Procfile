web: sh -c "python manage.py migrate --noinput && gunicorn lms_project.wsgi:application --bind 0.0.0.0:$PORT"
release: python manage.py collectstatic --noinput
