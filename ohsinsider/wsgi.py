"""
WSGI config for OHS Insider Bridge integration.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ohsinsider.settings')

application = get_wsgi_application()
