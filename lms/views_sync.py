"""
Views for syncing users and companies to Bridge LMS.
"""
import json
import re
import hashlib
import hmac
import time
from urllib.parse import urlencode

from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator

from .models import OHSAccount, OHSAuth
from .bridge_api import BridgeAPI, BridgeSubaccountExists, BridgeUserExists, BridgeAPIError


def generate_subaccount_domain(company_name, root_subdomain='safetynow'):
    """
    Generate a Bridge subaccount subdomain from company name.
    
    Args:
        company_name: Company name (e.g., "ABC Company Inc.")
        root_subdomain: Root Bridge subdomain (default: 'safetynow')
    
    Returns:
        Subdomain string (e.g., "abccompany-safetynow")
    """
    if not company_name:
        return None
    
    # Convert to lowercase and remove special characters
    domain = company_name.lower()
    # Replace spaces and special chars with nothing or dashes
    domain = re.sub(r'[^a-z0-9]+', '', domain)
    # Remove common suffixes
    domain = re.sub(r'\b(inc|llc|corp|corporation|ltd|limited|company|co)\b', '', domain)
    domain = domain.strip()
    
    # Ensure it's not empty and add root subdomain
    if not domain:
        # Fallback: use hash of company name
        domain = hashlib.md5(company_name.encode()).hexdigest()[:12]
    
    # Bridge subdomains format: companyname-safetynow
    return f"{domain}-{root_subdomain}"


@csrf_exempt
@require_http_methods(["POST"])
def sync_user_to_bridge(request):
    """
    API endpoint to sync WordPress user to Bridge LMS.
    Called when user's membership level changes from trial to paid.
    
    Expected POST data:
    {
        "unique_id": "2019513-AIR-G-48",
        "email": "user@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "company_name": "ABC Company Inc.",
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
        
        # Verify signature
        expected_signature = hmac.new(
            auth.client_secret.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        if signature != expected_signature:
            return JsonResponse({'error': 'Invalid signature'}, status=403)
        
        # Check timestamp (within 5 minutes)
        timestamp = int(data.get('timestamp', 0))
        if abs(time.time() - timestamp) > 300:
            return JsonResponse({'error': 'Token expired'}, status=400)
        
        # Extract required fields
        unique_id = data.get('unique_id')
        email = data.get('email')
        first_name = data.get('first_name', '')
        last_name = data.get('last_name', '')
        company_name = data.get('company_name', '')
        
        if not unique_id or not email:
            return JsonResponse({'error': 'Missing required fields: unique_id, email'}, status=400)
        
        # Initialize Bridge API
        try:
            bridge_api = BridgeAPI(root_subdomain='safetynow')
        except ValueError as e:
            return JsonResponse({'error': f'Bridge API configuration error: {str(e)}'}, status=500)
        
        # Determine subaccount subdomain
        # First, check if we already have a mapping in OHSAccount
        account = None
        try:
            account = OHSAccount.objects.get(unique_id=unique_id)
            bridge_subaccount_id = account.bridge_subaccount_id
        except OHSAccount.DoesNotExist:
            # No existing account - need to create subaccount
            if not company_name:
                return JsonResponse({
                    'error': 'Company name required for new subaccount creation'
                }, status=400)
            
            # Generate subaccount subdomain from company name
            bridge_subaccount_id = generate_subaccount_domain(company_name)
        
        # Check if subaccount exists in Bridge, create if not
        subaccount = None
        subaccount_created = False
        try:
            subaccount = bridge_api.get_subaccount(bridge_subaccount_id)
            
            if not subaccount:
                # Subaccount doesn't exist - create it
                if not company_name:
                    return JsonResponse({
                        'error': 'Company name required for subaccount creation'
                    }, status=400)
                
                try:
                    subaccount = bridge_api.create_subaccount(
                        subdomain=bridge_subaccount_id,
                        name=company_name
                    )
                    subaccount_created = True
                except BridgeSubaccountExists:
                    # It was created between check and create - get it again
                    subaccount = bridge_api.get_subaccount(bridge_subaccount_id)
                except BridgeAPIError as e:
                    return JsonResponse({
                        'error': f'Failed to create Bridge subaccount: {str(e)}'
                    }, status=500)
        except BridgeAPIError as e:
            return JsonResponse({
                'error': f'Failed to check Bridge subaccount: {str(e)}'
            }, status=500)
        
        # Create or update user in Bridge subaccount
        bridge_user = None
        user_created = False
        try:
            # Check if user exists
            existing_user = bridge_api.get_user(bridge_subaccount_id, unique_id)
            
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
                        uid=unique_id,
                        email=email,
                        first_name=first_name,
                        last_name=last_name
                    )
                    user_created = True
                except BridgeUserExists:
                    # User was created between check and create - get it
                    existing_user = bridge_api.get_user(bridge_subaccount_id, unique_id)
                    if existing_user:
                        bridge_user = existing_user
        except BridgeAPIError as e:
            return JsonResponse({
                'error': f'Failed to create/update Bridge user: {str(e)}'
            }, status=500)
        
        # Create or update OHSAccount in Django
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
            # Create new account
            account = OHSAccount.objects.create(
                unique_id=unique_id,
                user_email=email,
                first_name=first_name,
                last_name=last_name,
                company_name=company_name,
                bridge_subaccount_id=bridge_subaccount_id,
                bridge_user_id=bridge_user.get('id') if bridge_user else None,
                bridge_account_id=subaccount.get('id') if subaccount else None,
            )
        
        # Return success response
        return JsonResponse({
            'success': True,
            'message': 'User synced to Bridge successfully',
            'data': {
                'unique_id': unique_id,
                'bridge_subaccount_id': bridge_subaccount_id,
                'bridge_user_id': bridge_user.get('id') if bridge_user else None,
                'subaccount_created': subaccount_created,
                'user_created': user_created,
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'error': f'Internal server error: {str(e)}'
        }, status=500)

