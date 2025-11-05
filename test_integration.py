#!/usr/bin/env python
"""
Test script for OHS Insider Bridge SSO integration.
"""
import os
import sys
import requests
import json
import time
import hmac
import hashlib
from urllib.parse import urlencode

# Add the project directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ohsinsider.settings')

import django
django.setup()

from lms.models import OHSAccount, OHSAuth


class OHSIntegrationTester:
    def __init__(self, base_url='http://localhost:8000'):
        self.base_url = base_url
        self.auth = OHSAuth.objects.filter(is_active=True).first()
        
        if not self.auth:
            print("❌ No active authentication found. Run setup_local.py first.")
            sys.exit(1)
    
    def test_health_check(self):
        """Test health check endpoint."""
        print("🔍 Testing health check endpoint...")
        
        try:
            response = requests.get(f"{self.base_url}/health/", timeout=10)
            if response.status_code == 200:
                print("✅ Health check passed")
                return True
            else:
                print(f"❌ Health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Health check error: {e}")
            return False
    
    def test_wordpress_notification(self):
        """Test WordPress login notification endpoint."""
        print("\n🔍 Testing WordPress login notification...")
        
        # Get a sample account
        account = OHSAccount.objects.first()
        if not account:
            print("❌ No sample accounts found. Run setup_local.py first.")
            return False
        
        # Create test data
        data = {
            'unique_id': account.unique_id,
            'email': account.user_email,
            'first_name': account.first_name,
            'last_name': account.last_name,
            'bridge_subaccount_id': account.bridge_subaccount_id,
            'timestamp': int(time.time())
        }
        
        # Create signature
        data_string = urlencode(data, doseq=True)
        signature = hmac.new(
            self.auth.client_secret.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        data['signature'] = signature
        
        try:
            response = requests.post(
                f"{self.base_url}/onlogin/",
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            if response.status_code == 200:
                print("✅ WordPress notification test passed")
                return True
            else:
                print(f"❌ WordPress notification failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ WordPress notification error: {e}")
            return False
    
    def test_user_authentication(self):
        """Test user authentication endpoint."""
        print("\n🔍 Testing user authentication...")
        
        # Get a sample account
        account = OHSAccount.objects.first()
        if not account:
            print("❌ No sample accounts found.")
            return False
        
        try:
            response = requests.get(
                f"{self.base_url}/auth/{account.unique_id}/",
                allow_redirects=False,
                timeout=10
            )
            
            if response.status_code in [302, 301]:  # Redirect response
                print("✅ User authentication test passed (redirect received)")
                print(f"   Redirect URL: {response.headers.get('Location', 'N/A')}")
                return True
            else:
                print(f"❌ User authentication failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ User authentication error: {e}")
            return False
    
    def test_admin_access(self):
        """Test Django admin access."""
        print("\n🔍 Testing Django admin access...")
        
        try:
            response = requests.get(f"{self.base_url}/admin/", timeout=10)
            if response.status_code == 200:
                print("✅ Django admin accessible")
                return True
            else:
                print(f"❌ Django admin not accessible: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Django admin error: {e}")
            return False
    
    def run_all_tests(self):
        """Run all integration tests."""
        print("🧪 OHS Insider Bridge SSO - Integration Tests")
        print("=" * 50)
        
        tests = [
            ("Health Check", self.test_health_check),
            ("WordPress Notification", self.test_wordpress_notification),
            ("User Authentication", self.test_user_authentication),
            ("Django Admin", self.test_admin_access),
        ]
        
        passed = 0
        total = len(tests)
        
        for test_name, test_func in tests:
            if test_func():
                passed += 1
            print()  # Add spacing between tests
        
        print("=" * 50)
        print(f"📊 Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! Integration is working correctly.")
        else:
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total
    
    def print_wordpress_config(self):
        """Print WordPress plugin configuration."""
        print("\n📋 WordPress Plugin Configuration:")
        print("=" * 40)
        print(f"Django Base URL: {self.base_url}")
        print(f"Client ID: {self.auth.client_id}")
        print(f"Client Secret: {self.auth.client_secret}")
        print("\nBridge Subaccount Mapping (JSON):")
        
        mapping = {}
        for account in OHSAccount.objects.all():
            mapping[account.unique_id] = account.bridge_subaccount_id
        
        print(json.dumps(mapping, indent=2))


def main():
    """Main test function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Test OHS Insider Bridge SSO integration')
    parser.add_argument('--base-url', default='http://localhost:8000', 
                       help='Django application base URL')
    parser.add_argument('--config-only', action='store_true',
                       help='Only print WordPress configuration')
    
    args = parser.parse_args()
    
    tester = OHSIntegrationTester(args.base_url)
    
    if args.config_only:
        tester.print_wordpress_config()
    else:
        tester.run_all_tests()
        tester.print_wordpress_config()


if __name__ == '__main__':
    main()
