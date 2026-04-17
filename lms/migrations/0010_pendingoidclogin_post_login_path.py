# Generated manually for admin Assign Training deep links

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lms', '0009_hriaccount_iltaccount_ohsiaccount_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pendingoidclogin',
            name='post_login_path',
            field=models.CharField(
                blank=True,
                default='',
                max_length=500,
                help_text='Optional Bridge path after SSO (e.g. /author/courses/123)',
            ),
        ),
    ]
