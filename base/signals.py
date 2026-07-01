from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def on_user_login(sender, request, user, **kwargs):
    from base.models import ActivityLog
    name = f"{user.first_name} {user.last_name}".strip() or user.username
    role = "Admin" if user.is_staff else "Member"
    ActivityLog.objects.create(
        actor=user,
        action="login",
        category=ActivityLog.CAT_AUTH,
        description=f"{role} {name} logged in.",
    )
