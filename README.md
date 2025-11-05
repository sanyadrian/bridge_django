# OHS Insider Bridge SSO Integration

This Django application provides SSO integration between OHS Insider WordPress and Bridge LMS, allowing users to seamlessly access their Bridge subaccounts.

## Features

- **Direct SSO**: Users log directly into their specific Bridge subaccount
- **Unique ID Mapping**: Maps OHS Insider unique IDs to Bridge subaccounts
- **Secure Authentication**: HMAC-signed tokens for secure communication
- **User Migration**: Script to migrate existing WordPress users
- **Access Logging**: Tracks user access attempts and authentication

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│   OHS Insider   │    │  OHS Django App  │    │  Bridge LMS        │
│   WordPress     │───▶│  (This App)      │───▶│  safetynow.bridge  │
│   (Existing)    │    │                  │    │  app.com           │
└─────────────────┘    └──────────────────┘    └─────────────────────┘
```

## Installation

### 1. Django Application Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver
```

### 2. WordPress Plugin Installation

1. Upload the `ohsinsider-bridge-plugin` folder to your WordPress `/wp-content/plugins/` directory
2. Activate the plugin in WordPress admin
3. Configure the plugin settings:
   - Django Base URL: `https://ohsinsider-bridge.yourdomain.com`
   - Client ID: Get from Django admin
   - Client Secret: Get from Django admin
   - Bridge Subaccount Mapping: JSON mapping of unique IDs to Bridge subaccounts

### 3. User Migration

```bash
# Run the migration script
python scripts/migrate_ohs_users.py
```

## Configuration

### Django Settings

Update `ohsinsider/settings.py`:

```python
# Database configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'ohsinsider_bridge',
        'USER': 'your_db_user',
        'PASSWORD': 'your_db_password',
        'HOST': 'localhost',
        'PORT': '3306',
    }
}

# Bridge LMS configuration
OHS_BRIDGE_BASE_URL = 'https://safetynow.bridgeapp.com'
OHS_BRIDGE_API_KEY = 'your-bridge-api-key'
OHS_BRIDGE_API_SECRET = 'your-bridge-api-secret'
```

### WordPress Plugin Settings

1. Go to WordPress Admin → Settings → OHS Bridge SSO
2. Configure:
   - **Django Base URL**: Your Django application URL
   - **Client ID**: Generated in Django admin
   - **Client Secret**: Generated in Django admin
   - **Bridge Subaccount Mapping**: JSON mapping of unique IDs

## Usage

### For Users

1. Users log into OHS Insider WordPress with their existing credentials
2. Click "Access Bridge LMS" button (added via shortcode)
3. Automatically redirected to their specific Bridge subaccount
4. Seamless access to learning content

### For Administrators

1. **Django Admin**: Manage OHS accounts, authentication, and sync tasks
2. **Access Logs**: Monitor user access attempts
3. **Sync Tasks**: Track Bridge LMS synchronization status

## API Endpoints

- `POST /onlogin/` - WordPress login notifications
- `GET /auth/<unique_id>/` - User authentication and Bridge redirect
- `GET /bridge/callback/` - Bridge SSO callback
- `GET /health/` - Health check

## Security

- **HMAC Signatures**: All communications are HMAC-signed
- **Token Expiration**: Tokens expire after 5 minutes
- **IP Logging**: All access attempts are logged with IP addresses
- **Secure Redirects**: All redirects use HTTPS

## Troubleshooting

### Common Issues

1. **"Account not found"**: User's unique ID not in Django database
2. **"Invalid signature"**: Client secret mismatch between WordPress and Django
3. **"Token expired"**: Authentication took too long (>5 minutes)

### Debug Mode

Enable debug logging in Django settings:

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'debug.log',
        },
    },
    'loggers': {
        'lms': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}
```

## Support

For technical support, contact the development team or check the Django admin logs for detailed error information.
