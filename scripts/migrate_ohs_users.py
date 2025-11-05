#!/usr/bin/env python
"""
Migration script to import OHS Insider users from WordPress to Django.
"""
import os
import sys
import django
import mysql.connector
from mysql.connector import Error

# Add the project directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ohsinsider.settings')
django.setup()

from lms.models import OHSAccount, OHSAuth


class OHSUserMigrator:
    def __init__(self, wp_config):
        """
        Initialize migrator with WordPress database configuration.
        
        Args:
            wp_config (dict): WordPress database configuration
        """
        self.wp_config = wp_config
        self.connection = None
        
    def connect_to_wordpress(self):
        """Connect to WordPress database."""
        try:
            self.connection = mysql.connector.connect(
                host=self.wp_config['host'],
                database=self.wp_config['database'],
                user=self.wp_config['user'],
                password=self.wp_config['password']
            )
            print("✅ Connected to WordPress database")
            return True
        except Error as e:
            print(f"❌ Error connecting to WordPress database: {e}")
            return False
    
    def get_wordpress_users(self):
        """Get users with unique IDs from WordPress."""
        if not self.connection:
            return []
        
        try:
            cursor = self.connection.cursor(dictionary=True)
            
            # Query to get users with unique_id meta
            query = """
            SELECT 
                u.ID,
                u.user_email,
                u.display_name,
                u.user_registered,
                um_unique.meta_value as unique_id,
                um_first.meta_value as first_name,
                um_last.meta_value as last_name
            FROM wp_users u
            LEFT JOIN wp_usermeta um_unique ON u.ID = um_unique.user_id AND um_unique.meta_key = 'unique_id'
            LEFT JOIN wp_usermeta um_first ON u.ID = um_first.user_id AND um_first.meta_key = 'first_name'
            LEFT JOIN wp_usermeta um_last ON u.ID = um_last.user_id AND um_last.meta_key = 'last_name'
            WHERE um_unique.meta_value IS NOT NULL
            AND um_unique.meta_value != ''
            ORDER BY u.user_registered DESC
            """
            
            cursor.execute(query)
            users = cursor.fetchall()
            cursor.close()
            
            print(f"📊 Found {len(users)} users with unique IDs")
            return users
            
        except Error as e:
            print(f"❌ Error querying WordPress users: {e}")
            return []
    
    def map_unique_id_to_bridge_subaccount(self, unique_id):
        """
        Map unique ID to Bridge subaccount ID.
        This is where you'd implement your specific mapping logic.
        """
        # Example mapping logic - customize based on your requirements
        if unique_id.startswith('2019513'):
            return f"ohs_{unique_id.lower().replace('-', '_')}"
        elif unique_id.startswith('AIR'):
            return f"air_{unique_id.lower()}"
        else:
            # Default mapping
            return f"ohs_{unique_id.lower().replace('-', '_')}"
    
    def migrate_users(self, dry_run=True):
        """Migrate users from WordPress to Django."""
        if not self.connect_to_wordpress():
            return False
        
        users = self.get_wordpress_users()
        if not users:
            print("❌ No users found to migrate")
            return False
        
        migrated_count = 0
        skipped_count = 0
        error_count = 0
        
        print(f"\n🔄 Starting migration (dry_run={dry_run})")
        print("=" * 50)
        
        for user in users:
            try:
                unique_id = user['unique_id']
                email = user['user_email']
                first_name = user['first_name'] or ''
                last_name = user['last_name'] or ''
                
                # Check if account already exists
                if OHSAccount.objects.filter(unique_id=unique_id).exists():
                    print(f"⏭️  Skipping {unique_id} - already exists")
                    skipped_count += 1
                    continue
                
                # Map to Bridge subaccount
                bridge_subaccount_id = self.map_unique_id_to_bridge_subaccount(unique_id)
                
                if dry_run:
                    print(f"🔍 Would create: {unique_id} -> {bridge_subaccount_id} ({email})")
                else:
                    # Create the account
                    account = OHSAccount.objects.create(
                        unique_id=unique_id,
                        bridge_subaccount_id=bridge_subaccount_id,
                        user_email=email,
                        first_name=first_name,
                        last_name=last_name,
                        is_active=True
                    )
                    print(f"✅ Created: {unique_id} -> {bridge_subaccount_id}")
                
                migrated_count += 1
                
            except Exception as e:
                print(f"❌ Error migrating user {user.get('unique_id', 'unknown')}: {e}")
                error_count += 1
        
        print("\n" + "=" * 50)
        print(f"📊 Migration Summary:")
        print(f"   Migrated: {migrated_count}")
        print(f"   Skipped: {skipped_count}")
        print(f"   Errors: {error_count}")
        
        if self.connection:
            self.connection.close()
        
        return True
    
    def create_auth_credentials(self):
        """Create authentication credentials for WordPress integration."""
        auth, created = OHSAuth.objects.get_or_create(
            name='OHS Insider WordPress',
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
        
        return auth


def main():
    """Main migration function."""
    print("🚀 OHS Insider User Migration Script")
    print("=" * 40)
    
    # WordPress database configuration
    wp_config = {
        'host': 'localhost',  # Update with your WordPress database host
        'database': 'ohsinsider_wp',  # Update with your WordPress database name
        'user': 'wp_user',  # Update with your WordPress database user
        'password': 'wp_password'  # Update with your WordPress database password
    }
    
    migrator = OHSUserMigrator(wp_config)
    
    # Create authentication credentials
    print("\n🔐 Setting up authentication credentials...")
    migrator.create_auth_credentials()
    
    # Run migration (dry run first)
    print("\n🔍 Running dry run migration...")
    migrator.migrate_users(dry_run=True)
    
    # Ask for confirmation
    print("\n❓ Do you want to proceed with the actual migration? (y/N): ", end='')
    response = input().strip().lower()
    
    if response == 'y':
        print("\n🚀 Running actual migration...")
        migrator.migrate_users(dry_run=False)
        print("\n✅ Migration completed!")
    else:
        print("\n⏹️  Migration cancelled.")


if __name__ == '__main__':
    main()
