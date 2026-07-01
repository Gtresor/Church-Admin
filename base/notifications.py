import logging
from html.parser import HTMLParser

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _strip_tags(html):
    class _S(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, d):
            self.parts.append(d)

    p = _S()
    p.feed(html)
    return " ".join(p.parts)


def _send(subject, to_email, template_name, context):
    """Fire-and-forget email. Logs failures, never raises."""
    if not to_email:
        return
    try:
        html = render_to_string(f"emails/{template_name}.html", context)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=_strip_tags(html),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )
        msg.attach_alternative(html, "text/html")
        msg.send()
    except Exception:
        logger.exception("Email send failed: %s → %s", template_name, to_email)


# ---------------------------------------------------------------------------
# Account notifications
# ---------------------------------------------------------------------------

def send_welcome(person, username, temp_password=None):
    """Welcome email on account creation. Pass temp_password when admin creates the account."""
    _send(
        subject="Welcome to New Life Bible Church — Your Account is Ready",
        to_email=person.email,
        template_name="welcome",
        context={
            "name": person.first_name,
            "username": username,
            "temp_password": temp_password,
        },
    )


# ---------------------------------------------------------------------------
# Wedding notifications
# ---------------------------------------------------------------------------

def send_partner_invite(wrequest, invite_url):
    """Send wedding consent invite link to the partner."""
    if wrequest.partner:
        to = wrequest.partner.email
    elif wrequest.partner_non_member_data:
        to = wrequest.partner_non_member_data.get("email", "")
    else:
        to = ""
    submitter_name = f"{wrequest.submitter.first_name} {wrequest.submitter.last_name}".strip()
    _send(
        subject="You've Been Invited to Confirm a Wedding Request",
        to_email=to,
        template_name="partner_invite",
        context={"wrequest": wrequest, "invite_url": invite_url, "submitter_name": submitter_name},
    )


def notify_admin_new_wedding_request(wrequest, review_url):
    """Notify admin staff of a new pending wedding request."""
    to = getattr(settings, "STAFF_NOTIFICATION_EMAIL", "")
    if not to:
        return
    submitter_name = f"{wrequest.submitter.first_name} {wrequest.submitter.last_name}".strip()
    _send(
        subject=f"New Wedding Request — {submitter_name}",
        to_email=to,
        template_name="admin_new_wedding",
        context={"wrequest": wrequest, "review_url": review_url, "submitter_name": submitter_name},
    )


def notify_admin_wedding_cancelled(wrequest):
    """Notify admin staff that a member withdrew their wedding request."""
    to = getattr(settings, "STAFF_NOTIFICATION_EMAIL", "")
    if not to:
        return
    name = f"{wrequest.submitter.first_name} {wrequest.submitter.last_name}".strip()
    _send(
        subject=f"Wedding Request Withdrawn — {name}",
        to_email=to,
        template_name="wedding_cancelled_admin",
        context={"wrequest": wrequest, "name": name},
    )


def send_wedding_approved(wrequest):
    """Notify submitter their wedding request was approved."""
    _send(
        subject="Your Wedding Request Has Been Approved",
        to_email=wrequest.submitter.email,
        template_name="wedding_approved",
        context={"wrequest": wrequest, "name": wrequest.submitter.first_name},
    )


def send_wedding_rejected(wrequest):
    """Notify submitter their wedding request was declined."""
    _send(
        subject="Update on Your Wedding Request",
        to_email=wrequest.submitter.email,
        template_name="wedding_rejected",
        context={"wrequest": wrequest, "name": wrequest.submitter.first_name},
    )


def send_wedding_scheduled(wedding):
    """Notify both groom and bride that the wedding date has been confirmed."""
    date_str = wedding.wedding_date.strftime("%d %B %Y") if wedding.wedding_date else "TBD"
    for person in [wedding.groom, wedding.bride]:
        if person and person.email:
            _send(
                subject="Your Wedding Has Been Scheduled",
                to_email=person.email,
                template_name="wedding_scheduled",
                context={"wedding": wedding, "name": person.first_name, "date_str": date_str},
            )


# ---------------------------------------------------------------------------
# Baptism notifications
# ---------------------------------------------------------------------------

def notify_admin_new_baptism(baptism, review_url):
    """Notify admin of a new baptism request."""
    to = getattr(settings, "STAFF_NOTIFICATION_EMAIL", "")
    if not to:
        return
    name = f"{baptism.person.first_name} {baptism.person.last_name}".strip()
    _send(
        subject=f"New Baptism Request — {name}",
        to_email=to,
        template_name="admin_new_baptism",
        context={"baptism": baptism, "review_url": review_url, "name": name},
    )


def send_baptism_status(baptism, action):
    """Notify member of a baptism status change."""
    to = baptism.person.email
    if not to:
        return
    labels = {
        "approve": ("Baptism Request Approved", "approved"),
        "reject": ("Update on Your Baptism Request", "declined"),
        "cancel": ("Update on Your Baptism Request", "cancelled"),
        "schedule": ("Your Baptism Has Been Scheduled", "scheduled"),
        "complete": ("Baptism Record Updated", "completed"),
    }
    subject, status_label = labels.get(action, ("Update on Your Baptism Request", action))
    _send(
        subject=subject,
        to_email=to,
        template_name="baptism_status",
        context={"baptism": baptism, "name": baptism.person.first_name, "status_label": status_label},
    )


# ---------------------------------------------------------------------------
# Baby dedication notifications
# ---------------------------------------------------------------------------

def notify_admin_new_dedication(dedication, review_url):
    """Notify admin of a new baby dedication request."""
    to = getattr(settings, "STAFF_NOTIFICATION_EMAIL", "")
    if not to:
        return
    child_name = f"{dedication.child.first_name} {dedication.child.last_name}".strip()
    _send(
        subject=f"New Baby Dedication Request — {child_name}",
        to_email=to,
        template_name="admin_new_dedication",
        context={"dedication": dedication, "review_url": review_url, "child_name": child_name},
    )


def send_dedication_status(dedication, action):
    """Notify parent of a dedication status change."""
    parent = dedication.mother or dedication.father
    to = parent.email if parent else ""
    if not to:
        return
    labels = {
        "approve": ("Baby Dedication Request Approved", "approved"),
        "reject": ("Update on Your Baby Dedication Request", "declined"),
        "schedule": ("Baby Dedication Has Been Scheduled", "scheduled"),
        "complete": ("Baby Dedication Record Updated", "completed"),
    }
    subject, status_label = labels.get(action, ("Update on Your Baby Dedication Request", action))
    child_name = f"{dedication.child.first_name} {dedication.child.last_name}".strip()
    _send(
        subject=subject,
        to_email=to,
        template_name="dedication_status",
        context={
            "dedication": dedication,
            "child_name": child_name,
            "status_label": status_label,
            "name": parent.first_name,
        },
    )
