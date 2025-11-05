"""
URL configuration for OHS Insider LMS app.
"""
from django.urls import path
from . import views, views_openid

urlpatterns = [
    # Authentication endpoints
    path('auth/<str:unique_id>/', views.authenticate_user, name='authenticate_user'),
    path('onlogin/', views.wordpress_login_notification, name='wordpress_login_notification'),
    path('bridge/callback/', views.bridge_sso_callback, name='bridge_sso_callback'),
    
    # OpenID Connect endpoints (for Bridge SSO)
    path('openid/authorize/', views_openid.authorize, name='openid_authorize'),
    path('openid/token/', views_openid.token, name='openid_token'),
    path('openid/userinfo/', views_openid.userinfo, name='openid_userinfo'),
    
    # Health check
    path('health/', views.health_check, name='health_check'),
]
