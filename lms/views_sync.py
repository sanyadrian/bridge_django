"""
Views for syncing users and companies to Bridge LMS.
"""
import json
import re
import hashlib
import hmac
import time
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator

from .models import OHSAccount, OHSAuth, Package
from .bridge_api import BridgeAPI, BridgeSubaccountExists, BridgeUserExists, BridgeAPIError

logger = logging.getLogger(__name__)


def generate_subaccount_domain(company_name, prefix='ohsi', root_subdomain='safetynow'):
    """
    Generate a Bridge subaccount subdomain from company name.
    Format: ohsi-{sanitized_company}-safetynow
    
    Args:
        company_name: Company name (e.g., "Adrianov Inc.")
        prefix: Prefix for subaccount (default: 'ohsi')
        root_subdomain: Root Bridge subdomain (default: 'safetynow')
    
    Returns:
        Subdomain string (e.g., "ohsi-adrianov-safetynow")
    """
    if not company_name:
        return None
    
    # Convert to lowercase and remove special characters
    domain = company_name.lower()
    # Replace spaces and special chars with nothing
    domain = re.sub(r'[^a-z0-9]+', '', domain)
    # Remove common suffixes
    domain = re.sub(r'\b(inc|llc|corp|corporation|ltd|limited|company|co)\b', '', domain)
    domain = domain.strip()
    
    # Ensure it's not empty
    if not domain:
        # Fallback: use hash of company name
        domain = hashlib.md5(company_name.encode()).hexdigest()[:12]
    
    # Bridge subdomains format: ohsi-companyname-safetynow
    return f"{prefix}-{domain}-{root_subdomain}"


