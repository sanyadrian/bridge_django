"""
URL configuration for OHS Insider Bridge integration.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from lms import views_admin

urlpatterns = [
    # Admin prefix selection (must be before admin.site.urls)
    path('admin/set-prefix/', views_admin.set_prefix, name='set_prefix'),
    path('admin/', admin.site.urls),
    path('', include('lms.urls')),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
