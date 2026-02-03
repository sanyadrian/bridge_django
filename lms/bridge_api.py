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
            
            # Handle empty responses (204 No Content)
            if response.status_code == 204 or not response.content:
                return {}
            
            # Try to parse JSON, handle empty/invalid JSON gracefully
            try:
                return response.json()
            except json.JSONDecodeError:
                # If response is not JSON, return empty dict and log warning
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Bridge API returned non-JSON response (status {response.status_code}): {response.text[:200]}")
                return {}
        except requests.exceptions.HTTPError as e:
            # Try to parse error details
            import logging
            logger = logging.getLogger(__name__)
            
            # Log the full error response for debugging
            try:
                error_text = e.response.text
                logger.error(f"Bridge API error response (status {e.response.status_code}): {error_text[:500]}")
                
                error_data = e.response.json()
                errors = error_data.get('errors', [])
                if errors:
                    error_code = errors[0].get('code', '')
                    error_title = errors[0].get('title', str(e))
                    error_detail = errors[0].get('detail', '')
                    
                    # Log full error details
                    logger.error(f"Bridge API error - Code: {error_code}, Title: {error_title}, Detail: {error_detail}")
                    
                    # Handle specific error cases
                    if error_code in ('taken', 'unique_violation'):
                        raise BridgeSubaccountExists(f"Subaccount already exists: {error_title}") from e
                    elif error_code == 'not_unique':
                        raise BridgeUserExists(f"User already exists: {error_title}") from e
                    
                    raise BridgeAPIError(f"Bridge API error: {error_title} (Detail: {error_detail})") from e
            except (json.JSONDecodeError, KeyError, AttributeError) as parse_error:
                logger.error(f"Could not parse Bridge API error response: {str(parse_error)}")
                if hasattr(e, 'response') and hasattr(e.response, 'text'):
                    logger.error(f"Raw response text: {e.response.text[:500]}")
            
            raise BridgeAPIError(f"Bridge API error: {str(e)}") from e
        except requests.exceptions.RequestException as e:
            raise BridgeAPIError(f"Request failed: {str(e)}") from e
    
    def list_courses(self, limit=None, include_unpublished=False):
        """
        List all courses from the root Bridge account.
        
        Args:
            limit: Maximum number of courses to return (None = all courses)
            include_unpublished: Include unpublished/archived courses (default: False - only published)
        
        Returns:
            List of course data dicts
        """
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        courses = []
        url = None  # Will be set to first page URL
        params = {'limit': 100}  # Bridge API limit per page
        
        page_count = 0
        while True:
            page_count += 1
            try:
                # First page: use _request with path
                if url is None:
                    response = self._request('get', 'author/course_templates', params=params)
                else:
                    # Subsequent pages: use full URL directly with session
                    logger.debug(f"Fetching next page: {url}")
                    response_obj = self.session.get(url, timeout=60)
                    response_obj.raise_for_status()
                    response = response_obj.json()
                
                course_list = response.get('course_templates', [])
                if not course_list:
                    logger.info(f"No more courses on page {page_count}")
                    break
                
                # Filter unpublished if needed
                if not include_unpublished:
                    course_list = [c for c in course_list if c.get('is_published', False)]
                
                courses.extend(course_list)
                logger.info(f"Page {page_count}: Fetched {len(course_list)} courses (total so far: {len(courses)})")
                
                # Check limit
                if limit and len(courses) >= limit:
                    break
                
                # Check for next page
                meta = response.get('meta', {})
                next_url = meta.get('next')
                if not next_url:
                    logger.info(f"No more pages (meta: {json.dumps(meta, indent=2)})")
                    break
                
                # Next URL is usually a full URL from Bridge
                url = next_url
                params = {}  # Next URL includes all params
                
            except Exception as e:
                logger.error(f"Error fetching courses page {page_count}: {str(e)}", exc_info=True)
                break
        
        result = courses[:limit] if limit else courses
        logger.info(f"✓ Fetched {len(result)} courses from {page_count} page(s)")
        return result
    
    def list_programs(self, limit=None, include_unpublished=False):
        """
        List all programs from the root Bridge account.
        
        Args:
            limit: Maximum number of programs to return (None = all programs)
            include_unpublished: Include unpublished/archived programs (default: False - only published)
        
        Returns:
            List of program data dicts
        """
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        programs = []
        url = None  # Will be set to first page URL
        params = {'limit': 100}  # Bridge API limit per page
        
        page_count = 0
        while True:
            page_count += 1
            try:
                # First page: use _request with path
                if url is None:
                    response = self._request('get', 'author/programs', params=params)
                else:
                    # Subsequent pages: use full URL directly with session
                    logger.debug(f"Fetching next page: {url}")
                    response_obj = self.session.get(url, timeout=60)
                    response_obj.raise_for_status()
                    response = response_obj.json()
                
                program_list = response.get('programs', [])
                if not program_list:
                    logger.info(f"No more programs on page {page_count}")
                    break
                
                # Filter unpublished if needed
                if not include_unpublished:
                    program_list = [p for p in program_list if p.get('is_published', False)]
                
                programs.extend(program_list)
                logger.info(f"Page {page_count}: Fetched {len(program_list)} programs (total so far: {len(programs)})")
                
                # Check limit
                if limit and len(programs) >= limit:
                    break
                
                # Check for next page
                meta = response.get('meta', {})
                next_url = meta.get('next')
                if not next_url:
                    logger.info(f"No more pages (meta: {json.dumps(meta, indent=2)})")
                    break
                
                # Next URL is usually a full URL from Bridge
                url = next_url
                params = {}  # Next URL includes all params
                
            except Exception as e:
                logger.error(f"Error fetching programs page {page_count}: {str(e)}", exc_info=True)
                break
        
        result = programs[:limit] if limit else programs
        logger.info(f"✓ Fetched {len(result)} programs from {page_count} page(s)")
        return result
    
    def set_course_affiliation(self, course_id, subaccount_id, on=True):
        """
        Set course affiliation (share/revoke) for a subaccount.
        
        Args:
            course_id: Bridge course ID
            subaccount_id: Bridge subaccount ID
            on: True to share, False to revoke
        
        Raises:
            BridgeAPIError: If affiliation fails
        """
        self._request(
            'put',
            'author/affiliated_sub_accounts/share' if on else 'author/affiliated_sub_accounts/revoke',
            json={
                'item_type': 'CourseTemplate',
                'item_id': str(course_id),
                'domain_id': str(subaccount_id)
            }
        )
    
    def set_program_affiliation(self, program_id, subaccount_id, on=True):
        """
        Set program affiliation (share/revoke) for a subaccount.
        
        Args:
            program_id: Bridge program ID
            subaccount_id: Bridge subaccount ID
            on: True to share, False to revoke
        
        Raises:
            BridgeAPIError: If affiliation fails
        """
        self._request(
            'put',
            'author/affiliated_sub_accounts/share' if on else 'author/affiliated_sub_accounts/revoke',
            json={
                'item_type': 'Program',
                'item_id': str(program_id),
                'domain_id': str(subaccount_id)
            }
        )

    def set_affiliations_batch(self, affiliations, on=True):
        """
        Batch share/revoke course/program affiliations for a subaccount.

        This is MUCH faster than calling set_course_affiliation() 500+ times.

        Args:
            affiliations: list[dict] like:
                {"item_type": "CourseTemplate"|"Program", "item_id": "...", "domain_id": "..."}
            on: True to share, False to revoke
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not affiliations:
            return

        # Bridge endpoint supports batch updates
        endpoint = 'author/affiliated_sub_accounts/share_batch' if on else 'author/affiliated_sub_accounts/revoke_batch'
        action = 'sharing' if on else 'revoking'
        
        logger.info(f"Batch {action} {len(affiliations)} affiliations via {endpoint}")
        
        # Log first affiliation for debugging
        if affiliations:
            logger.debug(f"Sample affiliation: {affiliations[0]}")
        
        try:
            response = self._request(
                'put',
                endpoint,
                json={'affiliations': affiliations},
                timeout=120
            )
            logger.info(f"✓ Batch {action} completed successfully")
            return response
        except BridgeAPIError as e:
            logger.error(f"✗ Batch {action} failed: {str(e)}")
            logger.error(f"Request payload (first 3 affiliations): {affiliations[:3] if len(affiliations) >= 3 else affiliations}")
            raise
    
    def enroll_user_in_course(self, subdomain, user_id, course_id):
        """
        Enroll a user in a course.
        
        Note: This endpoint is called from the subaccount, not root account.
        
        Args:
            subdomain: Subaccount subdomain
            user_id: Bridge user ID (from subaccount)
            course_id: Bridge course template ID
            
        Raises:
            BridgeAPIError: If enrollment fails
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Endpoint: POST /api/author/course_templates/{course_id}/enrollments
        # Called from subaccount
        endpoint = f'author/course_templates/{course_id}/enrollments'
        
        logger.debug(f"Enrolling user {user_id} in course {course_id} (subaccount: {subdomain})")
        
        self._request(
            'post',
            endpoint,
            subdomain=subdomain,  # Call from subaccount
            json={
                'enrollments': [{
                    'user_id': int(user_id)  # Bridge expects integer
                }]
            }
        )
    
    def enroll_user_in_courses_batch(self, subdomain, user_id, course_ids):
        """
        Enroll a user in multiple courses.
        
        Note: This calls the course-specific enrollment endpoint for each course.
        The Bridge API endpoint enrolls multiple users in ONE course, so we
        need to call it once per course for our single user.
        
        Args:
            subdomain: Subaccount subdomain
            user_id: Bridge user ID (from subaccount)
            course_ids: List of Bridge course template IDs
            
        Returns:
            tuple: (enrolled_count, failed_count)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not course_ids:
            return 0, 0
        
        enrolled_count = 0
        failed_count = 0
        total_courses = len(course_ids)
        
        logger.info(f"Enrolling user {user_id} in {total_courses} courses (subaccount: {subdomain})...")
        
        for idx, course_id in enumerate(course_ids, 1):
            try:
                self.enroll_user_in_course(subdomain, user_id, course_id)
                enrolled_count += 1
                if idx % 25 == 0 or idx == total_courses:
                    logger.info(f"  Progress: {idx}/{total_courses} courses processed ({enrolled_count} enrolled, {failed_count} failed)...")
            except BridgeAPIError as e:
                failed_count += 1
                logger.warning(f"  Failed to enroll user {user_id} in course {course_id}: {str(e)}")
        
        logger.info(f"✓ Enrollment complete: {enrolled_count} enrolled, {failed_count} failed (out of {total_courses} courses)")
        return enrolled_count, failed_count
    
    def list_roles(self, subdomain):
        """
        List all available roles in a subaccount.
        
        Note: Bridge API may not expose a roles listing endpoint. This method
        tries multiple endpoints and returns empty list if none work.
        
        Args:
            subdomain: Subaccount subdomain (or None for root account)
            
        Returns:
            list: List of role dictionaries with 'id' and 'name' keys
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Try different endpoints
        endpoints_to_try = [
            'admin/roles',
            'author/roles',
            'roles',
        ]
        
        for endpoint in endpoints_to_try:
            try:
                logger.debug(f"Trying to list roles from endpoint: {endpoint} (subdomain: {subdomain})")
                response = self._request('get', endpoint, subdomain=subdomain)
                roles = response.get('roles', [])
                if roles:
                    logger.debug(f"Found {len(roles)} roles from {endpoint}")
                    return roles
            except BridgeAPIError as e:
                logger.debug(f"Endpoint {endpoint} failed: {str(e)}")
                continue
            except Exception as e:
                logger.debug(f"Endpoint {endpoint} error: {str(e)}")
                continue
        
        # If all endpoints failed, try root account
        if subdomain:
            try:
                logger.debug("Trying to list roles from root account")
                for endpoint in endpoints_to_try:
                    try:
                        response = self._request('get', endpoint, subdomain=None)
                        roles = response.get('roles', [])
                        if roles:
                            logger.debug(f"Found {len(roles)} roles from root account ({endpoint})")
                            return roles
                    except:
                        continue
            except Exception as e:
                logger.debug(f"Root account role listing failed: {str(e)}")
        
        logger.warning("Could not list roles from any endpoint - Bridge API may not expose this")
        return []
    
    def get_role_by_name(self, subdomain, role_name):
        """
        Get a role ID by role name.
        
        Args:
            subdomain: Subaccount subdomain
            role_name: Name of the role (e.g., "Sub Account Administrator")
            
        Returns:
            str: Role ID, or None if not found
        """
        import logging
        logger = logging.getLogger(__name__)
        
        roles = self.list_roles(subdomain)
        if not roles:
            # If we can't list roles, try root account
            roles = self.list_roles(None)
        
        for role in roles:
            if role.get('name') == role_name:
                role_id = role.get('id')
                logger.debug(f"Found role '{role_name}' with ID: {role_id}")
                return role_id
        
        logger.warning(f"Role '{role_name}' not found")
        return None
    
    def get_sub_account_admin_role_id(self):
        """
        Get the Sub Account Administrator role ID.
        
        This uses a known hardcoded role ID that is consistent across Bridge instances.
        If role listing works, it will try to find it by name first.
        
        Returns:
            str: Role ID for Sub Account Administrator
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Known role ID from previous implementations
        # This is the standard "Sub Account Administrator" role ID in Bridge
        SUB_ACCOUNT_ADMIN_ROLE_ID = "25fed615-b7e8-4190-af30-b7ade587d04b"
        
        return SUB_ACCOUNT_ADMIN_ROLE_ID
    
    def assign_user_roles(self, subdomain, user_id, role_ids):
        """
        Assign roles to a user in a subaccount.
        
        Args:
            subdomain: Subaccount subdomain
            user_id: Bridge user ID
            role_ids: List of role IDs to assign (can be single role ID or list)
            
        Raises:
            BridgeAPIError: If role assignment fails
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Ensure role_ids is a list
        if not isinstance(role_ids, list):
            role_ids = [role_ids]
        
        endpoint = f'admin/users/{user_id}/roles/batch'
        logger.debug(f"Assigning roles {role_ids} to user {user_id} in subaccount {subdomain}")
        
        self._request(
            'put',
            endpoint,
            subdomain=subdomain,
            json={'roles': role_ids}
        )
        
        logger.info(f"✓ Assigned {len(role_ids)} role(s) to user {user_id}")
    
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

