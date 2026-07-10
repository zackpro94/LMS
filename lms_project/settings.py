import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-ae-lms-dev-key-change-in-production-!@#$%'
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Add Railway domains
if os.environ.get('RAILWAY_ENVIRONMENT'):
    ALLOWED_HOSTS.append('.railway.app')
    ALLOWED_HOSTS.append('.railway.internal')
    # Add Railway domain to CSRF trusted origins
    CSRF_TRUSTED_ORIGINS = ['https://*.railway.app']

# Add custom domain
ALLOWED_HOSTS.append('lms.pro.et')
if 'CSRF_TRUSTED_ORIGINS' not in locals():
    CSRF_TRUSTED_ORIGINS = []
CSRF_TRUSTED_ORIGINS.append('https://lms.pro.et')

# Push Notification Settings (VAPID)
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', 'BH0kCCgHsTcENSDsqsd6dMpMHaYwoCMaZJxL8V0xRoHvbGSLzrVtPBHoYp4eY-0zj2ZskLxVVH25_bQJNCPDYVE')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', 'A-51wCdoiSEFBuJ1Hm6BjU6BQtRf1wwtS19BwZubxoo')
VAPID_CLAIMS = {'sub': 'mailto:admin@lms.pro.et'}

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'crispy_forms',
    'crispy_bootstrap5',
    'django_filters',
    'corsheaders',
    'storages',
    # Local apps
    'letters.apps.LettersConfig',
    'accounts.apps.AccountsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'lms_project.urls'

# Custom error pages
handler404 = 'lms_project.views.custom_404'
handler403 = 'lms_project.views.custom_403'
handler500 = 'lms_project.views.custom_500'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'letters.context_processors.lms_navigation',
            ],
        },
    },
]

WSGI_APPLICATION = 'lms_project.wsgi.application'

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# SQLite for development. PostgreSQL for production (Railway)
if os.environ.get('RAILWAY_ENVIRONMENT'):
    # Railway provides PostgreSQL connection variables
    # Only use PostgreSQL if all required vars are present
    if all([
        os.environ.get('RAILWAY_POSTGRES_HOST'),
        os.environ.get('RAILWAY_POSTGRES_DB_NAME'),
        os.environ.get('RAILWAY_POSTGRES_USER'),
        os.environ.get('RAILWAY_POSTGRES_PASSWORD'),
    ]):
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': os.environ.get('RAILWAY_POSTGRES_DB_NAME') or os.environ.get('POSTGRES_DB') or os.environ.get('DB_NAME'),
                'USER': os.environ.get('RAILWAY_POSTGRES_USER') or os.environ.get('POSTGRES_USER') or os.environ.get('DB_USER'),
                'PASSWORD': os.environ.get('RAILWAY_POSTGRES_PASSWORD') or os.environ.get('POSTGRES_PASSWORD') or os.environ.get('DB_PASSWORD'),
                'HOST': os.environ.get('RAILWAY_POSTGRES_HOST') or os.environ.get('POSTGRES_HOST') or os.environ.get('DB_HOST'),
                'PORT': os.environ.get('RAILWAY_POSTGRES_PORT') or os.environ.get('POSTGRES_PORT') or os.environ.get('DB_PORT', '5432'),
            }
        }
    else:
        # Fallback to SQLite if PostgreSQL vars are missing
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / 'db.sqlite3',
            }
        }
