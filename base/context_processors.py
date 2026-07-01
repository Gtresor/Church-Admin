from base.models import ActivityLog


def notifications(request):
    if not request.user.is_authenticated:
        return {}

    if request.user.is_staff:
        unread_count = ActivityLog.objects.filter(is_read=False).count()
        recent = list(ActivityLog.objects.select_related("actor").filter(is_read=False).order_by("-created_at")[:5])
        if not recent:
            recent = list(ActivityLog.objects.select_related("actor").order_by("-created_at")[:5])
        return {
            "notif_unread_count": unread_count,
            "notif_recent": recent,
        }

    # Member notifications
    try:
        qs = request.user.member_notifications
        unread_count = qs.filter(is_read=False).count()
        recent = list(qs.filter(is_read=False).order_by("-created_at")[:5])
        if not recent:
            recent = list(qs.order_by("-created_at")[:5])
        return {
            "member_notif_unread_count": unread_count,
            "member_notif_recent": recent,
        }
    except Exception:
        return {}
