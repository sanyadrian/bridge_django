"""
Django settings for OHS Insider Bridge integration.
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-change-this-in-production'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

import os

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', 'ohsinsider-bridge.yourdomain.com']

# Allow a public tunnel host (e.g., ngrok) if provided via env var
NGROK_DOMAIN = os.environ.get('NGROK_DOMAIN')
if NGROK_DOMAIN:
    ALLOWED_HOSTS.append(NGROK_DOMAIN)

# Trust public tunnel domain for CSRF (Django 4+ requires scheme)
CSRF_TRUSTED_ORIGINS = [
    'http://localhost',
    'http://127.0.0.1',
]
if NGROK_DOMAIN:
    CSRF_TRUSTED_ORIGINS.append(f'https://{NGROK_DOMAIN}')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'lms',  # Our OHS Insider LMS app
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

ROOT_URLCONF = 'ohsinsider.urls'

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
            ],
        },
    },
]

WSGI_APPLICATION = 'ohsinsider.wsgi.application'

# Database
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

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# OHS Insider specific settings
OHS_BRIDGE_BASE_URL = 'https://safetynow.bridgeapp.com'
OHS_BRIDGE_API_KEY = 'your-bridge-api-key'
OHS_BRIDGE_API_SECRET = 'your-bridge-api-secret'

# Redis configuration for background tasks
REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
}

REDIS_TASK_QUEUE = 'ohsinsider:tasks'
