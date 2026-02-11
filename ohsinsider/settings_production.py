"""
Production settings for OHS Insider Bridge integration.
Import this in your production environment.
"""
import os
from pathlib import Path
from decouple import config, Csv
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Import base settings AFTER BASE_DIR is defined
from .settings import *

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default=os.environ.get('SECRET_KEY'))

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

# Allowed hosts - your production domain
ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    cast=Csv(),
    default=[
        'bridgeadmin1.safetynow.com',
        '54.224.65.225',
        'localhost',
        '127.0.0.1',
        '0.0.0.0'
    ]
)



# CSRF trusted origins - your production domain with https
# CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', cast=Csv(), default=['https://bridgeadmin1.safetynow.com'])
CSRF_TRUSTED_ORIGINS = [
    'http://bridgeadmin1.safetynow.com',
    'http://54.224.65.225',
]


# Database - Use PostgreSQL in production
DATABASES = {
    'default': dj_database_url.config(
        default=config('DATABASE_URL'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Static files - Use WhiteNoise for serving static files
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Add WhiteNoise middleware (should be after SecurityMiddleware)
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

# Security settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=True, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=True, cast=bool)
# SameSite=None is required for the OIDC flow: Django → Bridge → Django
# The session cookie must survive the cross-domain redirect chain
SESSION_COOKIE_SAMESITE = 'None'
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Redis configuration
# Support both standard Redis and Redis Cluster Mode
REDIS_CLUSTER_MODE = config('REDIS_CLUSTER_MODE', default=False, cast=bool)
REDIS_SSL = config('REDIS_SSL', default='auto', cast=str)  # 'auto', 'true', 'false'
REDIS = {
    'host': config('REDIS_HOST', default='localhost'),
    'port': config('REDIS_PORT', default=6379, cast=int),
    'db': config('REDIS_DB', default=0, cast=int),
    'decode_responses': False,
}
# Add SSL settings if using ElastiCache with encryption in transit
if REDIS_SSL == 'auto':
    # Auto-detect: if host contains 'cache.amazonaws.com', use SSL
    if 'cache.amazonaws.com' in REDIS['host']:
        REDIS['ssl'] = True
        REDIS['ssl_cert_reqs'] = 'required'
elif REDIS_SSL.lower() == 'true':
    REDIS['ssl'] = True
    REDIS['ssl_cert_reqs'] = 'required'

# Bridge API configuration
OHS_BRIDGE_BASE_URL = config('OHS_BRIDGE_BASE_URL', default='https://safetynow.bridgeapp.com')
OHS_BRIDGE_API_KEY = config('BRIDGE_API_KEY')
OHS_BRIDGE_API_SECRET = config('BRIDGE_API_SECRET')

# Django Base URL for SSO callbacks
OHS_BRIDGE_BASE_URL_DJANGO = config('OHS_BRIDGE_BASE_URL_DJANGO', default='')

# Email configuration (optional)
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@yourdomain.com')

# Logging - More detailed in production
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'maxBytes': 1024 * 1024 * 50,  # 50 MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'bridge_api_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'bridge_api.log',
            'maxBytes': 1024 * 1024 * 50,  # 50 MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'sync_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'sync.log',
            'maxBytes': 1024 * 1024 * 50,  # 50 MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'lms.bridge_api': {
            'handlers': ['bridge_api_file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'lms.views_sync': {
            'handlers': ['sync_file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'lms': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
}

# Performance optimizations
CONN_MAX_AGE = 600  # Database connection pooling

# FORCE disable HTTPS redirect (temporary)
# SECURE_SSL_REDIRECT = False
# SECURE_PROXY_SSL_HEADER = None
# USE_X_FORWARDED_HOST = False

# SESSION_COOKIE_SECURE = False
# CSRF_COOKIE_SECURE = False
