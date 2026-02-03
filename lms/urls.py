"""
URL configuration for OHS Insider LMS app.
"""
from django.urls import path
from . import views, views_openid, views_sync

urlpatterns = [
    # Authentication endpoints
    path('auth/<str:unique_id>/', views.authenticate_user, name='authenticate_user'),
    path('onlogin/', views.wordpress_login_notification, name='wordpress_login_notification'),
    path('bridge/callback/', views.bridge_sso_callback, name='bridge_sso_callback'),
    
    # OpenID Connect endpoints (for Bridge SSO)
    path('openid/authorize/', views_openid.authorize, name='openid_authorize'),
    path('openid/token/', views_openid.token, name='openid_token'),
    path('openid/userinfo/', views_openid.userinfo, name='openid_userinfo'),
    
    # Sync endpoints
    path('api/sync-user-to-bridge/', views_sync.sync_user_to_bridge, name='sync_user_to_bridge'),
    path('api/create-bridge-subaccount/', views_sync.create_bridge_subaccount, name='create_bridge_subaccount'),
    path('api/import-users-from-plugin/', views_sync.import_users_from_plugin, name='import_users_from_plugin'),
    path('api/sync-existing-user-sso/', views_sync.sync_existing_user_sso, name='sync_existing_user_sso'),
    path('api/sync-existing-users-batch/', views_sync.sync_existing_users_batch, name='sync_existing_users_batch'),
    
    # Health check
    path('health/', views.health_check, name='health_check'),
]
