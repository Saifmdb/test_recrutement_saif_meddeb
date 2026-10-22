import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string

from ..models import Candidature

logger = logging.getLogger("admissions")


def notify_team(c: Candidature) -> bool:
    """E-mail the business team about a new request. Returns True if sent."""
    ctx = {"c": c, "f": c.formation}
    msg = EmailMultiAlternatives(
        subject=f"[Admissions] Nouvelle demande {c.reference} — {c.formation.specialite} ({c.formation.ecole})",
        body=render_to_string("admissions/email_team.txt", ctx),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=settings.ADMISSIONS_TEAM_EMAILS,
        reply_to=[c.email],
    )
    msg.attach_alternative(render_to_string("admissions/email_team.html", ctx), "text/html")
    try:
        msg.send()
        c.notification_envoyee = True
    except Exception:
        logger.exception("Team notification failed for %s", c.reference)
        c.notification_envoyee = False
    c.save(update_fields=["notification_envoyee"])
    return c.notification_envoyee


def confirm_prospect(c: Candidature) -> None:
    if not settings.SEND_PROSPECT_CONFIRMATION_EMAIL:
        return
    try:
        send_mail(
            subject=f"Votre demande d'inscription {c.reference} a bien été reçue",
            message=render_to_string("admissions/email_prospect.txt", {"c": c, "f": c.formation}),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[c.email],
        )
    except Exception:
        logger.exception("Prospect confirmation e-mail failed for %s", c.reference)
