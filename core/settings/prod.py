from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

SECRET_KEY = env.str('SECRET_KEY')  # required — no default

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env.str('POSTGRES_DB', 'symmy_task'),
        'USER': env.str('POSTGRES_USER', 'postgres'),
        'PASSWORD': env.str('POSTGRES_PASSWORD', 'postgres'),
        'HOST': env.str('POSTGRES_HOST', 'db'),
        'PORT': env.str('POSTGRES_PORT', '5432'),
    }
}

# Security
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', True)
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', 31536000)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