@csrf_exempt
@require_http_methods(["POST"])
def sync_user_to_bridge(request):
    """
    API endpoint to sync WordPress user to Bridge LMS.
    Called when user's membership level changes from trial to paid.
    
    Expected POST data:
    {
        "email": "user@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "company_name": "ABC Company Inc.",
        "provision_id": "PROV-12345",  # Optional, used for Bridge subaccount mapping
        "timestamp": 1234567890,
        "signature": "hmac_sha256_signature"
    }
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get authentication credentials
        auth = OHSAuth.objects.filter(is_active=True).first()
        if not auth:
            return JsonResponse({'error': 'No active authentication configured'}, status=500)
        
        # Parse request data
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        
        # Verify signature
        signature = data.get('signature')
        if not signature:
            return JsonResponse({'error': 'Missing signature'}, status=400)
        
        # Create data string for verification (excluding signature)
        data_copy = data.copy()
        data_copy.pop('signature', None)
        data_string = urlencode(sorted(data_copy.items()), doseq=True)
        
        # DEBUG: Log signature verification details
        logger.info(f"=== SIGNATURE DEBUG ===")
        logger.info(f"Data string for verification: {data_string}")
        logger.info(f"Received signature: {signature}")
        
        # Verify signature
        expected_signature = hmac.new(
            auth.client_secret.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        logger.info(f"Expected signature: {expected_signature}")
        logger.info(f"Client secret used: {auth.client_secret[:8]}...")
        logger.info(f"=== END SIGNATURE DEBUG ===")
        
        if signature != expected_signature:
            return JsonResponse({'error': 'Invalid signature'}, status=403)
        
        # Check timestamp (within 5 minutes)
        timestamp = int(data.get('timestamp', 0))
        if abs(time.time() - timestamp) > 300:
            return JsonResponse({'error': 'Token expired'}, status=400)
        
        # Extract required fields
        email = data.get('email')
        first_name = data.get('first_name', '')
        last_name = data.get('last_name', '')
        company_name = data.get('company_name', '')
        provision_id = data.get('provision_id', '')
        prefix = data.get('prefix', 'ohsi')  # Default to 'ohsi' if not provided
        
        if not email:
            return JsonResponse({'error': 'Missing required field: email'}, status=400)
        
        # Initialize Bridge API
        try:
            bridge_api = BridgeAPI(root_subdomain='safetynow')
        except ValueError as e:
            return JsonResponse({'error': f'Bridge API configuration error: {str(e)}'}, status=500)
        
        # Determine subaccount subdomain
        # First, check if we already have a mapping in OHSAccount (by email)
        account = None
        try:
            account = OHSAccount.objects.get(user_email=email)
            bridge_subaccount_id = account.bridge_subaccount_id
        except OHSAccount.DoesNotExist:
            # No existing account - need to create subaccount
            if not company_name:
                return JsonResponse({
                    'error': 'Company name required for new subaccount creation'
                }, status=400)
            
            # Generate subaccount subdomain from company name with prefix
            bridge_subaccount_id = generate_subaccount_domain(company_name, prefix=prefix, root_subdomain='safetynow')
        
        # Check if subaccount exists in Bridge, create if not
        subaccount = None
        subaccount_created = False
        sso_needs_config = False
        try:
            subaccount = bridge_api.get_subaccount(bridge_subaccount_id)
            
            if not subaccount:
                # Subaccount doesn't exist - create it
                if not company_name:
                    return JsonResponse({
                        'error': 'Company name required for subaccount creation'
                    }, status=400)
                
                try:
                    # Create subaccount name with prefix: "{prefix} - {Company Name}"
                    subaccount_name = f"{prefix.upper()} - {company_name}"
                    subaccount = bridge_api.create_subaccount(
                        subdomain=bridge_subaccount_id,
                        name=subaccount_name
                    )
                    subaccount_created = True
                    sso_needs_config = True
                    logger.info(f"✓ New subaccount created: {bridge_subaccount_id}")
                except BridgeSubaccountExists:
                    # It was created between check and create - get it again
                    logger.info(f"Subaccount {bridge_subaccount_id} was created concurrently, fetching it...")
                    subaccount = bridge_api.get_subaccount(bridge_subaccount_id)
                    if subaccount:
                        # Subaccount exists now, check if SSO is configured
                        sso_needs_config = True
                except BridgeAPIError as e:
                    return JsonResponse({
                        'error': f'Failed to create Bridge subaccount: {str(e)}'
                    }, status=500)
            else:
                # Subaccount exists - check if SSO needs to be configured
                logger.info(f"Subaccount {bridge_subaccount_id} already exists")
                # Always try to configure SSO (in case it wasn't configured before)
                sso_needs_config = True
        except BridgeAPIError as e:
            return JsonResponse({
                'error': f'Failed to check Bridge subaccount: {str(e)}'
            }, status=500)
        
        # Configure SSO if needed (for new subaccounts or if not configured)
        if sso_needs_config and subaccount:
            logger.info(f"Configuring SSO for subaccount: {bridge_subaccount_id}")
            try:
                # Get Django base URL from settings or request
                django_base_url = getattr(settings, 'OHS_DJANGO_BASE_URL', None)
                if not django_base_url:
                    # Try to get from request
                    django_base_url = request.build_absolute_uri('/').rstrip('/')
                    # Remove the /api/sync-user-to-bridge/ part if present
                    django_base_url = django_base_url.split('/api/')[0]
                
                logger.info(f"Django base URL: {django_base_url}")
                logger.info(f"Client ID: {auth.client_id}")
                logger.info(f"Client Secret: {'*' * len(auth.client_secret) if auth.client_secret else 'NOT SET'}")
                
                # Use auth credentials from the top of the function
                if auth:
                    bridge_api.configure_sso(
                        subdomain=bridge_subaccount_id,
                        django_base_url=django_base_url,
                        client_id=auth.client_id,
                        client_secret=auth.client_secret,
                        login_attribute='email'
                    )
                    logger.info(f"✓ Successfully configured SSO for subaccount: {bridge_subaccount_id}")
                else:
                    logger.warning("No active auth found - SSO not configured")
            except BridgeAPIError as sso_error:
                logger.error(f"✗ Failed to configure SSO for {bridge_subaccount_id}: {str(sso_error)}")
                logger.warning("Continuing despite SSO configuration failure - can be configured manually")
                # Don't fail the whole process, but log the error
            except Exception as sso_error:
                logger.error(f"✗ Unexpected error configuring SSO for {bridge_subaccount_id}: {str(sso_error)}")
                logger.exception("Full traceback:")
                # Don't fail the whole process, but log the error
        
        # Create or update user in Bridge subaccount
        # Use email as uid since we don't have unique_id
        bridge_user = None
        user_created = False
        try:
            # Check if user exists
            existing_user = bridge_api.get_user(bridge_subaccount_id, email)
            
            if existing_user:
                # Update existing user
                bridge_user = bridge_api.update_user(
                    subdomain=bridge_subaccount_id,
                    user_id=existing_user['id'],
                    email=email,
                    first_name=first_name,
                    last_name=last_name
                )
            else:
                # Create new user
                try:
                    bridge_user = bridge_api.create_user(
                        subdomain=bridge_subaccount_id,
                        uid=email,  # Use email as uid
                        email=email,
                        first_name=first_name,
                        last_name=last_name
                    )
                    user_created = True
                    
                    # Assign "Sub Account Administrator" role to newly created user
                    if bridge_user and bridge_user.get('id'):
                        try:
                            logger.info(f"Assigning 'Sub Account Administrator' role to user {bridge_user.get('id')}...")
                            
                            # Try to find role by name first (if role listing works)
                            role_names_to_try = [
                                "Sub Account Administrator",
                                "Sub Account Admin",
                                "SubAccount Administrator",
                                "SubAccount Admin"
                            ]
                            
                            role_id = None
                            found_role_name = None
                            
                            for role_name in role_names_to_try:
                                role_id = bridge_api.get_role_by_name(bridge_subaccount_id, role_name)
                                if role_id:
                                    found_role_name = role_name
                                    break
                            
                            # If role listing doesn't work, use hardcoded role ID
                            if not role_id:
                                logger.info("  Role listing not available, using known Sub Account Administrator role ID")
                                role_id = bridge_api.get_sub_account_admin_role_id()
                                found_role_name = "Sub Account Administrator (by ID)"
                            
                            if role_id:
                                bridge_api.assign_user_roles(
                                    subdomain=bridge_subaccount_id,
                                    user_id=bridge_user.get('id'),
                                    role_ids=[role_id]
                                )
                                logger.info(f"✓ Successfully assigned '{found_role_name}' role to user")
                            else:
                                logger.warning(f"✗ Could not determine Sub Account Administrator role ID")
                                logger.warning(f"  Skipping role assignment - can be assigned manually")
                        except Exception as role_error:
                            logger.error(f"✗ Failed to assign role to user: {str(role_error)}")
                            logger.exception("Full traceback:")
                            # Don't fail the whole process; role can be assigned manually if needed
                except BridgeUserExists:
                    # User was created between check and create - get it
                    existing_user = bridge_api.get_user(bridge_subaccount_id, email)
                    if existing_user:
                        bridge_user = existing_user
        except BridgeAPIError as e:
            return JsonResponse({
                'error': f'Failed to create/update Bridge user: {str(e)}'
            }, status=500)
        
        # Create or update OHSAccount in Django (using email as unique_id)
        if account:
            # Update existing account
            account.user_email = email
            account.first_name = first_name
            account.last_name = last_name
            account.bridge_subaccount_id = bridge_subaccount_id
            if company_name:
                account.company_name = company_name
            if bridge_user:
                account.bridge_user_id = bridge_user.get('id')
            if subaccount:
                account.bridge_account_id = subaccount.get('id')
            account.save()
        else:
            # Create new account (use email as unique_id)
            account = OHSAccount.objects.create(
                unique_id=email,  # Use email as unique_id
                user_email=email,
                first_name=first_name,
                last_name=last_name,
                company_name=company_name,
                bridge_subaccount_id=bridge_subaccount_id,
                bridge_user_id=bridge_user.get('id') if bridge_user else None,
                bridge_account_id=subaccount.get('id') if subaccount else None,
                prefix=prefix if prefix in ['ohsi', 'hri', 'ilt'] else None,
            )

        # Auto-assign package courses and programs to subaccount based on prefix
        # ONLY for newly created subaccounts
        #
        # IMPORTANT: This runs AFTER Bridge user + OHSAccount are created, so even if package assignment
        # fails/times out, /auth/<email>/ will still work (no more "No OHSAccount matches..." errors).
        if subaccount_created and subaccount and subaccount.get('id'):
            try:
                subaccount_id = subaccount.get('id')
                subaccount_name = subaccount.get('name', '')

                # If prefix not provided, try to extract from subaccount name
                # Format: "OHSI - Company Name" or "HRI - Company Name" or "ILT - Company Name"
                if not prefix or prefix not in ['ohsi', 'hri', 'ilt']:
                    if ' - ' in subaccount_name:
                        extracted_prefix = subaccount_name.split(' - ')[0].lower()
                        if extracted_prefix in ['ohsi', 'hri', 'ilt']:
                            prefix = extracted_prefix
                            logger.info(f"Extracted prefix '{prefix}' from subaccount name: {subaccount_name}")
                    else:
                        # Try to extract from subdomain: "ohsi-company-safetynow"
                        subdomain_parts = bridge_subaccount_id.split('-')
                        if len(subdomain_parts) > 0 and subdomain_parts[0] in ['ohsi', 'hri', 'ilt']:
                            prefix = subdomain_parts[0]
                            logger.info(f"Extracted prefix '{prefix}' from subdomain: {bridge_subaccount_id}")

                if not prefix or prefix not in ['ohsi', 'hri', 'ilt']:
                    logger.warning(f"Could not determine prefix for subaccount {bridge_subaccount_id} - skipping package assignment")
                    logger.warning(f"Subaccount name: {subaccount_name}, Subdomain: {bridge_subaccount_id}")
                else:
                    logger.info(f"Assigning package to NEWLY CREATED subaccount {bridge_subaccount_id} (ID: {subaccount_id}) based on prefix: {prefix}")

                    # Find package by prefix
                    package = Package.objects.filter(prefix=prefix, active=True).order_by('id').first()
                    if not package:
                        logger.warning(f"No active package found for prefix '{prefix}' - skipping package assignment")
                    else:
                        courses = list(package.courses.filter(active=True).values_list('bridge_id', flat=True))
                        programs = list(package.programs.filter(active=True).values_list('bridge_id', flat=True))
                        logger.info(f"Found package: {package.name} with {len(courses)} courses and {len(programs)} programs")

                        def _chunks(items, size):
                            for i in range(0, len(items), size):
                                yield items[i:i + size]

                        # Bridge API limit: max 25 affiliations per batch
                        BATCH_SIZE = 25

                        # Batch share courses (fast)
                        if courses:
                            course_affiliations = [
                                {'item_type': 'CourseTemplate', 'item_id': str(cid), 'domain_id': str(subaccount_id)}
                                for cid in courses
                            ]
                            batch_num = 0
                            total_batches = (len(course_affiliations) + BATCH_SIZE - 1) // BATCH_SIZE
                            courses_assigned = 0
                            courses_failed = 0
                            
                            for batch in _chunks(course_affiliations, BATCH_SIZE):
                                batch_num += 1
                                logger.info(f"  Sharing batch {batch_num}/{total_batches} of courses ({len(batch)} courses)...")
                                try:
                                    bridge_api.set_affiliations_batch(batch, on=True)
                                    courses_assigned += len(batch)
                                except BridgeAPIError as batch_error:
                                    logger.warning(f"  Batch {batch_num} failed, trying individual assignments...")
                                    # Fallback to individual assignments if batch fails
                                    for affiliation in batch:
                                        try:
                                            bridge_api.set_course_affiliation(
                                                course_id=int(affiliation['item_id']),
                                                subaccount_id=int(affiliation['domain_id']),
                                                on=True
                                            )
                                            courses_assigned += 1
                                        except BridgeAPIError as individual_error:
                                            courses_failed += 1
                                            logger.warning(f"    Failed to assign course {affiliation['item_id']}: {str(individual_error)}")
                            
                            logger.info(f"✓ Shared {courses_assigned} courses to subaccount ({courses_failed} failed) in {total_batches} batch(es)")
                            logger.info(f"  Note: Course relevance ('Available in Library') can be set manually via Bridge UI if needed")
                        else:
                            logger.info("  No courses to share")

                        # Batch share programs (fast)
                        if programs:
                            program_affiliations = [
                                {'item_type': 'Program', 'item_id': str(pid), 'domain_id': str(subaccount_id)}
                                for pid in programs
                            ]
                            batch_num = 0
                            total_batches = (len(program_affiliations) + BATCH_SIZE - 1) // BATCH_SIZE
                            programs_assigned = 0
                            programs_failed = 0
                            
                            for batch in _chunks(program_affiliations, BATCH_SIZE):
                                batch_num += 1
                                logger.info(f"  Sharing batch {batch_num}/{total_batches} of programs ({len(batch)} programs)...")
                                try:
                                    bridge_api.set_affiliations_batch(batch, on=True)
                                    programs_assigned += len(batch)
                                except BridgeAPIError as batch_error:
                                    logger.warning(f"  Batch {batch_num} failed, trying individual assignments...")
                                    # Fallback to individual assignments if batch fails
                                    for affiliation in batch:
                                        try:
                                            bridge_api.set_program_affiliation(
                                                program_id=int(affiliation['item_id']),
                                                subaccount_id=int(affiliation['domain_id']),
                                                on=True
                                            )
                                            programs_assigned += 1
                                        except BridgeAPIError as individual_error:
                                            programs_failed += 1
                                            logger.warning(f"    Failed to assign program {affiliation['item_id']}: {str(individual_error)}")
                            
                            logger.info(f"✓ Shared {programs_assigned} programs to subaccount ({programs_failed} failed) in {total_batches} batch(es)")
                        else:
                            logger.info("  No programs to share")

                        logger.info("✓ Package assignment complete for NEW subaccount")
                        logger.info("  Note: Courses/programs are now affiliated (accessible) to the subaccount.")
                        logger.info("  Administrators can enroll learners from their Training tab.")
            except Exception as package_error:
                logger.error(f"✗ Failed to assign package to NEW subaccount {bridge_subaccount_id}: {str(package_error)}")
                logger.exception("Full traceback:")
                # Don't fail the whole process; package can be assigned manually if needed
        
        # Return success response
        return JsonResponse({
            'success': True,
            'message': 'User synced to Bridge successfully',
            'data': {
                'email': email,
                'bridge_subaccount_id': bridge_subaccount_id,
                'bridge_user_id': bridge_user.get('id') if bridge_user else None,
                'subaccount_created': subaccount_created,
                'user_created': user_created,
            }
        })
        
    except Exception as e:
        logger.error(f"Error in sync_user_to_bridge: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': f'Internal server error: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def create_bridge_subaccount(request):
    """
    API endpoint to create a new Bridge subaccount with automatic SSO configuration.
    Called when a user's membership becomes paid (non-trial).
    
    Expected POST data:
    {
        "email": "user@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "company_name": "ABC Company Inc.",
        "provision_id": "PROV-12345",  # Optional, used for Bridge subaccount mapping
        "timestamp": 1234567890,
        "signature": "hmac_sha256_signature"
    }
    """
    logger.info("=" * 80)
    logger.info("OHS Bridge: create_bridge_subaccount endpoint called")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request body length: {len(request.body)} bytes")
    
    try:
        # Get authentication credentials
        logger.info("Step 1: Getting authentication credentials...")
        auth = OHSAuth.objects.filter(is_active=True).first()
        if not auth:
            logger.error("✗ No active authentication configured")
            return JsonResponse({'error': 'No active authentication configured'}, status=500)
        logger.info(f"✓ Found active auth: client_id={auth.client_id}")
        
        # Parse request data
        logger.info("Step 2: Parsing request data...")
        try:
            data = json.loads(request.body)
            logger.info(f"✓ Parsed data keys: {list(data.keys())}")
            # Log data without signature for security
            data_for_log = {k: v for k, v in data.items() if k != 'signature'}
            logger.info(f"Data (without signature): {json.dumps(data_for_log, indent=2)}")
        except json.JSONDecodeError as e:
            logger.error(f"✗ Invalid JSON: {str(e)}")
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        
        # Verify signature
        logger.info("Step 3: Verifying signature...")
        signature = data.get('signature')
        if not signature:
            logger.error("✗ Missing signature in request")
            return JsonResponse({'error': 'Missing signature'}, status=400)
        
        # Create data string for verification (excluding signature)
        data_copy = data.copy()
        data_copy.pop('signature', None)
        data_string = urlencode(sorted(data_copy.items()), doseq=True)
        logger.debug(f"Data string for signature: {data_string}")
        
        # Verify signature
        expected_signature = hmac.new(
            auth.client_secret.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        logger.debug(f"Received signature: {signature[:20]}...")
        logger.debug(f"Expected signature: {expected_signature[:20]}...")
        
        if signature != expected_signature:
            logger.error("✗ Signature verification FAILED")
            return JsonResponse({'error': 'Invalid signature'}, status=403)
        logger.info("✓ Signature verification PASSED")
        
        # Check timestamp (within 5 minutes)
        logger.info("Step 4: Checking timestamp...")
        timestamp = int(data.get('timestamp', 0))
        time_diff = abs(time.time() - timestamp)
        logger.info(f"Timestamp: {timestamp}, Current time: {int(time.time())}, Difference: {time_diff}s")
        if time_diff > 300:
            logger.error(f"✗ Token expired: {time_diff}s > 300s")
            return JsonResponse({'error': 'Token expired'}, status=400)
        logger.info("✓ Timestamp check PASSED")
        
        # Extract required fields
        logger.info("Step 5: Extracting required fields...")
        email = data.get('email')
        first_name = data.get('first_name', '')
        last_name = data.get('last_name', '')
        company_name = data.get('company_name', '')
        provision_id = data.get('provision_id', '')
        prefix = data.get('prefix', 'ohsi')  # Default to 'ohsi' if not provided
        
        logger.info(f"Email: {email}")
        logger.info(f"Name: {first_name} {last_name}")
        logger.info(f"Company: {company_name}")
        logger.info(f"Prefix: {prefix}")
        logger.info(f"Provision ID: {provision_id if provision_id else '(not provided)'}")
        
        if not email or not company_name:
            logger.error(f"✗ Missing required fields - email: {bool(email)}, company_name: {bool(company_name)}")
            return JsonResponse({
                'error': 'Missing required fields: email, company_name'
            }, status=400)
        
        # Initialize Bridge API
        logger.info("Step 6: Initializing Bridge API...")
        try:
            bridge_api = BridgeAPI(root_subdomain='safetynow')
            logger.info("✓ Bridge API initialized successfully")
        except ValueError as e:
            logger.error(f"✗ Bridge API configuration error: {str(e)}")
            return JsonResponse({'error': f'Bridge API configuration error: {str(e)}'}, status=500)
        
        # Generate base subaccount domain: {prefix}-{company}-safetynow
        logger.info("Step 7: Generating subaccount domain...")
        base_subdomain = generate_subaccount_domain(company_name, prefix=prefix, root_subdomain='safetynow')
        logger.info(f"Generated base subdomain: {base_subdomain}")
        
        if not base_subdomain:
            logger.error("✗ Failed to generate subaccount domain from company name")
            return JsonResponse({'error': 'Failed to generate subaccount domain from company name'}, status=400)
        
        # Try to create subaccount, handle duplicates by adding -1, -2, etc.
        logger.info("Step 8: Creating Bridge subaccount...")
        subaccount = None
        subaccount_subdomain = base_subdomain
        attempt = 0
        max_attempts = 10
        
        while attempt < max_attempts:
            try:
                logger.info(f"Attempt {attempt + 1}/{max_attempts}: Trying to create subaccount: {subaccount_subdomain}")
                # Create subaccount name with prefix: "{prefix} - {Company Name}"
                # Example: "ohsi - TestAdrianov" or "hri - TestAdrianov"
                subaccount_name = f"{prefix.upper()} - {company_name}"
                logger.info(f"Subaccount name: {subaccount_name}")
                
                subaccount = bridge_api.create_subaccount(
                    subdomain=subaccount_subdomain,
                    name=subaccount_name
                )
                logger.info(f"✓ Successfully created Bridge subaccount: {subaccount_subdomain}")
                logger.info(f"Subaccount ID: {subaccount.get('id') if subaccount else 'N/A'}")
                break
            except BridgeSubaccountExists:
                # Subaccount exists, try with number suffix
                attempt += 1
                logger.warning(f"Subaccount {subaccount_subdomain} already exists")
                if attempt >= max_attempts:
                    logger.error(f"✗ Failed after {max_attempts} attempts - too many duplicates")
                    return JsonResponse({
                        'error': f'Failed to create subaccount: too many duplicates of {base_subdomain}'
                    }, status=409)
                
                # Try with -1, -2, etc.
                # Remove -safetynow, add number, add -safetynow back
                base_without_suffix = base_subdomain.replace('-safetynow', '')
                subaccount_subdomain = f"{base_without_suffix}-{attempt}-safetynow"
                logger.info(f"Trying with suffix -{attempt}: {subaccount_subdomain}")
            except BridgeAPIError as e:
                logger.error(f"✗ Bridge API error creating subaccount: {str(e)}")
                return JsonResponse({
                    'error': f'Failed to create Bridge subaccount: {str(e)}'
                }, status=500)
        
        if not subaccount:
            logger.error("✗ Failed to create subaccount after all attempts")
            return JsonResponse({'error': 'Failed to create subaccount after multiple attempts'}, status=500)
        
        # Configure SSO automatically
        logger.info("Step 9: Configuring SSO for subaccount...")
        django_base_url = getattr(settings, 'OHS_DJANGO_BASE_URL', None)
        if not django_base_url:
            # Try to get from request
            django_base_url = request.build_absolute_uri('/').rstrip('/')
            # Remove the /api/create-bridge-subaccount/ part if present
            django_base_url = django_base_url.split('/api/')[0]
        
        logger.info(f"Django base URL: {django_base_url}")
        logger.info(f"Client ID: {auth.client_id}")
        logger.info(f"Client Secret: {'*' * len(auth.client_secret) if auth.client_secret else 'NOT SET'}")
        
        try:
            bridge_api.configure_sso(
                subdomain=subaccount_subdomain,
                django_base_url=django_base_url,
                client_id=auth.client_id,
                client_secret=auth.client_secret,
                login_attribute='email'
            )
            logger.info(f"✓ Successfully configured SSO for subaccount: {subaccount_subdomain}")
        except BridgeAPIError as e:
            logger.error(f"✗ Failed to configure SSO for {subaccount_subdomain}: {str(e)}")
            logger.warning("Continuing despite SSO configuration failure - can be configured manually")
            # Don't fail the whole process, but log the error
            # SSO can be configured manually if needed
        
        # Create or update user in the subaccount
        # Use email as uid since we don't have unique_id
        logger.info("Step 10: Creating/updating user in Bridge subaccount...")
        bridge_user = None
        try:
            logger.info(f"Attempting to create user: {email} in subaccount: {subaccount_subdomain}")
            bridge_user = bridge_api.create_user(
                subdomain=subaccount_subdomain,
                uid=email,  # Use email as uid
                email=email,
                first_name=first_name,
                last_name=last_name
            )
            logger.info(f"✓ Successfully created user {email} in subaccount {subaccount_subdomain}")
            logger.info(f"Bridge user ID: {bridge_user.get('id') if bridge_user else 'N/A'}")
        except BridgeUserExists:
            # User already exists, try to update
            logger.info(f"User {email} already exists, attempting to update...")
            try:
                existing_user = bridge_api.get_user(subaccount_subdomain, email)
                if existing_user:
                    bridge_user = bridge_api.update_user(
                        subdomain=subaccount_subdomain,
                        user_id=existing_user['id'],
                        email=email,
                        first_name=first_name,
                        last_name=last_name
                    )
                    logger.info(f"✓ Successfully updated existing user {email}")
                else:
                    logger.warning(f"User {email} marked as exists but couldn't retrieve it")
            except BridgeAPIError as e:
                logger.error(f"✗ Failed to update user {email}: {str(e)}")
        except BridgeAPIError as e:
            logger.error(f"✗ Failed to create user {email} in subaccount: {str(e)}")
            logger.warning("Continuing despite user creation failure - user can be created later")
            # Don't fail the whole process, user can be created later
        
        # Store the full subdomain for Bridge API calls
        # subaccount_subdomain is like "ohsi-adrianov-safetynow" - this is what Bridge expects
        logger.info("Step 11: Preparing subaccount ID for storage...")
        logger.info(f"Full subaccount subdomain: {subaccount_subdomain}")
        
        # Create or update OHSAccount record
        logger.info("Step 12: Creating/updating OHSAccount record...")
        account, created = OHSAccount.objects.get_or_create(
            unique_id=email,  # Use email as unique_id since we don't have separate unique_id
            defaults={
                'user_email': email,
                'first_name': first_name,
                'last_name': last_name,
                'bridge_subaccount_id': subaccount_subdomain,  # Store FULL subdomain
                'company_name': company_name,
                'is_active': True
            }
        )
        
        if created:
            logger.info(f"✓ Created new OHSAccount record for {email}")
        else:
            logger.info(f"Updating existing OHSAccount record for {email}")
            # Update existing account
            account.user_email = email
            account.first_name = first_name
            account.last_name = last_name
            account.bridge_subaccount_id = subaccount_subdomain  # Store FULL subdomain
            account.company_name = company_name
            account.is_active = True
            if bridge_user:
                account.bridge_user_id = bridge_user.get('id')
            if subaccount:
                account.bridge_account_id = subaccount.get('id')
            account.save()
            logger.info(f"✓ Updated OHSAccount record")
        
        logger.info("=" * 80)
        logger.info(f"SUCCESS: Subaccount creation completed for {email}")
        logger.info(f"  - Subaccount: {subaccount_subdomain}")
        logger.info(f"  - Full URL: https://{subaccount_subdomain}.bridgeapp.com")
        logger.info("=" * 80)
        
        return JsonResponse({
            'success': True,
            'subaccount_id': subaccount_subdomain,  # Full subdomain for Bridge API
            'subaccount_subdomain': subaccount_subdomain,
            'full_url': f'https://{subaccount_subdomain}.bridgeapp.com',
            'message': f'Subaccount {subaccount_subdomain} created and SSO configured'
        })
        
    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"ERROR in create_bridge_subaccount: {str(e)}")
        logger.error(f"Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        logger.error("=" * 80)
        return JsonResponse({
            'error': f'Internal server error: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def import_users_from_plugin(request):
    """
    API endpoint to import existing users from WordPress plugin to Django.
    This syncs users that existed before the Django app was created.
    
    Expected POST data:
    {
        "users": [
            {
                "unique_id": "2019513-AIR-G-48",
                "email": "user@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "unique_url": "https://ohsiaircanada-safetynow.bridgeapp.com",
                "prefix": "ohsi",  # Optional, will be extracted from unique_url if not provided
                "company_name": "Air Canada"  # Optional
            },
            ...
        ]
    }
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Parse request data
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        
        users_data = data.get('users', [])
        if not users_data:
            return JsonResponse({'error': 'No users provided'}, status=400)
        
        if not isinstance(users_data, list):
            return JsonResponse({'error': 'users must be a list'}, status=400)
        
        logger.info(f"Importing {len(users_data)} users from plugin...")
        
        results = {
            'created': [],
            'updated': [],
            'failed': []
        }
        
        for user_data in users_data:
            try:
                unique_id = user_data.get('unique_id')
                if not unique_id:
                    results['failed'].append({
                        'data': user_data,
                        'error': 'Missing unique_id'
                    })
                    continue
                
                # Normalize unique_id: replace spaces with + (for consistency)
                # WordPress might have "2019513-AIR -G-48" but we need "2019513-AIR+-G-48"
                unique_id = unique_id.replace(' ', '+')
                
                email = user_data.get('email', '')
                first_name = user_data.get('first_name', '')
                last_name = user_data.get('last_name', '')
                unique_url = user_data.get('unique_url', '')
                prefix = user_data.get('prefix', '')
                company_name = user_data.get('company_name', '')
                
                # Extract prefix from unique_url if not provided
                if not prefix and unique_url:
                    try:
                        from urllib.parse import urlparse
                        parsed_url = urlparse(unique_url)
                        subdomain = parsed_url.netloc.split('.')[0]
                        # Extract prefix from subdomain (e.g., "ohsiaircanada-safetynow" -> "ohsi")
                        if subdomain.startswith('ohsi'):
                            prefix = 'ohsi'
                        elif subdomain.startswith('hri'):
                            prefix = 'hri'
                        elif subdomain.startswith('ilt'):
                            prefix = 'ilt'
                    except:
                        pass
                
                # Extract bridge_subaccount_id from unique_url if not provided
                bridge_subaccount_id = user_data.get('bridge_subaccount_id', '')
                if not bridge_subaccount_id and unique_url:
                    try:
                        from urllib.parse import urlparse
                        parsed_url = urlparse(unique_url)
                        bridge_subaccount_id = parsed_url.netloc.split('.')[0]
                    except:
                        pass
                
                # Create or update account
                account, created = OHSAccount.objects.update_or_create(
                    unique_id=unique_id,
                    defaults={
                        'user_email': email,
                        'first_name': first_name,
                        'last_name': last_name,
                        'unique_url': unique_url,
                        'prefix': prefix if prefix in ['ohsi', 'hri', 'ilt'] else None,
                        'bridge_subaccount_id': bridge_subaccount_id,
                        'company_name': company_name,
                        'is_active': True
                    }
                )
                
                if created:
                    results['created'].append({
                        'unique_id': unique_id,
                        'email': email
                    })
                    logger.info(f"✓ Created account: {unique_id} ({email})")
                else:
                    results['updated'].append({
                        'unique_id': unique_id,
                        'email': email
                    })
                    logger.info(f"✓ Updated account: {unique_id} ({email})")
                    
            except Exception as e:
                results['failed'].append({
                    'data': user_data,
                    'error': str(e)
                })
                logger.error(f"✗ Failed to import user {user_data.get('unique_id', 'unknown')}: {str(e)}")
        
        return JsonResponse({
            'success': True,
            'message': f'User import completed',
            'summary': {
                'total': len(users_data),
                'created': len(results['created']),
                'updated': len(results['updated']),
                'failed': len(results['failed'])
            },
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error in import_users_from_plugin: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': f'Internal server error: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def sync_existing_user_sso(request):
    """
    API endpoint to sync SSO for an existing user.
    For existing users, we only configure SSO - no subaccount creation or package assignment.
    
    Expected POST data:
    {
        "account_id": 123,  # OHSAccount ID
        OR
        "unique_id": "2019513-AIR-G-48",  # OHSAccount unique_id
        OR
        "email": "user@example.com",  # User email
    }
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Get authentication credentials
        auth = OHSAuth.objects.filter(is_active=True).first()
        if not auth:
            return JsonResponse({'error': 'No active authentication configured'}, status=500)
        
        # Parse request data
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        
        # Find the account
        account = None
        if 'account_id' in data:
            try:
                account = OHSAccount.objects.get(id=int(data['account_id']))
            except (OHSAccount.DoesNotExist, ValueError):
                return JsonResponse({'error': 'Account not found'}, status=404)
        elif 'unique_id' in data:
            try:
                account = OHSAccount.objects.get(unique_id=data['unique_id'])
            except OHSAccount.DoesNotExist:
                return JsonResponse({'error': 'Account not found'}, status=404)
        elif 'email' in data:
            try:
                account = OHSAccount.objects.get(user_email=data['email'])
            except (OHSAccount.DoesNotExist, OHSAccount.MultipleObjectsReturned):
                return JsonResponse({'error': 'Account not found or multiple accounts found'}, status=404)
        else:
            return JsonResponse({'error': 'Must provide account_id, unique_id, or email'}, status=400)
        
        if not account:
            return JsonResponse({'error': 'Account not found'}, status=404)
        
        # Check if account has unique_url
        if not account.unique_url:
            return JsonResponse({
                'error': 'Account does not have unique_url field set. Cannot determine subaccount.',
                'account_id': account.id,
                'unique_id': account.unique_id
            }, status=400)
        
        # Extract subdomain from unique_url
        # Format: https://ohsiaircanada-safetynow.bridgeapp.com
        # We need: ohsiaircanada-safetynow
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(account.unique_url)
            subdomain = parsed_url.netloc.split('.')[0]  # Get first part before .bridgeapp.com
            if not subdomain:
                raise ValueError("Could not extract subdomain from URL")
        except Exception as e:
            logger.error(f"Failed to extract subdomain from unique_url '{account.unique_url}': {str(e)}")
            return JsonResponse({
                'error': f'Invalid unique_url format: {account.unique_url}',
                'account_id': account.id
            }, status=400)
        
        logger.info(f"Syncing SSO for existing user: {account.user_email} (subdomain: {subdomain})")
        
        # Initialize Bridge API
        bridge_api = BridgeAPI()
        
        # Configure SSO
        try:
            # Get Django base URL from request
            django_base_url = request.build_absolute_uri('/').rstrip('/')
            # Remove the /api/sync-existing-user-sso/ part if present
            django_base_url = django_base_url.split('/api/')[0]
            
            logger.info(f"Configuring SSO for subaccount: {subdomain}")
            logger.info(f"Django base URL: {django_base_url}")
            logger.info(f"Client ID: {auth.client_id}")
            
            bridge_api.configure_sso(
                subdomain=subdomain,
                django_base_url=django_base_url,
                client_id=auth.client_id,
                client_secret=auth.client_secret,
                login_attribute='email'
            )
            logger.info(f"✓ Successfully configured SSO for subaccount: {subdomain}")
            
            # Update bridge_subaccount_id if not set
            if not account.bridge_subaccount_id:
                account.bridge_subaccount_id = subdomain
                account.save()
            
            return JsonResponse({
                'success': True,
                'message': 'SSO configured successfully for existing user',
                'data': {
                    'account_id': account.id,
                    'unique_id': account.unique_id,
                    'email': account.user_email,
                    'subdomain': subdomain,
                }
            })
            
        except BridgeAPIError as sso_error:
            logger.error(f"✗ Failed to configure SSO for {subdomain}: {str(sso_error)}")
            return JsonResponse({
                'error': f'Failed to configure SSO: {str(sso_error)}',
                'account_id': account.id,
                'subdomain': subdomain
            }, status=500)
        except Exception as sso_error:
            logger.error(f"✗ Unexpected error configuring SSO for {subdomain}: {str(sso_error)}")
            logger.exception("Full traceback:")
            return JsonResponse({
                'error': f'Unexpected error: {str(sso_error)}',
                'account_id': account.id
            }, status=500)
        
    except Exception as e:
        logger.error(f"Error in sync_existing_user_sso: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': f'Internal server error: {str(e)}'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def sync_existing_users_batch(request):
    """
    API endpoint to sync SSO for multiple existing users in batch.
    
    Expected POST data:
    {
        "account_ids": [123, 456, 789],  # List of OHSAccount IDs
        OR
        "unique_ids": ["2019513-AIR-G-48", "2019514-AIR-G-49"],  # List of unique_ids
        OR
        "all": true,  # Sync all accounts with unique_url set
    }
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Get authentication credentials
        auth = OHSAuth.objects.filter(is_active=True).first()
        if not auth:
            return JsonResponse({'error': 'No active authentication configured'}, status=500)
        
        # Parse request data
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        
        # Get accounts to sync
        accounts = []
        if data.get('all'):
            # Get all accounts with unique_url set
            accounts = list(OHSAccount.objects.filter(unique_url__isnull=False).exclude(unique_url=''))
            logger.info(f"Syncing SSO for all {len(accounts)} accounts with unique_url")
        elif 'account_ids' in data:
            account_ids = data['account_ids']
            if not isinstance(account_ids, list):
                return JsonResponse({'error': 'account_ids must be a list'}, status=400)
            accounts = list(OHSAccount.objects.filter(id__in=account_ids))
            logger.info(f"Syncing SSO for {len(accounts)} accounts (requested {len(account_ids)})")
        elif 'unique_ids' in data:
            unique_ids = data['unique_ids']
            if not isinstance(unique_ids, list):
                return JsonResponse({'error': 'unique_ids must be a list'}, status=400)
            accounts = list(OHSAccount.objects.filter(unique_id__in=unique_ids))
            logger.info(f"Syncing SSO for {len(accounts)} accounts (requested {len(unique_ids)})")
        else:
            return JsonResponse({'error': 'Must provide account_ids, unique_ids, or all=true'}, status=400)
        
        if not accounts:
            return JsonResponse({'error': 'No accounts found to sync'}, status=404)
        
        # Get Django base URL from request
        django_base_url = request.build_absolute_uri('/').rstrip('/')
        django_base_url = django_base_url.split('/api/')[0]
        
        # Initialize Bridge API
        bridge_api = BridgeAPI()
        
        results = {
            'success': [],
            'failed': [],
            'skipped': []
        }
        
        for account in accounts:
            try:
                # Check if account has unique_url
                if not account.unique_url:
                    results['skipped'].append({
                        'account_id': account.id,
                        'unique_id': account.unique_id,
                        'email': account.user_email,
                        'reason': 'No unique_url set'
                    })
                    continue
                
                # Extract subdomain from unique_url
                try:
                    from urllib.parse import urlparse
                    parsed_url = urlparse(account.unique_url)
                    subdomain = parsed_url.netloc.split('.')[0]
                    if not subdomain:
                        raise ValueError("Could not extract subdomain")
                    
                    # Extract and update prefix if not set
                    if not account.prefix:
                        if subdomain.startswith('ohsi'):
                            account.prefix = 'ohsi'
                        elif subdomain.startswith('hri'):
                            account.prefix = 'hri'
                        elif subdomain.startswith('ilt'):
                            account.prefix = 'ilt'
                        if account.prefix:
                            account.save()
                except Exception as e:
                    results['failed'].append({
                        'account_id': account.id,
                        'unique_id': account.unique_id,
                        'email': account.user_email,
                        'error': f'Invalid unique_url format: {account.unique_url}'
                    })
                    continue
                
                # Configure SSO
                try:
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
                    
                    results['success'].append({
                        'account_id': account.id,
                        'unique_id': account.unique_id,
                        'email': account.user_email,
                        'subdomain': subdomain
                    })
                    logger.info(f"✓ Configured SSO for {account.user_email} (subdomain: {subdomain})")
                    
                except BridgeAPIError as sso_error:
                    results['failed'].append({
                        'account_id': account.id,
                        'unique_id': account.unique_id,
                        'email': account.user_email,
                        'error': str(sso_error)
                    })
                    logger.warning(f"✗ Failed to configure SSO for {account.user_email}: {str(sso_error)}")
                    
            except Exception as e:
                results['failed'].append({
                    'account_id': account.id,
                    'unique_id': account.unique_id,
                    'email': account.user_email,
                    'error': str(e)
                })
                logger.error(f"✗ Error processing account {account.id}: {str(e)}")
        
        return JsonResponse({
            'success': True,
            'message': f'Batch SSO sync completed',
            'summary': {
                'total': len(accounts),
                'success': len(results['success']),
                'failed': len(results['failed']),
                'skipped': len(results['skipped'])
            },
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error in sync_existing_users_batch: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': f'Internal server error: {str(e)}'
        }, status=500)

