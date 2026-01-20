"""
Bridge API wrapper for OHS Insider integration.
Handles subaccount and user creation/management in Bridge LMS.
"""
import json
import requests
from django.conf import settings


class BridgeAPIError(Exception):
    """Base exception for Bridge API errors."""
    pass


class BridgeSubaccountExists(BridgeAPIError):
    """Raised when subaccount already exists."""
    pass


class BridgeUserExists(BridgeAPIError):
    """Raised when user already exists."""
    pass


class BridgeAPI:
    """
    Bridge LMS API client for managing subaccounts and users.
    """
    
    def __init__(self, api_key=None, api_secret=None, root_subdomain='safetynow'):
        """
        Initialize Bridge API client.
        
        Args:
            api_key: Bridge API key (from settings if not provided)
            api_secret: Bridge API secret (from settings if not provided)
            root_subdomain: Root Bridge subdomain (default: 'safetynow')
        """
        self.api_key = api_key or getattr(settings, 'OHS_BRIDGE_API_KEY', None)
        self.api_secret = api_secret or getattr(settings, 'OHS_BRIDGE_API_SECRET', None)
        self.root_subdomain = root_subdomain
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Bridge API key and secret must be provided")
        
        self.session = requests.Session()
        self.session.auth = (self.api_key, self.api_secret)
        self.root_base_url = f'https://{root_subdomain}.bridgeapp.com/api/'
    
    def _request(self, method, path, subdomain=None, **kwargs):
        """
        Make a request to Bridge API.
        
        Args:
            method: HTTP method (get, post, put, patch, delete)
            path: API path (e.g., 'admin/sub_accounts')
            subdomain: Subaccount subdomain (None for root account)
            **kwargs: Additional arguments for requests
        
        Returns:
            JSON response data
        """
        base_url = f'https://{subdomain}.bridgeapp.com/api/' if subdomain else self.root_base_url
        url = f'{base_url}{path}'
        
        # Set default timeout if not provided
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 60
        
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            # Try to parse error details
            try:
                error_data = e.response.json()
                errors = error_data.get('errors', [])
                if errors:
                    error_code = errors[0].get('code', '')
                    error_title = errors[0].get('title', str(e))
                    
                    # Handle specific error cases
                    if error_code in ('taken', 'unique_violation'):
                        raise BridgeSubaccountExists(f"Subaccount already exists: {error_title}") from e
                    elif error_code == 'not_unique':
                        raise BridgeUserExists(f"User already exists: {error_title}") from e
                    
                    raise BridgeAPIError(f"Bridge API error: {error_title}") from e
            except (json.JSONDecodeError, KeyError):
                pass
            
            raise BridgeAPIError(f"Bridge API error: {str(e)}") from e
        except requests.exceptions.RequestException as e:
            raise BridgeAPIError(f"Request failed: {str(e)}") from e
    
    def get_subaccount(self, subdomain):
        """
        Get subaccount information.
        
        Args:
            subdomain: Subaccount subdomain
        
        Returns:
            Subaccount data dict or None if not found
        """
        try:
            # Try to access the subaccount directly first (more efficient)
            # If it exists, we can try to get info from it
            # Otherwise, list subaccounts with search
            response = self._request('get', 'admin/sub_accounts', params={
                'limit': 100,
                'search': subdomain  # Try to search for it
            }, timeout=30)
            
            for subaccount in response.get('sub_accounts', []):
                if subaccount.get('subdomain') == subdomain:
                    return subaccount
            
            return None
        except BridgeAPIError:
            return None
    
    def create_subaccount(self, subdomain, name):
        """
        Create a new subaccount in Bridge.
        
        Args:
            subdomain: Subaccount subdomain (e.g., 'companyname-safetynow')
            name: Subaccount display name
        
        Returns:
            Created subaccount data dict
        
        Raises:
            BridgeSubaccountExists: If subaccount already exists
            BridgeAPIError: For other API errors
        """
        try:
            response = self._request(
                'post',
                'admin/sub_accounts',
                json={'sub_account': {'subdomain': subdomain, 'name': name}}
            )
            return response.get('sub_accounts', [{}])[0]
        except BridgeSubaccountExists:
            # If it exists, return the existing one
            existing = self.get_subaccount(subdomain)
            if existing:
                return existing
            raise
    
    def get_user(self, subdomain, unique_id):
        """
        Get user by unique identifier (uid or email).
        
        Args:
            subdomain: Subaccount subdomain
            unique_id: User unique identifier (uid or email)
        
        Returns:
            User data dict or None if not found
        """
        try:
            # Search for user by uid or email
            response = self._request('get', 'author/users', subdomain=subdomain, params={
                'search': unique_id,
                'limit': 100
            })
            
            for user in response.get('users', []):
                if user.get('uid', '').lower() == unique_id.lower() or \
                   user.get('email', '').lower() == unique_id.lower():
                    return user
            
            return None
        except BridgeAPIError:
            return None
    
    def create_user(self, subdomain, uid, email, first_name, last_name):
        """
        Create a new user in Bridge subaccount.
        
        Args:
            subdomain: Subaccount subdomain
            uid: User unique identifier (must match WordPress unique_id)
            email: User email address
            first_name: User first name
            last_name: User last name
        
        Returns:
            Created user data dict
        
        Raises:
            BridgeUserExists: If user already exists
            BridgeAPIError: For other API errors
        """
        try:
            response = self._request(
                'post',
                'admin/users',
                subdomain=subdomain,
                json={
                    'users': [{
                        'uid': uid,
                        'email': email,
                        'first_name': first_name,
                        'last_name': last_name,
                        'full_name': f'{first_name} {last_name}',
                        'sortable_name': f'{last_name}, {first_name}',
                    }]
                }
            )
            return response.get('users', [{}])[0]
        except BridgeUserExists:
            # If user exists, try to update it
            existing_user = self.get_user(subdomain, uid)
            if existing_user:
                return self.update_user(subdomain, existing_user['id'], email, first_name, last_name)
            raise
    
    def update_user(self, subdomain, user_id, email=None, first_name=None, last_name=None):
        """
        Update an existing user in Bridge.
        
        Args:
            subdomain: Subaccount subdomain
            user_id: Bridge user ID
            email: User email (optional)
            first_name: User first name (optional)
            last_name: User last name (optional)
        
        Returns:
            Updated user data dict
        """
        user_data = {}
        if email:
            user_data['email'] = email
        if first_name:
            user_data['first_name'] = first_name
        if last_name:
            user_data['last_name'] = last_name
        
        if first_name and last_name:
            user_data['full_name'] = f'{first_name} {last_name}'
            user_data['sortable_name'] = f'{last_name}, {first_name}'
        
        response = self._request(
            'patch',
            f'author/users/{user_id}',
            subdomain=subdomain,
            json={'user': user_data}
        )
        return response.get('users', [{}])[0]
    
    def list_subaccounts(self, limit=100):
        """
        List all subaccounts under the root account.
        
        Args:
            limit: Maximum number of subaccounts to return
        
        Returns:
            List of subaccount data dicts
        """
        response = self._request('get', 'admin/sub_accounts', params={'limit': limit})
        return response.get('sub_accounts', [])
    
    def configure_sso(self, subdomain, django_base_url, client_id, client_secret, login_attribute='email'):
        """
        Configure SSO/OAuth for a subaccount.
        
        Args:
            subdomain: Subaccount subdomain (e.g., 'ohsi-adrianov-safetynow')
            django_base_url: Base URL of Django app (e.g., 'https://yourdomain.com')
            client_id: OAuth client ID (required by Bridge)
            client_secret: OAuth client secret (required by Bridge)
            login_attribute: Login attribute ('email' or 'uid')
        
        Raises:
            BridgeAPIError: If SSO configuration fails
        """
        import logging
        from urllib.parse import urlparse, urlunparse
        logger = logging.getLogger(__name__)
        
        # Ensure django_base_url uses HTTPS and doesn't have trailing slash
        django_base_url = django_base_url.rstrip('/')
        parsed = urlparse(django_base_url)
        if parsed.scheme != 'https':
            parsed = parsed._replace(scheme='https')
            django_base_url = urlunparse(parsed)
        
        auth_config = {
            "provider": "OAuth2",
            "subprovider": "oauth2",
            "authorize_url": f"{django_base_url}/openid/authorize/",
            "token_url": f"{django_base_url}/openid/token/",
            "profile_url": f"{django_base_url}/openid/userinfo/",
            "scope": "openid profile email",
            "login_attribute": login_attribute,
            "token_as_header": True,
            "request_body_auth": False,
            "client_id": client_id,
            "client_secret": client_secret
        }
        
        logger.info(f"Configuring SSO for subaccount: {subdomain}")
        logger.info(f"Django base URL: {django_base_url}")
        logger.info(f"Client ID: {client_id}")
        logger.info(f"Login attribute: {login_attribute}")
        # Don't log client_secret for security
        logger.info(f"Auth config (without secret): {json.dumps({k: v for k, v in auth_config.items() if k != 'client_secret'}, indent=2)}")
        
        try:
            # Make request directly to the subaccount's API
            # The subdomain parameter tells _request to use the subaccount's base URL
            response = self._request(
                'patch',
                'config/sub_account/auth',
                subdomain=subdomain,
                json={"auth": auth_config}
            )
            logger.info(f"✓ SSO configuration successful for {subdomain}")
            logger.debug(f"Response: {json.dumps(response, indent=2) if response else 'No response body'}")
            
            # Verify SSO was actually configured by fetching it back
            try:
                verify_response = self._request(
                    'get',
                    'config/sub_account/auth',
                    subdomain=subdomain
                )
                logger.info(f"✓ Verified SSO config: {json.dumps(verify_response.get('auth', {}), indent=2)}")
            except Exception as verify_error:
                logger.warning(f"Could not verify SSO config: {str(verify_error)}")
            
            return response
        except BridgeAPIError as e:
            logger.error(f"✗ Failed to configure SSO for subaccount {subdomain}: {str(e)}")
            logger.error(f"Error details: {type(e).__name__}")
            # Try to get more details from the exception
            if hasattr(e, 'response'):
                logger.error(f"Response status: {e.response.status_code if hasattr(e.response, 'status_code') else 'N/A'}")
                try:
                    if hasattr(e.response, 'text'):
                        logger.error(f"Response body: {e.response.text}")
                except:
                    pass
            raise

