"""
OpenID Connect endpoints for OHS Insider Bridge SSO.
"""
import base64
import secrets
import urllib.parse

import redis
from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseRedirect, JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404

from .models import OHSAccount, OHSAuth, OAuthAuthorizationCode, OAuthAccessToken
from django.utils import timezone
from datetime import timedelta

# Initialize Redis connection (optional - can use database instead)
try:
    r = redis.Redis(**settings.REDIS)
except:
    r = None


def authorize(request):
    """
    OIDC Authorization endpoint.
    Bridge will call this to initiate OAuth2 flow.
    """
    try:
        client_id = request.GET['client_id']
        redirect_uri = request.GET['redirect_uri']
        state = request.GET['state']
    except KeyError:
        return HttpResponseBadRequest(f'Incomplete set of parameters for {request.path}')

    try:
        # Get account from session (set in authenticate_user)
        # Session might not persist across domain redirects, so also check state parameter
        account_id = request.session.get('ohs_account_id')
        unique_id = request.session.get('ohs_unique_id')
        
        # If state parameter contains unique_id (from our redirect), use it
        if state and not unique_id:
            # Try to decode unique_id from state (if we passed it)
            try:
                from urllib.parse import unquote
                potential_unique_id = unquote(state)
                # Check if it looks like an email or unique_id
                if '@' in potential_unique_id or len(potential_unique_id) > 10:
                    account = OHSAccount.objects.filter(unique_id=potential_unique_id).first()
                    if account:
                        unique_id = account.unique_id
            except:
                pass
        
        if account_id:
            account = get_object_or_404(OHSAccount, id=account_id)
        elif unique_id:
            account = get_object_or_404(OHSAccount, unique_id=unique_id)
        else:
            # Fallback: try to find by logged-in user email (if user was logged in)
            if request.user.is_authenticated:
                account = get_object_or_404(OHSAccount, user_email=request.user.email)
            else:
                # No session data and user not logged in - return error
                return HttpResponseForbidden('User session not found. Please start from WordPress login.')
        
        # Verify we have an active OHSAuth (for token endpoint later)
        auth = OHSAuth.objects.filter(is_active=True).first()
        if not auth:
            return HttpResponseBadRequest('Authentication not configured')
        
        # Generate authorization code
        code = secrets.token_urlsafe(16)
        
        # Store code in database (works for server-to-server token exchange)
        expires_at = timezone.now() + timedelta(minutes=5)
        OAuthAuthorizationCode.objects.create(
            code=code,
            account=account,
            client_id=client_id,
            expires_at=expires_at
        )
        
        # Logout user from Django (security best practice)
        auth_logout(request)
        
        # Redirect back to Bridge with authorization code
        return HttpResponseRedirect(
            f'{redirect_uri}?{urllib.parse.urlencode({"code": code, "state": state})}'
        )
        
    except (OHSAuth.DoesNotExist, OHSAccount.DoesNotExist):
        return HttpResponseForbidden('Forbidden')


@csrf_exempt
def token(request):
    """
    OIDC Token endpoint.
    Bridge exchanges authorization code for access token.
    """
    try:
        auth_header = request.headers['Authorization']
        code = request.POST['code']
    except (KeyError, AttributeError):
        return HttpResponseBadRequest('Missing code or authorization header')
    
    # Verify Basic auth credentials
    try:
        # Decode Basic auth
        credentials = auth_header.replace('Basic ', '')
        decoded = base64.b64decode(credentials).decode('utf-8')
        client_id, client_secret = decoded.split(':')
        
        # Verify credentials
        auth = OHSAuth.objects.get(client_id=client_id, is_active=True)
        if auth.client_secret != client_secret:
            return HttpResponseForbidden('Invalid credentials')
    except:
        return HttpResponseForbidden('Invalid credentials')
    
    # Retrieve authorization code from database
    try:
        auth_code = OAuthAuthorizationCode.objects.get(
            code=code,
            used=False,
            expires_at__gt=timezone.now()
        )
        account = auth_code.account
        
        # Mark code as used
        auth_code.used = True
        auth_code.save()
    except OAuthAuthorizationCode.DoesNotExist:
        return HttpResponseForbidden('Invalid or expired authorization code')
    
    # Generate access token
    access_token = secrets.token_urlsafe(16)
    
    # Store access token in database
    expires_at = timezone.now() + timedelta(hours=1)
    OAuthAccessToken.objects.create(
        token=access_token,
        account=account,
        client_id=client_id,
        expires_at=expires_at
    )
    
    return JsonResponse({
        'access_token': access_token,
        'token_type': 'Bearer',
        'expires_in': 3600,
    })


@csrf_exempt
def userinfo(request):
    """
    OIDC UserInfo endpoint.
    Bridge gets user information using access token.
    """
    try:
        auth_header = request.headers['Authorization']
        token_type, token = auth_header.split(' ')
        
        if token_type != 'Bearer':
            return HttpResponseForbidden('Invalid token type')
    except:
        return HttpResponseForbidden('Missing or invalid authorization header')
    
    # Retrieve user data from access token in database
    try:
        access_token_obj = OAuthAccessToken.objects.get(
            token=token,
            expires_at__gt=timezone.now()
        )
        account = access_token_obj.account
    except OAuthAccessToken.DoesNotExist:
        return HttpResponseForbidden('Invalid or expired access token')
    
    claims = {
        'uid': account.unique_id,
        'email': account.user_email,
        'first_name': account.first_name,
        'family_name': account.last_name,
        'sub': account.unique_id,  # OIDC standard subject identifier
    }
    
    return JsonResponse(claims)
