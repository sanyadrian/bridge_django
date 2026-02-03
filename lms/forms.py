"""
Forms for OHS Insider LMS admin.
"""
from django import forms
from .models import OHSAccount


class PrefixSelectForm(forms.Form):
    """Form for selecting prefix (OHSI/HRI/ILT) in admin."""
    prefix = forms.ChoiceField(
        choices=[
            ('', 'All'),
            ('ohsi', 'OHSI'),
            ('hri', 'HRI'),
            ('ilt', 'ILT'),
        ],
        required=False,
        widget=forms.Select(attrs={
            'style': 'height:auto;',
            'onchange': 'this.form.submit();'
        })
    )

