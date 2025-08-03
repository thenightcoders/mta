"""
Django settings for money transfer application.

Generated using Django best practices for production deployment.
"""

import os
from pathlib import Path

from django.utils.translation import gettext_lazy as _
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the .env file
dotenv_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=dotenv_path)

# Get environment variables with fallbacks
debug_value = os.getenv('DEBUG_VALUE', 'True').strip().lower()
allowed_hosts_str = os.getenv('LIST_OF_ALLOWED_HOSTS', default="")
secret_key_value = os.getenv('SECRET_KEY_VALUE')

# Core settings
SECRET_KEY = secret_key_value
DEBUG = debug_value == 'true'
LIST_OF_ALLOWED_HOSTS = allowed_hosts_str.split(',') if allowed_hosts_str else []
ALLOWED_HOSTS = ["*"] if DEBUG else LIST_OF_ALLOWED_HOSTS

# Admin configuration
ADMIN_NAME = os.getenv('ADMIN_NAME', default="")
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', default="")

# Site configuration
SITE_ID = 1
SITE_NAME = os.getenv('SITE_NAME', 'Money Transfer Platform')
SITE_DESCRIPTION = os.getenv('SITE_DESCRIPTION', 'Secure Money Transfer Application')

# Application definition
INSTALLED_APPS = [
    # Django core apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.sites',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.admindocs',

    # Third party apps
    'phonenumber_field',
    'django_q',

    # Local apps
    'users',
    'stock',
    'transfers',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'users.signals.ActivityLoggingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.contrib.admindocs.middleware.XViewMiddleware',
]

# URL configuration
ROOT_URLCONF = 'config.urls'

# Template configuration
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
                'users.context_processors.site_info',
            ],
        },
    },
]

# WSGI application
WSGI_APPLICATION = 'config.wsgi.application'

# Database configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Authentication
AUTH_USER_MODEL = 'users.User'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# Static files configuration
if DEBUG:
    STATICFILES_DIRS = [
        BASE_DIR / "static",
    ]
else:
    STATIC_ROOT = os.path.join(BASE_DIR, 'static')

STATIC_URL = '/static/'

# Media files
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_URL = '/media/'

# Cache configuration
CACHES_LOCATION = os.path.join(BASE_DIR, '.cache')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': CACHES_LOCATION,
    }
}

# User activity tracking
USER_ONLINE_TIMEOUT = 300  # 5 minutes
USER_LAST_SEEN_TIMEOUT = 60 * 60 * 24 * 7  # 1 week

# Session configuration
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 1800  # 30 minutes in seconds
SESSION_SAVE_EVERY_REQUEST = True

# Message storage
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

# Admin configuration
ADMINS = [
    (ADMIN_NAME, ADMIN_EMAIL),
]
MANAGERS = ADMINS

# Security settings for production
if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True

    SECURE_HSTS_SECONDS = 60
    SECURE_HSTS_PRELOAD = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# Email configuration
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', default="")
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', default="")

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = EMAIL_HOST_USER
EMAIL_HOST_PASSWORD = EMAIL_HOST_PASSWORD

# Conditional TLS/SSL based on port
EMAIL_USE_TLS = EMAIL_PORT != 465
EMAIL_USE_SSL = EMAIL_PORT == 465

EMAIL_SUBJECT_PREFIX = ""
EMAIL_USE_LOCALTIME = True
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
SERVER_EMAIL = EMAIL_HOST_USER

# Internationalization
LANGUAGE_CODE = 'fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_L10N = True
USE_TZ = True

LANGUAGES = (
    ('en', _('English')),
    ('fr', _('French')),
)

LOCALE_PATHS = (
    os.path.join(BASE_DIR / 'locale'),
)

# Django Q Cluster configuration for background tasks
USE_DJANGO_Q_FOR_EMAILS=os.getenv('USE_DJANGO_Q_FOR_EMAILS', 'False').strip().lower() == 'true'
Q_CLUSTER = {
    'name': 'MoneyTransferORM',
    'workers': 4,
    'timeout': 90,
    'retry': 120,
    'queue_limit': 50,
    'bulk': 10,
    'orm': 'default',
    'save_limit': 250,
    'max_attempts': 1,
    'attempt_count': 1,
    'cached': False,
    'sync': DEBUG,  # Run synchronously in development
}

# Logging configuration
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
            'formatter': 'verbose' if DEBUG else 'simple',
            'level': 'DEBUG' if DEBUG else 'ERROR',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
            'level': 'INFO',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'] if DEBUG else ['console', 'file'],
            'level': 'INFO', # 'DEBUG' if DEBUG else 'ERROR',
            'propagate': False,
        },
        'users.views': {
            'handlers': ['console'] if DEBUG else ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'transfers.views': {
            'handlers': ['console'] if DEBUG else ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'stock.views': {
            'handlers': ['console'] if DEBUG else ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
logs_dir = BASE_DIR / 'logs'
if not logs_dir.exists():
    logs_dir.mkdir(parents=True, exist_ok=True)

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Content Security Policy (if you add django-csp later)
CSP_IMG_SRC = ("'self'", "data:", "blob:", "filesystem:")
CSP_FRAME_SRC = ("'self'",)

# URL trailing slash behavior
APPEND_SLASH = True
