"""
Admin views for OHS Insider LMS.
"""
from django.shortcuts import redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect


@staff_member_required
@require_POST
@csrf_protect
def set_prefix(request):
    """Set prefix filter in session and redirect back."""
    prefix = request.POST.get('prefix', '')
    request.session['admin_prefix'] = prefix if prefix else None
    
    # Redirect back to the page that sent us here
    next_url = request.POST.get('next', '/admin/')
    return redirect(next_url)

