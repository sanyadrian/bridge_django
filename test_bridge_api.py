#!/usr/bin/env python3
"""
Test script to verify Bridge API credentials work.
This tests direct Bridge API access before testing the sync endpoint.
"""
import os
import sys
from decouple import config
import requests

# Load from .env
BRIDGE_API_KEY = config('BRIDGE_API_KEY', default='')
BRIDGE_API_SECRET = config('BRIDGE_API_SECRET', default='')
ROOT_SUBDOMAIN = 'safetynow'

def test_bridge_api():
    """Test Bridge API credentials."""
    print("=" * 60)
    print("Testing Bridge API Credentials")
    print("=" * 60)
    
    if not BRIDGE_API_KEY or not BRIDGE_API_SECRET:
        print("\n❌ ERROR: Bridge API credentials not found in .env file")
        print("Make sure .env file has:")
        print("  BRIDGE_API_KEY=your-key")
        print("  BRIDGE_API_SECRET=your-secret")
        return False
    
    print(f"\nAPI Key: {BRIDGE_API_KEY[:20]}...")
    print(f"API Secret: {BRIDGE_API_SECRET[:20]}...")
    print(f"Root Subdomain: {ROOT_SUBDOMAIN}")
    
    # Test 1: List subaccounts (simple API call)
    print("\n" + "-" * 60)
    print("Test 1: Listing subaccounts (limit 10)")
    print("-" * 60)
    
    url = f'https://{ROOT_SUBDOMAIN}.bridgeapp.com/api/admin/sub_accounts'
    params = {'limit': 10}
    
    try:
        response = requests.get(
            url,
            auth=(BRIDGE_API_KEY, BRIDGE_API_SECRET),
            params=params,
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            subaccounts = data.get('sub_accounts', [])
            print(f"✅ SUCCESS! Found {len(subaccounts)} subaccounts")
            
            if subaccounts:
                print("\nFirst few subaccounts:")
                for sa in subaccounts[:3]:
                    print(f"  - {sa.get('subdomain')}: {sa.get('name')}")
            
            return True
        else:
            print(f"❌ ERROR: {response.status_code}")
            try:
                error_data = response.json()
                print(f"Error: {error_data}")
            except:
                print(f"Response: {response.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ ERROR: Request timed out (30 seconds)")
        print("Bridge API might be slow or unreachable")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR: Request failed: {str(e)}")
        return False

if __name__ == '__main__':
    # Change to script directory to load .env
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    success = test_bridge_api()
    
    if success:
        print("\n" + "=" * 60)
        print("✅ Bridge API credentials are working!")
        print("You can now test the sync endpoint.")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ Bridge API test failed.")
        print("\nCheck:")
        print("1. API credentials in .env file are correct")
        print("2. API key has permissions to list subaccounts")
        print("3. Network can reach Bridge API")
        print("=" * 60)
        sys.exit(1)

