from django import template
from django.urls import reverse
from ..models import Certificate

register = template.Library()


@register.filter
def certificate_source_url(certificate):
    """Get the admin review URL for the sacrament linked to a certificate."""
    linked = certificate.linked_object
    if not linked:
        return None
    if certificate.service_type == Certificate.BAPTISM:
        return reverse("admin_baptism_review", kwargs={"baptism_id": linked.id})
    elif certificate.service_type == Certificate.DEDICATION:
        return reverse("admin_dedication_review", kwargs={"dedication_id": linked.id})
    elif certificate.service_type == Certificate.WEDDING:
        return reverse("admin_wedding_review", kwargs={"wedding_id": linked.id})
    return None


@register.filter
def certificate_source_name(certificate):
    """Get the display name for the person/couple linked to a certificate."""
    linked = certificate.linked_object
    if not linked:
        return "-"
    if certificate.service_type == Certificate.BAPTISM:
        return str(linked.person)
    elif certificate.service_type == Certificate.DEDICATION:
        return str(linked.child)
    elif certificate.service_type == Certificate.WEDDING:
        return f"{linked.groom} & {linked.bride}"
    return "-"