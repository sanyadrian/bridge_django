"""
Admin configuration for OHS Insider LMS models.
"""
import json
from django.contrib import admin
from django.http import JsonResponse
from django.test import RequestFactory
from django.urls import reverse
from .models import (
    OHSAccount, OHSIAccount, HRIAccount, ILTAccount,
    OHSAuth, OHSAccessLog, BridgeSyncTask, 
    OAuthAuthorizationCode, OAuthAccessToken, Course, Program, Package
)
from .views_sync import sync_existing_user_sso, sync_existing_users_batch
from .forms import PrefixSelectForm


class PrefixSelectionMixin:
    """Mixin to add prefix selection dropdown to admin changelist."""
    
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        selected_prefix = request.session.get('admin_prefix', '')
        extra_context['prefix_select_form'] = PrefixSelectForm(
            initial={'prefix': selected_prefix}
        )
        extra_context['set_prefix_url'] = reverse('set_prefix')
        return super().changelist_view(request, extra_context=extra_context)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        selected_prefix = request.session.get('admin_prefix')
        if selected_prefix:
            # For models with account relationship, filter through that
            if hasattr(self.model, 'account'):
                # Filter by account's prefix
                qs = qs.filter(account__prefix=selected_prefix)
            elif hasattr(self.model, 'prefix'):
                # Direct prefix field
                qs = qs.filter(prefix=selected_prefix)
        return qs


@admin.register(OHSAccount)
class OHSAccountAdmin(PrefixSelectionMixin, admin.ModelAdmin):
    list_display = ['unique_id', 'user_email', 'first_name', 'last_name', 'prefix', 'unique_url', 'is_active', 'created_at']
    list_filter = ['prefix', 'is_active', 'created_at']
    search_fields = ['unique_id', 'user_email', 'first_name', 'last_name', 'unique_url', 'bridge_subaccount_id']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['prefix', 'unique_id']
    list_per_page = 50
    show_full_result_count = False
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('unique_id', 'prefix', 'user_email', 'first_name', 'last_name', 'is_active')
        }),
        ('Bridge Integration', {
            'fields': ('bridge_subaccount_id', 'unique_url', 'company_name', 'bridge_user_id', 'bridge_account_id')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['sync_sso_selected']
    
    def sync_sso_selected(self, request, queryset):
        """Admin action to sync SSO for selected accounts."""
        from urllib.parse import urlparse
        from .bridge_api import BridgeAPI
        from django.conf import settings
        
        auth = OHSAuth.objects.filter(is_active=True).first()
        if not auth:
            self.message_user(request, "No active authentication configured", level='error')
            return
        
        bridge_api = BridgeAPI()
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        # Get Django base URL from settings or request
        try:
            django_base_url = getattr(settings, 'OHS_BRIDGE_BASE_URL', None)
            if not django_base_url:
                # Try to get from request
                django_base_url = request.build_absolute_uri('/').rstrip('/')
                django_base_url = django_base_url.split('/admin/')[0]
        except:
            django_base_url = 'https://bridgeadmin.safetynow.com'
        
        for account in queryset:
            if not account.unique_url:
                skipped_count += 1
                continue
            
            try:
                # Extract subdomain from unique_url
                parsed_url = urlparse(account.unique_url)
                subdomain = parsed_url.netloc.split('.')[0]
                if not subdomain:
                    failed_count += 1
                    continue
                
                # Configure SSO
                bridge_api.configure_sso(
                    subdomain=subdomain,
                    django_base_url=django_base_url,
                    client_id=auth.client_id,
                    client_secret=auth.client_secret,
                    login_attribute='email'
                )
                
                # Update bridge_subaccount_id if not set
                if not account.bridge_subaccount_id:
                    account.bridge_subaccount_id = subdomain
                    account.save()
                
                success_count += 1
            except Exception as e:
                failed_count += 1
                self.message_user(request, f"Error syncing {account.unique_id}: {str(e)}", level='warning')
        
        self.message_user(request, 
            f"SSO sync completed: {success_count} succeeded, {failed_count} failed, {skipped_count} skipped",
            level='success')
    sync_sso_selected.short_description = "Sync SSO for selected accounts"


@admin.register(OHSAuth)
class OHSAuthAdmin(PrefixSelectionMixin, admin.ModelAdmin):
    list_display = ['name', 'client_id', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    readonly_fields = ['client_id', 'client_secret', 'created_at']
    ordering = ['name']


@admin.register(OHSAccessLog)
class OHSAccessLogAdmin(admin.ModelAdmin):
    list_display = ['account', 'access_time', 'ip_address', 'success']
    list_filter = ['success', 'access_time']
    search_fields = ['account__unique_id', 'account__user_email', 'ip_address']
    readonly_fields = ['access_time']
    ordering = ['-access_time']


@admin.register(BridgeSyncTask)
class BridgeSyncTaskAdmin(admin.ModelAdmin):
    list_display = ['account', 'task_type', 'status', 'created_at', 'completed_at']
    list_filter = ['task_type', 'status', 'created_at']
    search_fields = ['account__unique_id', 'account__user_email']
    readonly_fields = ['created_at', 'started_at', 'completed_at']
    ordering = ['-created_at']


@admin.register(OAuthAuthorizationCode)
class OAuthAuthorizationCodeAdmin(PrefixSelectionMixin, admin.ModelAdmin):
    list_display = ['code', 'account', 'client_id', 'used', 'created_at', 'expires_at']
    list_filter = ['used', 'created_at', 'expires_at']
    search_fields = ['code', 'account__unique_id', 'account__user_email']
    readonly_fields = ['created_at', 'expires_at']
    ordering = ['-created_at']


@admin.register(OAuthAccessToken)
class OAuthAccessTokenAdmin(PrefixSelectionMixin, admin.ModelAdmin):
    list_display = ['token', 'account', 'client_id', 'created_at', 'expires_at']
    list_filter = ['created_at', 'expires_at']
    search_fields = ['token', 'account__unique_id', 'account__user_email']
    readonly_fields = ['created_at', 'expires_at']
    ordering = ['-created_at']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'bridge_id', 'active', 'updated_at']
    list_filter = ['active', 'updated_at']
    search_fields = ['title', 'description']
    readonly_fields = ['bridge_id', 'created_at', 'updated_at']
    ordering = ['title']


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ['title', 'bridge_id', 'active', 'updated_at']
    list_filter = ['active', 'updated_at']
    search_fields = ['title', 'description']
    readonly_fields = ['bridge_id', 'created_at', 'updated_at']
    ordering = ['title']


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ['name', 'prefix', 'active', 'course_count', 'program_count', 'created_at']
    list_filter = ['prefix', 'active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    filter_horizontal = ['courses', 'programs']
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'prefix', 'description', 'active')
        }),
        ('Content', {
            'fields': ('courses', 'programs'),
            'description': 'Select courses and programs to include in this package. '
                          'Package will be auto-assigned to subaccounts based on prefix.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def course_count(self, obj):
        return obj.courses.count()
    course_count.short_description = 'Courses'
    
    def program_count(self, obj):
        return obj.programs.count()
    program_count.short_description = 'Programs'
