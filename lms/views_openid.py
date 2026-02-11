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

from .models import OHSAccount, OHSAuth, OAuthAuthorizationCode, OAuthAccessToken, PendingOIDCLogin
from django.utils import timezone
from datetime import timedelta

# Initialize Redis connection (optional - can use database instead)
# Support both standard Redis and Redis Cluster Mode
try:
    if getattr(settings, 'REDIS_CLUSTER_MODE', False):
        from redis.cluster import RedisCluster
        from redis.connection import ConnectionPool
        startup_nodes = [{"host": settings.REDIS['host'], "port": settings.REDIS['port']}]
        r = RedisCluster(
            startup_nodes=startup_nodes,
            decode_responses=False,
            ssl=settings.REDIS.get('ssl', True),
            ssl_cert_reqs=settings.REDIS.get('ssl_cert_reqs', 'required'),
        )
    else:
        r = redis.Redis(**settings.REDIS)
except Exception as e:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Redis connection failed: {e}. Using database fallback.")
    r = None


@csrf_exempt
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
                decoded_state = unquote(state)
                
                # Check if state contains unique_id in format: /learner/courses|unique_id
                if '|' in decoded_state:
                    parts = decoded_state.split('|', 1)
                    if len(parts) == 2:
                        potential_unique_id = parts[1]
                        account = OHSAccount.objects.filter(unique_id=potential_unique_id).first()
                        if account:
                            unique_id = account.unique_id
                # Otherwise, check if it looks like an email or unique_id
                elif '@' in decoded_state or len(decoded_state) > 10:
                    account = OHSAccount.objects.filter(unique_id=decoded_state).first()
                    if account:
                        unique_id = account.unique_id
            except:
                pass
        
        import logging
        logger = logging.getLogger(__name__)
        
        account = None
        
        if account_id:
            account = OHSAccount.objects.filter(id=account_id, is_active=True).first()
            if account:
                logger.info(f"OIDC authorize: found account by session account_id={account_id}")
        
        if not account and unique_id:
            account = OHSAccount.objects.filter(unique_id=unique_id, is_active=True).first()
            if account:
                logger.info(f"OIDC authorize: found account by session unique_id={unique_id}")
        
        if not account and request.user.is_authenticated:
            account = OHSAccount.objects.filter(user_email=request.user.email, is_active=True).first()
            if account:
                logger.info(f"OIDC authorize: found account by authenticated user email={request.user.email}")
        
        # Fallback: look up PendingOIDCLogin by client IP address
        # This is the most reliable method when session cookies are lost across
        # the cross-domain redirect chain (Django → Bridge → Django)
        if not account:
            from .views import get_client_ip
            client_ip = get_client_ip(request)
            try:
                cutoff = timezone.now() - timedelta(minutes=5)
                pending = PendingOIDCLogin.objects.filter(
                    ip_address=client_ip,
                    consumed=False,
                    created_at__gte=cutoff
                ).order_by('-created_at').first()
                if pending:
                    account = pending.account
                    pending.consumed = True
                    pending.save()
                    logger.info(f"OIDC authorize: found account by PendingOIDCLogin IP={client_ip}, account={account.unique_id}")
                else:
                    logger.warning(f"OIDC authorize: no PendingOIDCLogin found for IP={client_ip}")
            except Exception as e:
                logger.warning(f"OIDC authorize: PendingOIDCLogin lookup failed: {e}")
        
        # Last resort: try Referer header (only works for single-user subaccounts)
        if not account:
            from urllib.parse import urlparse
            referer = request.META.get('HTTP_REFERER', '')
            if referer:
                try:
                    parsed = urlparse(referer)
                    hostname = parsed.hostname
                    if hostname and hostname.endswith('.bridgeapp.com') and hostname != 'auth.bridgeapp.com':
                        subdomain = hostname.replace('.bridgeapp.com', '')
                        # Only use Referer if there's exactly ONE account for this subaccount
                        matching = OHSAccount.objects.filter(bridge_subaccount_id=subdomain, is_active=True)
                        if matching.count() == 1:
                            account = matching.first()
                            logger.info(f"OIDC authorize: found single account by Referer subdomain={subdomain}, account={account.unique_id}")
                        else:
                            logger.warning(f"OIDC authorize: Referer subdomain={subdomain} has {matching.count()} accounts, cannot disambiguate")
                except Exception as e:
                    logger.warning(f"OIDC authorize: failed to parse Referer: {e}")
        
        # Check if user submitted the email login form (POST fallback)
        if not account and request.method == 'POST':
            login_email = request.POST.get('email', '').strip()
            if login_email:
                account = OHSAccount.objects.filter(user_email=login_email, is_active=True).first()
                if not account:
                    account = OHSAccount.objects.filter(unique_id=login_email, is_active=True).first()
                if account:
                    logger.info(f"OIDC authorize: found account by email form submission: {login_email}, account={account.unique_id}")
                else:
                    logger.warning(f"OIDC authorize: email form submitted but no account found for: {login_email}")
        
        # Final fallback: show email login form
        if not account:
            from .views import get_client_ip
            client_ip = get_client_ip(request)
            referer = request.META.get('HTTP_REFERER', 'none')
            logger.warning(f"OIDC authorize: showing login form. session_account_id={account_id}, session_unique_id={unique_id}, ip={client_ip}, referer={referer}")
            
            # Preserve all OIDC parameters for the form POST
            error_msg = ''
            if request.method == 'POST' and request.POST.get('email'):
                error_msg = '<p style="color:#c0392b;margin-top:10px;">Account not found. Please check your email and try again.</p>'
            
            login_form = f"""<!DOCTYPE html>
<html>
<head>
    <title>Bridge SSO Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f6fa; margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
        .card {{ background: white; border-radius: 12px; box-shadow: 0 2px 20px rgba(0,0,0,0.1); padding: 40px; max-width: 420px; width: 90%; }}
        h2 {{ margin: 0 0 8px; color: #2c3e50; font-size: 22px; }}
        p {{ color: #666; margin: 0 0 24px; font-size: 14px; }}
        label {{ display: block; margin-bottom: 6px; font-weight: 600; color: #333; font-size: 14px; }}
        input[type=email] {{ width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 16px; box-sizing: border-box; transition: border-color 0.2s; }}
        input[type=email]:focus {{ border-color: #3498db; outline: none; }}
        button {{ width: 100%; padding: 12px; background: #3498db; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; margin-top: 16px; transition: background 0.2s; }}
        button:hover {{ background: #2980b9; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Sign in to Bridge</h2>
        <p>Enter your email address to continue to your eLearning portal.</p>
        <form method="POST" action="{request.get_full_path()}">
            <label for="email">Email Address</label>
            <input type="email" id="email" name="email" required autofocus placeholder="your.email@company.com" value="{request.POST.get('email', '') if request.method == 'POST' else ''}">
            <button type="submit">Continue</button>
            {error_msg}
        </form>
    </div>
</body>
</html>"""
            from django.http import HttpResponse
            return HttpResponse(login_form, status=200)
        
        # Find the matching OHSAuth by client_id, fallback to first active
        auth = OHSAuth.objects.filter(is_active=True, client_id=client_id).first()
        if not auth:
            # Fallback: try matching by account prefix
            if hasattr(account, 'prefix') and account.prefix:
                auth = OHSAuth.objects.filter(is_active=True, name__icontains=account.prefix).first()
            if not auth:
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
        
        # Check if state parameter contains a path (like /learner/courses)
        # We need to redirect to Bridge's redirect_uri so Bridge can process the code
        # But then immediately redirect to courses to avoid the error page
        from urllib.parse import unquote
        decoded_state = unquote(state) if state else ''
        
        # Extract path from state if it's in format: /learner/courses|unique_id
        state_path = decoded_state
        if '|' in decoded_state:
            state_path = decoded_state.split('|', 1)[0]
        
        # If state looks like a path (starts with /), redirect to courses after OAuth
        if state_path.startswith('/') and account.bridge_subaccount_id:
            # Use the account's bridge_subaccount_id and ensure -safetynow suffix
            bridge_subdomain = account.bridge_subaccount_id
            if '-safetynow' not in bridge_subdomain:
                bridge_subdomain = f"{bridge_subdomain}-safetynow"
            
            bridge_courses_url = f"https://{bridge_subdomain}.bridgeapp.com{state_path}"
            
            # If redirect_uri is Bridge's central callback (auth.bridgeapp.com), 
            # we need to redirect there with the code, then Bridge will handle the rest
            # Otherwise, redirect directly to the redirect_uri
            if 'auth.bridgeapp.com/oauth2/callback' in redirect_uri:
                # Bridge's central callback - redirect there with code, Bridge will handle redirect to subaccount
                redirect_uri_with_code = f'{redirect_uri}?{urllib.parse.urlencode({"code": code, "state": state})}'
                
                # Create HTML page that processes OAuth callback in iframe, then redirects to courses
                html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Logging into Bridge...</title>
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            text-align: center;
                            padding: 50px;
                        }}
                    </style>
                </head>
                <body>
                    <h2>Logging you into Bridge...</h2>
                    <p>Please wait...</p>
                    <iframe id="bridgeFrame" style="display:none;" src="{redirect_uri_with_code}"></iframe>
                    <script>
                        // Wait a moment for Bridge to process the code, then redirect to courses
                        setTimeout(function() {{
                            window.location.href = "{bridge_courses_url}";
                        }}, 1000);
                    </script>
                </body>
                </html>
                """
                from django.http import HttpResponse
                return HttpResponse(html_content)
            else:
                # Subaccount-specific redirect_uri - redirect there with code
                redirect_uri_with_code = f'{redirect_uri}?{urllib.parse.urlencode({"code": code, "state": state})}'
                return HttpResponseRedirect(redirect_uri_with_code)
        
        # Fallback: redirect to Bridge's redirect_uri (standard OIDC flow)
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
    
    logger.info(f"Userinfo returning: sub={account.unique_id}, email={account.user_email}, name={account.first_name} {account.last_name}")
    
    return JsonResponse(claims)
