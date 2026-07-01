from base.models import ActivityLog


def log(actor, action, category, description):
    """One-liner activity logger for views. actor may be None."""
    ActivityLog.objects.create(
        actor=actor,
        action=action,
        category=category,
        description=description,
    )


def notify_member(person, category, message):
    """Create an in-app notification for the member account linked to `person`."""
    try:
        user = person.member_account.user
    except Exception:
        return
    from base.models import MemberNotification
    MemberNotification.objects.create(user=user, category=category, message=message)
