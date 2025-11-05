#!/usr/bin/env python
"""
Local development setup script for OHS Insider Bridge SSO.
"""
import os
import sys
import subprocess
import django
from django.core.management import execute_from_command_line

def setup_local_environment():
    """Set up local development environment."""
    print("🚀 Setting up OHS Insider Bridge SSO - Local Development")
    print("=" * 60)
    
    # Check if we're in the right directory
    if not os.path.exists('manage.py'):
        print("❌ Please run this script from the ohsinsider-bridge directory")
        return False
    
    # Set up Django environment
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ohsinsider.settings')
    
    try:
        django.setup()
        print("✅ Django environment configured")
    except Exception as e:
        print(f"❌ Error setting up Django: {e}")
        return False
    
    return True

def create_superuser():
    """Create Django superuser for local testing."""
    print("\n👤 Creating Django superuser...")
    print("You'll need to enter username, email, and password for the admin user.")
    
    try:
        execute_from_command_line(['manage.py', 'createsuperuser'])
        print("✅ Superuser created successfully")
        return True
    except Exception as e:
        print(f"❌ Error creating superuser: {e}")
        return False

def create_sample_data():
    """Create sample data for testing."""
    print("\n📊 Creating sample data for testing...")
    
    try:
        from lms.models import OHSAccount, OHSAuth
        
        # Create authentication credentials
        auth, created = OHSAuth.objects.get_or_create(
            name='OHS Insider WordPress - Local',
            defaults={
                'is_active': True
            }
        )
        
        if created:
            print(f"✅ Created auth credentials:")
            print(f"   Client ID: {auth.client_id}")
            print(f"   Client Secret: {auth.client_secret}")
        else:
            print(f"ℹ️  Auth credentials already exist:")
            print(f"   Client ID: {auth.client_id}")
            print(f"   Client Secret: {auth.client_secret}")
        
        # Create sample OHS accounts
        sample_accounts = [
            {
                'unique_id': '2019513-AIR-G-48',
                'user_email': 'test1@ohsinsider.com',
                'first_name': 'John',
                'last_name': 'Doe',
                'bridge_subaccount_id': 'ohs_2019513_air_g_48'
            },
            {
                'unique_id': '2019514-AIR-G-49',
                'user_email': 'test2@ohsinsider.com',
                'first_name': 'Jane',
                'last_name': 'Smith',
                'bridge_subaccount_id': 'ohs_2019514_air_g_49'
            }
        ]
        
        for account_data in sample_accounts:
            account, created = OHSAccount.objects.get_or_create(
                unique_id=account_data['unique_id'],
                defaults=account_data
            )
            
            if created:
                print(f"✅ Created sample account: {account.unique_id}")
            else:
                print(f"ℹ️  Sample account already exists: {account.unique_id}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating sample data: {e}")
        return False

def run_migrations():
    """Run Django migrations."""
    print("\n🔄 Running Django migrations...")
    
    try:
        execute_from_command_line(['manage.py', 'makemigrations'])
        execute_from_command_line(['manage.py', 'migrate'])
        print("✅ Migrations completed successfully")
        return True
    except Exception as e:
        print(f"❌ Error running migrations: {e}")
        return False

def start_development_server():
    """Start Django development server."""
    print("\n🌐 Starting Django development server...")
    print("Server will be available at: http://localhost:8000")
    print("Admin panel: http://localhost:8000/admin")
    print("Press Ctrl+C to stop the server")
    print("-" * 60)
    
    try:
        execute_from_command_line(['manage.py', 'runserver', '0.0.0.0:8000'])
    except KeyboardInterrupt:
        print("\n👋 Development server stopped")
    except Exception as e:
        print(f"❌ Error starting server: {e}")

def main():
    """Main setup function."""
    if not setup_local_environment():
        return
    
    # Run migrations
    if not run_migrations():
        return
    
    # Create superuser
    if not create_superuser():
        return
    
    # Create sample data
    if not create_sample_data():
        return
    
    print("\n🎉 Setup completed successfully!")
    print("\n📋 Next steps:")
    print("1. Start the development server: python setup_local.py --server")
    print("2. Configure WordPress plugin with:")
    print(f"   - Django Base URL: http://localhost:8000")
    print("   - Client ID: (get from Django admin)")
    print("   - Client Secret: (get from Django admin)")
    print("3. Test the integration")
    
    # Check if --server flag is provided
    if '--server' in sys.argv:
        start_development_server()

if __name__ == '__main__':
    main()
