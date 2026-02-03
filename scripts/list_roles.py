#!/usr/bin/env python
"""
Script to list all roles in a Bridge subaccount.

Usage:
    python scripts/list_roles.py <subdomain>

Example:
    python scripts/list_roles.py ohsi-testsso13-safetynow
"""
import os
import sys
import django

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ohsinsider.settings')
django.setup()

from lms.bridge_api import BridgeAPI
from django.conf import settings

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/list_roles.py <subdomain>")
        print("\nExample:")
        print("  python scripts/list_roles.py ohsi-testsso13-safetynow")
        sys.exit(1)
    
    subdomain = sys.argv[1]
    
    print(f"\n{'='*80}")
    print(f"Listing roles for subaccount: {subdomain}")
    print(f"{'='*80}\n")
    
    try:
        bridge_api = BridgeAPI()
        roles = bridge_api.list_roles(subdomain)
        
        if not roles:
            print("No roles found in this subaccount.")
            return
        
        print(f"Found {len(roles)} role(s):\n")
        print(f"{'ID':<40} {'Name':<50}")
        print(f"{'-'*40} {'-'*50}")
        
        for role in roles:
            role_id = role.get('id', 'N/A')
            role_name = role.get('name', 'N/A')
            print(f"{role_id:<40} {role_name:<50}")
        
        print(f"\n{'='*80}")
        print("\nTo use a role, you can either:")
        print("  1. Use the role name (e.g., 'Sub Account Administrator')")
        print("  2. Use the role ID directly (e.g., '25fed615-b7e8-4190-af30-b7ade587d04b')")
        print(f"\n{'='*80}\n")
        
        # Check for common role names
        common_names = [
            'Sub Account Administrator',
            'Sub Account Admin',
            'Account Admin',
            'Admin',
            'Administrator'
        ]
        
        print("\nChecking for common role names:")
        for name in common_names:
            matching_roles = [r for r in roles if name.lower() in r.get('name', '').lower()]
            if matching_roles:
                print(f"  ✓ Found '{name}' matches:")
                for role in matching_roles:
                    print(f"      - {role.get('name')} (ID: {role.get('id')})")
            else:
                print(f"  ✗ No match for '{name}'")
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()

