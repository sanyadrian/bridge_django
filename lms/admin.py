"""
Admin configuration for OHS Insider LMS models.
"""
from django.contrib import admin
from .models import (
    OHSAccount, OHSAuth, OHSAccessLog, BridgeSyncTask, 
    OAuthAuthorizationCode, OAuthAccessToken, Course, Program, Package
)


@admin.register(OHSAccount)
class OHSAccountAdmin(admin.ModelAdmin):
    list_display = ['unique_id', 'user_email', 'first_name', 'last_name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['unique_id', 'user_email', 'first_name', 'last_name']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['unique_id']


@admin.register(OHSAuth)
class OHSAuthAdmin(admin.ModelAdmin):
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
class OAuthAuthorizationCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'account', 'client_id', 'used', 'created_at', 'expires_at']
    list_filter = ['used', 'created_at', 'expires_at']
    search_fields = ['code', 'account__unique_id', 'account__user_email']
    readonly_fields = ['created_at', 'expires_at']
    ordering = ['-created_at']


@admin.register(OAuthAccessToken)
class OAuthAccessTokenAdmin(admin.ModelAdmin):
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
