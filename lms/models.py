"""
Models for OHS Insider Bridge integration.
"""
import secrets
from django.db import models
from django.contrib.auth.models import User


class OHSAccount(models.Model):
    """
    OHS Insider account linking unique IDs to Bridge subaccounts.
    """
    PREFIX_CHOICES = [
        ('ohsi', 'OHSI'),
        ('hri', 'HRI'),
        ('ilt', 'ILT'),
    ]
    
    unique_id = models.CharField(
        max_length=50, 
        unique=True, 
        db_index=True,
        help_text="OHS Insider unique ID (e.g., 2019513-AIR-G-48)"
    )
    prefix = models.CharField(
        max_length=10,
        choices=PREFIX_CHOICES,
        blank=True,
        null=True,
        db_index=True,
        help_text="Bridge subaccount prefix (ohsi/hri/ilt) - used to identify account type"
    )
    bridge_subaccount_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Bridge LMS subaccount identifier (subdomain)"
    )
    unique_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Bridge subaccount URL (e.g., https://ohsiaircanada-safetynow.bridgeapp.com)"
    )
    company_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Company name for subaccount creation"
    )
    user_email = models.EmailField()
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Bridge LMS integration fields
    bridge_user_id = models.PositiveIntegerField(null=True, blank=True)
    bridge_account_id = models.PositiveIntegerField(null=True, blank=True)
    
    class Meta:
        db_table = 'ohs_account'
        ordering = ['unique_id']
        verbose_name = 'Account'
        verbose_name_plural = 'Accounts'
    
    def __str__(self):
        return f"{self.unique_id} - {self.user_email}"


# Proxy models for separate admin sections
class OHSIAccount(OHSAccount):
    """Proxy model for OHSI accounts only."""
    class Meta:
        proxy = True
        verbose_name = 'OHSI Account'
        verbose_name_plural = 'OHSI Accounts'


class HRIAccount(OHSAccount):
    """Proxy model for HRI accounts only."""
    class Meta:
        proxy = True
        verbose_name = 'HRI Account'
        verbose_name_plural = 'HRI Accounts'


class ILTAccount(OHSAccount):
    """Proxy model for ILT accounts only."""
    class Meta:
        proxy = True
        verbose_name = 'ILT Account'
        verbose_name_plural = 'ILT Accounts'