elif os.environ.get('POSTGRES_HOST'):
    # Manual PostgreSQL configuration
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB') or os.environ.get('DB_NAME'),
            'USER': os.environ.get('POSTGRES_USER') or os.environ.get('DB_USER'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD') or os.environ.get('DB_PASSWORD'),
            'HOST': os.environ.get('POSTGRES_HOST') or os.environ.get('DB_HOST'),
            'PORT': os.environ.get('POSTGRES_PORT') or os.environ.get('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Addis_Ababa'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files (CSS, JavaScript, Images)
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'
# Only add staticfiles dir if it exists
static_dir = BASE_DIR / 'static'
STATICFILES_DIRS = [static_dir] if static_dir.exists() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}

# ---------------------------------------------------------------------------
# Media files (uploaded attachments)
# ---------------------------------------------------------------------------
# Cloudflare R2 Storage Configuration
USE_R2_STORAGE = os.environ.get('USE_R2_STORAGE', 'False').lower() in ('true', '1', 'yes')

# Custom storage function
def get_media_storage():
    """Return the appropriate storage backend based on configuration"""
    if USE_R2_STORAGE:
        AWS_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
        AWS_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
        AWS_STORAGE_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')
        AWS_S3_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL')
        
        if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME, AWS_S3_ENDPOINT_URL]):
            print("WARNING: R2 storage enabled but missing required environment variables. Falling back to local storage.")
            from django.core.files.storage import FileSystemStorage
            return FileSystemStorage(location=str(BASE_DIR / 'media'), base_url='/media/')
        else:
            from storages.backends.s3boto3 import S3Boto3Storage
            return S3Boto3Storage(
                bucket_name=AWS_STORAGE_BUCKET_NAME,
                endpoint_url=AWS_S3_ENDPOINT_URL,
                access_key=AWS_ACCESS_KEY_ID,
                secret_key=AWS_SECRET_ACCESS_KEY,
                region_name='auto',
                addressing_style='path',
                file_overwrite=False,
            )
    else:
        from django.core.files.storage import FileSystemStorage
        return FileSystemStorage(location=str(BASE_DIR / 'media'), base_url='/media/')

if USE_R2_STORAGE:
    # Use Cloudflare R2 for production
    AWS_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL')  # e.g., https://<accountid>.r2.cloudflarestorage.com
    AWS_S3_REGION_NAME = 'auto'
    AWS_S3_CUSTOM_DOMAIN = os.environ.get('R2_CUSTOM_DOMAIN')  # Optional: custom domain for serving files
    
    # Validate required settings
    if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME, AWS_S3_ENDPOINT_URL]):
        print("WARNING: R2 storage enabled but missing required environment variables. Falling back to local storage.")
        USE_R2_STORAGE = False
    else:
        # R2-specific settings
        AWS_S3_OBJECT_PARAMETERS = {
            'CacheControl': 'max-age=86400',
        }
        
        # Storage backend
        DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
        
        # Additional R2-specific settings
        AWS_S3_ADDRESSING_STYLE = 'path'
        AWS_S3_FILE_OVERWRITE = False
        
        # Use /media/ URL for proxy approach to avoid CORB
        MEDIA_URL = '/media/'
        
        MEDIA_ROOT = ''
        print(f"R2 Storage enabled with proxy: Bucket={AWS_STORAGE_BUCKET_NAME}, Endpoint={AWS_S3_ENDPOINT_URL}")

if not USE_R2_STORAGE:
    # For Railway/local development, use local filesystem
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        MEDIA_ROOT = BASE_DIR / 'media'
    else:
        MEDIA_ROOT = BASE_DIR / 'media'
    MEDIA_URL = '/media/'
    print("Using local filesystem for media storage")

# ---------------------------------------------------------------------------
# CORS Settings for iframe preview
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://lms.pro.et",
]

# Add R2 endpoint if configured
if USE_R2_STORAGE and AWS_S3_ENDPOINT_URL:
    CORS_ALLOWED_ORIGINS.append(AWS_S3_ENDPOINT_URL)
    if AWS_S3_CUSTOM_DOMAIN:
        CORS_ALLOWED_ORIGINS.append(f"https://{AWS_S3_CUSTOM_DOMAIN}")

# Allow all origins for R2 media files in development
if DEBUG and USE_R2_STORAGE:
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOW_CREDENTIALS = False
else:
    CORS_ALLOW_CREDENTIALS = True

# Allow same-origin iframes for media preview
X_FRAME_OPTIONS = 'SAMEORIGIN'

# ---------------------------------------------------------------------------
# Crispy Forms
# ---------------------------------------------------------------------------
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# ---------------------------------------------------------------------------
# Default primary key field type
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# File upload limits (10 MB)
# ---------------------------------------------------------------------------
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# Email Configuration
# ---------------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'  # For development
DEFAULT_FROM_EMAIL = 'noreply@auctionethiopia.com'
SITE_URL = 'http://127.0.0.1:8000'

# For production, configure SMTP:
# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST = 'smtp.gmail.com'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
# EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')

# ---------------------------------------------------------------------------
# Celery Configuration (for async email sending)
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'letters': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
import logging
import sys
from pathlib import Path

logs_dir = BASE_DIR / 'logs'
if not logs_dir.exists():
    try:
        logs_dir.mkdir(exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create logs directory: {e}", file=sys.stderr)
