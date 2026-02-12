"""
Views for OHS Insider Bridge authentication.
"""
import hashlib
import hmac
import time
import json
import base64
import logging
from urllib.parse import urlencode, quote

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User

from .models import OHSAccount, OHSAuth, OHSAccessLog, BridgeSyncTask, PendingOIDCLogin


def get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def sign_token(data, secret):
    """Create HMAC signature for token data."""
    querystring = urlencode(data, doseq=True)
    signature = hmac.new(
        secret.encode('utf-8'),
        querystring.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"{querystring}&signature={signature}"


def verify_token(token, secret):
    """Verify HMAC signature for token."""
    try:
        querystring, signature = token.rsplit('&signature=')
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            querystring.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        if signature != expected_signature:
            return None
            
        # Parse the querystring back to dict
        data = {}
        for pair in querystring.split('&'):
            if '=' in pair:
                key, value = pair.split('=', 1)
                data[key] = value
        return data
    except:
        return None


@csrf_exempt
@require_http_methods(["POST"])
def wordpress_login_notification(request):
    """
    Handle login notifications from OHS Insider WordPress.
    """
    try:
        # Parse the request data
        data = json.loads(request.body)
        
        # Verify the signature
        signature = data.get('signature')
        if not signature:
            return HttpResponseBadRequest('Missing signature')
        
        # Try all active auth records to find the matching one
        from .views_sync import verify_signature_multi_auth
        auth = verify_signature_multi_auth(data, signature)
        if not auth:
            return HttpResponseBadRequest('Invalid signature')
        
        # Check timestamp (within 5 minutes)
        timestamp = int(data.get('timestamp', 0))
        if abs(time.time() - timestamp) > 300:
            return HttpResponseBadRequest('Token expired')
        
        # Get or create OHS account
        unique_id = data.get('unique_id')
        if not unique_id:
            return HttpResponseBadRequest('Missing unique_id')
        
        account, created = OHSAccount.objects.get_or_create(
            unique_id=unique_id,
            defaults={
                'user_email': data.get('email', ''),
                'first_name': data.get('first_name', ''),
                'last_name': data.get('last_name', ''),
                'bridge_subaccount_id': data.get('bridge_subaccount_id', ''),
            }
        )
        
        if not created:
            # Update existing account
            account.user_email = data.get('email', account.user_email)
            account.first_name = data.get('first_name', account.first_name)
            account.last_name = data.get('last_name', account.last_name)
            account.bridge_subaccount_id = data.get('bridge_subaccount_id', account.bridge_subaccount_id)
            account.save()
        
        # Log the access
        OHSAccessLog.objects.create(
            account=account,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            success=True
        )
        
        # Queue sync task
        BridgeSyncTask.objects.create(
            account=account,
            task_type=BridgeSyncTask.TASK_TYPE_USER
        )
        
        return HttpResponse('OK')
        
    except Exception as e:
        return HttpResponseBadRequest(f'Error: {str(e)}')


def authenticate_user(request, unique_id):
    """
    Authenticate user and redirect to Bridge LMS.
    Creates Django user if needed and logs them in for OIDC flow.
    """
    try:
        from urllib.parse import unquote
        logger = logging.getLogger(__name__)
        
        account = None
        email = request.GET.get('email')
        
        # FIRST: Try by email (since we now use email as unique_id)
        # This is the primary lookup method
        if email:
            try:
                account = OHSAccount.objects.get(unique_id=email, is_active=True)
                logger.info(f"Found account by email as unique_id: {email}")
            except OHSAccount.DoesNotExist:
                # Also try by user_email field
                try:
                    account = OHSAccount.objects.get(user_email=email, is_active=True)
                    logger.info(f"Found account by user_email field: {email}")
                except OHSAccount.DoesNotExist:
                    pass
                except OHSAccount.MultipleObjectsReturned:
                    # If multiple, get the first one
                    account = OHSAccount.objects.filter(user_email=email, is_active=True).first()
                    logger.info(f"Found account by user_email (multiple existed): {email}")
        
        # FALLBACK: Try by original unique_id (for backwards compatibility)
        if not account:
            decoded_unique_id = unquote(unique_id.replace(' ', '+'))
            
            for try_id in [decoded_unique_id, unique_id, unique_id.replace(' ', '+'), unique_id.replace('+', ' ')]:
                try:
                    account = OHSAccount.objects.get(unique_id=try_id, is_active=True)
                    logger.info(f"Found account by unique_id: {try_id}")
                    break
                except OHSAccount.DoesNotExist:
                    continue
        
        if not account:
            logger.warning(f"Account not found for unique_id: {unique_id}")
            if email:
                logger.warning(f"Also tried email: {email}")
            
            # If a fallback_url was provided (user's Bridge unique_url), redirect there
            # This allows unsynced users to use their regular Bridge login
            fallback_url = request.GET.get('fallback_url')
            if fallback_url and fallback_url.startswith('https://') and 'bridgeapp.com' in fallback_url:
                logger.info(f"Redirecting unsynced user to fallback_url: {fallback_url}")
                return HttpResponseRedirect(fallback_url)
            
            return HttpResponseBadRequest(f'Account not found. unique_id: {unique_id}' + (f', email: {email}' if email else ''))
        
        # Log the access attempt
        OHSAccessLog.objects.create(
            account=account,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            success=True
        )
        
        # Get or create Django User for OIDC authentication
        django_user, created = User.objects.get_or_create(
            username=account.unique_id,
            defaults={
                'email': account.user_email,
                'first_name': account.first_name,
                'last_name': account.last_name,
            }
        )
        
        if not created:
            # Update existing user
            django_user.email = account.user_email
            django_user.first_name = account.first_name
            django_user.last_name = account.last_name
            django_user.save()
        
        # Log the user into Django (required for OIDC authorize endpoint)
        auth_login(request, django_user)
        
        # Store account info in session for OIDC endpoint
        request.session['ohs_account_id'] = account.id
        request.session['ohs_unique_id'] = account.unique_id
        request.session.save()  # Ensure session is saved
        
        # Also create a PendingOIDCLogin record as fallback
        # Session cookies may not survive cross-domain redirects (Django → Bridge → Django)
        # The pending login is matched by IP address in /openid/authorize/
        client_ip = get_client_ip(request)
        try:
            # Clean up old pending logins for this IP (older than 5 min)
            from django.utils import timezone
            from datetime import timedelta
            PendingOIDCLogin.objects.filter(
                ip_address=client_ip,
                created_at__lt=timezone.now() - timedelta(minutes=5)
            ).delete()
            # Mark any existing pending logins for this IP as consumed
            PendingOIDCLogin.objects.filter(ip_address=client_ip, consumed=False).update(consumed=True)
            # Create new pending login
            PendingOIDCLogin.objects.create(account=account, ip_address=client_ip)
            logger.info(f"Created PendingOIDCLogin for {account.unique_id} from IP {client_ip}")
        except Exception as e:
            logger.warning(f"Failed to create PendingOIDCLogin: {e}")
        
        # Build Bridge subaccount URL
        # All Bridge subaccounts follow the pattern: name-safetynow.bridgeapp.com
        bridge_subdomain = account.bridge_subaccount_id
        if '-safetynow' not in bridge_subdomain:
            bridge_subdomain = f"{bridge_subdomain}-safetynow"
        
        # Redirect directly to Bridge learner courses page
        # Bridge will detect external auth configured and trigger OIDC flow automatically
        # This bypasses the /login endpoint which has 503 issues
        # We rely on session data (ohs_account_id, ohs_unique_id) stored above
        # The session should persist across the redirect to Bridge
        bridge_url = f"https://{bridge_subdomain}.bridgeapp.com/learner/courses"
        
        return HttpResponseRedirect(bridge_url)
        
    except OHSAccount.MultipleObjectsReturned:
        logger = logging.getLogger(__name__)
        logger.error(f"Multiple accounts found for unique_id: {unique_id}")
        return HttpResponseBadRequest('Multiple accounts found')
    except Exception as e:
        return HttpResponseBadRequest(f'Error: {str(e)}')


def bridge_sso_callback(request):
    """
    Handle callback from Bridge LMS after authentication.
    """
    token = request.GET.get('token')
    if not token:
        return HttpResponseBadRequest('Missing token')
    
    try:
        # Decode the token
        decoded_token = base64.b64decode(token.encode('utf-8')).decode('utf-8')
        
        # Verify the token
        auth = OHSAuth.objects.filter(is_active=True).first()
        if not auth:
            return HttpResponseBadRequest('Authentication not configured')
        
        user_data = verify_token(decoded_token, auth.client_secret)
        if not user_data:
            return HttpResponseBadRequest('Invalid token')
        
        # Get the account
        account = get_object_or_404(OHSAccount, unique_id=user_data['user_id'])
        
        # Log successful authentication
        OHSAccessLog.objects.create(
            account=account,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            success=True
        )
        
        # Redirect to user's specific subaccount
        subaccount_url = f"{auth.bridge_base_url}/{account.bridge_subaccount_id}/learner/courses"
        return HttpResponseRedirect(subaccount_url)
        
    except Exception as e:
        return HttpResponseBadRequest(f'Error: {str(e)}')


def health_check(request):
    """
    Health check endpoint for monitoring.
    """
    return HttpResponse('OK')
