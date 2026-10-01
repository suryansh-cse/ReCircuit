"""
ReCircuit Django settings — Day 1 foundation.

Keep it simple and student-friendly:
- SQLite for development (easy migrate to PostgreSQL later: just swap DATABASES)
- Templates in /templates, static in /static
- DRF enabled for REST APIs
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-recircuit-dev-only-change-in-production'

DEBUG = True

ALLOWED_HOSTS = ['*']


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    # Local apps
    'core',
    'bins',
    'waste',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.alert_counts',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


# Database — SQLite for dev. To move to PostgreSQL later, replace this dict
# with the psycopg2/postgres config (no model changes needed).
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True


STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Auth redirects (Day 2)
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# DRF — open by default on Day 1; we lock down per-view from Day 2 onwards.
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
}

# ReCircuit thresholds — single source of truth for bins + alert engine.
RECIRCUIT_FILL_WARNING_AT = 60.0   # 60-79%  -> Warning
RECIRCUIT_FILL_CRITICAL_AT = 80.0  # 80-100% -> Collection Required
RECIRCUIT_TEMP_WARNING_AT = 40.0   # °C — HIGH_TEMPERATURE warning at/above this
RECIRCUIT_TEMP_CRITICAL_AT = 45.0  # °C — HIGH_TEMPERATURE critical at/above this
RECIRCUIT_OFFLINE_AFTER_MINUTES = 15
