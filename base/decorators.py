from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def staff_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not request.user.is_staff:
            messages.error(request, "Staff access required.")
            return redirect("member_dashboard")
        return view_func(request, *args, **kwargs)

    return _wrapped


def member_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if request.user.is_staff:
            return view_func(request, *args, **kwargs)
        if not hasattr(request.user, "member_account"):
            messages.error(request, "Member profile not configured.")
            return redirect("logout")
        return view_func(request, *args, **kwargs)

    return _wrapped
