from pathlib import Path

from environs import Env

env = Env()
env.read_env(recurse=False)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = env.str('SECRET_KEY', 'django-insecure-mv0kt+(+=$5xn*pu1p#lk16zrl^pz5zdj8@(ah%glr=gz=nm9m')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', [])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'integrator',
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

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Celery
CELERY_BROKER_URL = env.str('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_BEAT_SCHEDULE = {
    'sync-products-every-10-min': {
        'task': 'integrator.tasks.sync_products',
        'schedule': 600,
    },
}

# E-shop API
ESHOP_API_BASE_URL = env.str('ESHOP_API_BASE_URL', 'https://api.fake-eshop.cz/v1')
ESHOP_API_KEY = env.str('ESHOP_API_KEY', 'symma-secret-token')
ESHOP_API_RATE_LIMIT = env.int('ESHOP_API_RATE_LIMIT', 5)

# Sync providers — swap via env or override in dev.py/prod.py
SYNC_SOURCE_CLASS = env.str('SYNC_SOURCE_CLASS', 'integrator.sources.json_source.JsonFileSource')
SYNC_CLIENT_CLASS = env.str('SYNC_CLIENT_CLASS', 'integrator.clients.eshop_client.EshopClient')