class OHSAuth(models.Model):
    """
    Authentication credentials for OHS Insider WordPress integration.
    """
    name = models.CharField(max_length=100, unique=True)

    # Django migrations cannot serialize lambdas; use named callables instead
    def generate_client_id():
        return secrets.token_hex(8)

    def generate_client_secret():
        return secrets.token_hex(16)

    client_id = models.CharField(
        max_length=16,
        unique=True,
        default=generate_client_id
    )
    client_secret = models.CharField(
        max_length=32,
        default=generate_client_secret
    )
    bridge_base_url = models.URLField(
        default='https://safetynow.bridgeapp.com',
        help_text="Bridge LMS base URL"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'ohs_auth'
        verbose_name = 'Authentication'
        verbose_name_plural = 'Authentications'
    
    def __str__(self):
        return f"{self.name} - {self.client_id}"


class OHSAccessLog(models.Model):
    """
    Log of user access attempts to Bridge LMS.
    """
    account = models.ForeignKey(OHSAccount, on_delete=models.CASCADE, related_name='access_logs')
    access_time = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    
    class Meta:
        db_table = 'ohs_access_log'
        ordering = ['-access_time']
        verbose_name = 'OHS Access Log'
        verbose_name_plural = 'OHS Access Logs'
    
    def __str__(self):
        return f"{self.account.unique_id} - {self.access_time}"


class OAuthAuthorizationCode(models.Model):
    """
    Store OAuth2 authorization codes for token exchange.
    """
    code = models.CharField(max_length=100, unique=True, db_index=True)
    account = models.ForeignKey(OHSAccount, on_delete=models.CASCADE)
    client_id = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'oauth_authorization_code'
        verbose_name = 'Authorization Code'
        verbose_name_plural = 'Authorization Codes'
    
    def __str__(self):
        return f"{self.code} - {self.account.unique_id}"


class OAuthAccessToken(models.Model):
    """
    Store OAuth2 access tokens for userinfo requests.
    """
    token = models.CharField(max_length=100, unique=True, db_index=True)
    account = models.ForeignKey(OHSAccount, on_delete=models.CASCADE)
    client_id = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        db_table = 'oauth_access_token'
        verbose_name = 'Access Token'
        verbose_name_plural = 'Access Tokens'
    
    def __str__(self):
        return f"{self.token} - {self.account.unique_id}"


class BridgeSyncTask(models.Model):
    """
    Background tasks for syncing with Bridge LMS.
    """
    STATUS_PENDING = 'P'
    STATUS_PROCESSING = 'PR'
    STATUS_COMPLETED = 'C'
    STATUS_FAILED = 'F'
    
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]
    
    TASK_TYPE_ACCOUNT = 'A'
    TASK_TYPE_USER = 'U'
    TASK_TYPE_ACCESS = 'AC'
    
    TASK_TYPE_CHOICES = [
        (TASK_TYPE_ACCOUNT, 'Account Sync'),
        (TASK_TYPE_USER, 'User Sync'),
        (TASK_TYPE_ACCESS, 'Access Grant'),
    ]
    
    account = models.ForeignKey(OHSAccount, on_delete=models.CASCADE, related_name='sync_tasks')
    task_type = models.CharField(max_length=2, choices=TASK_TYPE_CHOICES)
    status = models.CharField(max_length=2, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    
    class Meta:
        db_table = 'bridge_sync_task'
        ordering = ['-created_at']
        verbose_name = 'Bridge Sync Task'
        verbose_name_plural = 'Bridge Sync Tasks'
    
    def __str__(self):
        return f"{self.get_task_type_display()} - {self.account.unique_id} - {self.get_status_display()}"


class PendingOIDCLogin(models.Model):
    """
    Temporary record to track which user initiated an OIDC login.
    Created in /auth/<unique_id>/ and consumed in /openid/authorize/.
    This solves the cross-domain session cookie loss (Django → Bridge → Django).
    """
    account = models.ForeignKey(OHSAccount, on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    consumed = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'pending_oidc_login'
        ordering = ['-created_at']
        verbose_name = 'Pending OIDC Login'
        verbose_name_plural = 'Pending OIDC Logins'
    
    def __str__(self):
        return f"{self.account.unique_id} - {self.ip_address} - {self.created_at}"


class Course(models.Model):
    """
    Course from Bridge LMS.
    """
    bridge_id = models.PositiveIntegerField(db_index=True, unique=True)
    title = models.CharField(max_length=500, db_index=True, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        db_table = 'course'
        ordering = ['title']
        verbose_name = 'Course'
        verbose_name_plural = 'Courses'
    
    def __str__(self):
        return self.title or f'Course {self.bridge_id}'


class Program(models.Model):
    """
    Program from Bridge LMS.
    """
    bridge_id = models.PositiveIntegerField(db_index=True, unique=True)
    title = models.CharField(max_length=500, db_index=True, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        db_table = 'program'
        ordering = ['title']
        verbose_name = 'Program'
        verbose_name_plural = 'Programs'
    
    def __str__(self):
        return self.title or f'Program {self.bridge_id}'


class Package(models.Model):
    """
    Package containing courses and programs for assignment to subaccounts.
    Auto-assigned based on subaccount prefix.
    """
    PREFIX_CHOICES = [
        ('ohsi', 'OHSI'),
        ('ilt', 'ILT'),
        ('hri', 'HRI'),
    ]
    
    name = models.CharField(max_length=200, unique=True)
    prefix = models.CharField(
        max_length=10,
        choices=PREFIX_CHOICES,
        help_text="Subaccount prefix for auto-assignment (ohsi/ilt/hri)"
    )
    description = models.TextField(blank=True)
    courses = models.ManyToManyField(Course, blank=True, related_name='packages')
    programs = models.ManyToManyField(Program, blank=True, related_name='packages')
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'package'
        ordering = ['name']
        verbose_name = 'Package'
        verbose_name_plural = 'Packages'
    
    def __str__(self):
        return f"{self.name} ({self.get_prefix_display()})"
