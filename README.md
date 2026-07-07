# Auction Ethiopia — Letter Management System (LMS)

A Django 5.x web application for tracking incoming and outgoing company correspondence, with department-based reference numbering, action logging, attachment management, and reporting dashboards.

## Features

- **Letter Registration** — Log incoming & outgoing letters with automatic reference numbers (`AE/HR/0001/26`)
- **Department Assignment** — Route letters to the correct department and person
- **Action Logging** — Chronological audit trail of every action taken on a letter
- **Attachments** — Upload and download files linked to letters
- **Status Tracking** — RECEIVED → IN_REVIEW → ACTIONED → RESPONDED → CLOSED → ARCHIVED
- **Overdue Alerts** — View all letters past their due date
- **Reports & Charts** — Monthly volume, department breakdown, category/status analytics
- **Permissions** — Role-based access: Front Desk, Department Staff, Admin

## Tech Stack

- Python 3.11+ / Django 5.x
- SQLite (dev) / PostgreSQL (production)
- Bootstrap 5, Chart.js 4
- django-crispy-forms, django-filter, whitenoise

---

## Quick Start

### 1. Clone & create virtual environment

```bash
git clone <repo-url>
cd "AE LMS"
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run migrations

```bash
python manage.py migrate
```

### 4. Create a superuser

```bash
python manage.py createsuperuser
```

### 5. (Optional) Seed demo data

```bash
python manage.py seed_demo_data
```

This creates:
- 6 departments (HR, FIN, LEG, OPS, IT, MKT)
- 8 users across 3 permission groups
- ~30 sample letters with action logs

**Demo accounts:**

| Username   | Password       | Role             |
|------------|----------------|------------------|
| admin      | admin123       | Superuser        |
| frontdesk  | frontdesk123   | Front Desk       |
| hana       | hana123        | Dept Staff (HR)  |
| dawit      | dawit123       | Dept Staff (FIN) |

### 6. Run the development server

```bash
python manage.py runserver
```

Visit [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## Running Tests

```bash
python manage.py test letters
```

Tests cover:
- Reference number generation (format, sequencing, per-department/year counters, year reset)
- Status transition permissions (who can close/archive)

---

## Project Structure

```
AE LMS/
├── lms_project/           # Django project config
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py / asgi.py
├── letters/               # Main app
│   ├── models.py          # Department, Letter, Attachment, ActionLog, ReferenceCounter
│   ├── views.py           # Dashboard, CRUD, Reports
│   ├── forms.py           # Crispy forms
│   ├── filters.py         # django-filter integration
│   ├── permissions.py     # Role-based access control
│   ├── admin.py           # Django admin config
│   ├── urls.py
│   ├── tests/
│   └── management/commands/seed_demo_data.py
├── accounts/              # Auth (login/logout)
├── templates/             # HTML templates
├── static/                # CSS, JS
├── requirements.txt
└── README.md
```

---

## Reference Number Format

```
AE/{DEPT_CODE}/{4-digit seq}/{2-digit year}
```

- `AE` — fixed company prefix (Auction Ethiopia)
- `{DEPT_CODE}` — from `Department.code` (e.g. HR, FIN, LEG)
- Sequential number resets per department per year
- Uses `ReferenceCounter` table with `select_for_update()` for concurrency safety

---

## Production Notes

To switch to PostgreSQL, set these environment variables:

```bash
DB_ENGINE=django.db.backends.postgresql
DB_NAME=ae_lms
DB_USER=your_user
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
DJANGO_SECRET_KEY=your-production-secret-key
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=your-domain.com
```

---

## License

Internal use — Auction Ethiopia.
