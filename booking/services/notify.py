"""Service-Layer (notify): Benachrichtigungen & E-Mail: In-App-Notifications, Outbox-Mails, Web-Push, URLs.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from ..models import (
    OutboxEmail,
)

__all__ = [
    'unread_notifications', 'mark_notifications_read', 'absolute_url',
    'queue_email', 'email_member', 'queue_email_many', 'email_admins',
    'email_cleaning', 'send_web_push', 'send_account_invite',
    'notify_admins_new_user', 'dispatch_event',
]


def dispatch_event(event_key: str, context: dict | None = None, *, member=None,
                   recipients=None, attachment: bytes | None = None,
                   attachment_name: str = "", url: str = ""):
    """Zentrale Benachrichtigungs-Naht (ADR 0089): rendert die Vorlage aus dem
    Katalog **sicher** und verschickt sie gemäß der Backend-`NotificationSetting`
    (an/aus, Empfänger). ``member``-Ereignisse gehen als In-App + Mail (Opt-in) ans
    Mitglied; ``ops``/``cleaning``/``broadcast`` als Mail an die Empfängerliste
    (optional mit PDF-Anhang). Gibt die eingereihte(n) Mail(s) zurück (oder None)."""
    from ..models import Notification, NotificationSetting, OpsConfig
    from ..notify_catalog import EVENTS, render
    ev = EVENTS.get(event_key)
    if ev is None:
        return None
    setting = NotificationSetting.for_event(event_key)
    if not setting.enabled:
        return None
    subject, body = render(event_key, context or {})
    audience = ev["audience"]

    if audience == "member":
        if member is None:
            return None
        Notification.objects.create(member=member, message=subject[:255],
                                    detail=body, url=url)
        return email_member(member, subject, body, attachment=attachment,
                            attachment_name=attachment_name,
                            attachment_mime="application/pdf" if attachment else
                            "application/octet-stream")
    # ops / cleaning / broadcast → E-Mail an die Empfängerliste
    if recipients is None:
        recipients = (OpsConfig.get_solo().cleaning_list()
                      if audience == "cleaning" else setting.recipient_list())
    if attachment:
        return [queue_email(to, subject, body, attachment=attachment,
                            attachment_name=attachment_name,
                            attachment_mime="application/pdf")
                for to in recipients if to]
    return queue_email_many(recipients, subject, body)

def unread_notifications(member):
    return list(member.notifications.filter(read=False)) if member else []


def mark_notifications_read(member) -> int:
    if not member:
        return 0
    return member.notifications.filter(read=False).update(read=True)


def absolute_url(path: str) -> str:
    """Baut aus einem Pfad eine absolute URL für E-Mails (PUBLIC_BASE_URL)."""
    from django.conf import settings
    base = getattr(settings, "PUBLIC_BASE_URL", "") or ""
    return f"{base}{path}" if base else path


def queue_email(to_email: str, subject: str, body: str, html_body: str = "",
                member=None, attachment: bytes | None = None,
                attachment_name: str = "",
                attachment_mime: str = "application/octet-stream"
                ) -> "OutboxEmail | None":
    """Stellt eine E-Mail in die Warteschlange (versendet wird sie vom Scheduler).
    Optional mit einem Datei-Anhang (z.B. Rechnungs-PDF)."""
    to_email = (to_email or "").strip()
    if not to_email:
        return None
    return OutboxEmail.objects.create(
        to_email=to_email, subject=subject, body=body, html_body=html_body,
        member=member,
        attachment=attachment if attachment else None,
        attachment_name=attachment_name if attachment else "",
        attachment_mime=attachment_mime if attachment else "")


def email_member(member, subject: str, body: str, html_body: str = "",
                 attachment: bytes | None = None, attachment_name: str = "",
                 attachment_mime: str = "application/octet-stream"):
    """Mail an ein Mitglied – nur wenn eine Adresse hinterlegt ist UND das
    Mitglied E-Mails nicht abbestellt hat (In-App-Hinweise bleiben unberührt)."""
    if not member or not getattr(member, "email_opt_in", True):
        return None
    email = (getattr(member.user, "email", "") or "").strip()
    if not email:
        return None
    return queue_email(email, subject, body, html_body, member,
                       attachment, attachment_name, attachment_mime)


def send_account_invite(user) -> "OutboxEmail | None":
    """Schickt einem (vom Backend/Import) angelegten Benutzer eine Einladung, sein
    **Passwort selbst zu setzen** – per Token-Link (wie Passwort-Reset, nur mit
    „Passwort setzen"-Sprache). Admins vergeben also kein Passwort. Voraussetzung:
    der Benutzer hat eine E-Mail-Adresse. Gibt die eingereihte Mail zurück (oder
    None, wenn keine Adresse vorliegt)."""
    from django.contrib.auth.tokens import default_token_generator
    from django.urls import reverse
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        return None
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = absolute_url(reverse("password_reset_confirm",
                                kwargs={"uidb64": uid, "token": token}))
    name = (user.get_full_name() or user.username or "").strip()
    return queue_email(
        email,
        "Re:Hof: Konto angelegt – jetzt Passwort setzen",
        f"Hallo {name},\n\n"
        f"für dich wurde ein Re:Hof-Konto angelegt. Vergib bitte über den folgenden "
        f"Link selbst dein Passwort – danach kannst du dich mit deiner E-Mail-Adresse "
        f"anmelden:\n\n{link}\n\n"
        f"Der Link ist aus Sicherheitsgründen nur begrenzt gültig. Brauchst du einen "
        f"neuen, wende dich bitte an die Verwaltung.\n\nViele Grüße\nRe:Hof")


def queue_email_many(recipients, subject: str, body: str, html_body: str = ""):
    """Stellt dieselbe Mail an mehrere Adressen ein (für Verwaltungs-Mails)."""
    return [em for to in recipients
            if (em := queue_email(to, subject, body, html_body))]


def email_admins(subject: str, body: str, html_body: str = ""):
    from ..models import OpsConfig
    return queue_email_many(OpsConfig.get_solo().admin_list(), subject, body, html_body)


def email_cleaning(subject: str, body: str, html_body: str = ""):
    from ..models import OpsConfig
    return queue_email_many(OpsConfig.get_solo().cleaning_list(), subject, body, html_body)


def notify_admins_new_user(user):
    """Mailt der Verwaltung, dass sich ein neuer Benutzer registriert hat und noch
    einem Mitglieds-Anteil zugeordnet werden muss (sonst kann die Person nicht
    buchen). Empfänger sind die Verwaltungs-Adressen aus den Betriebs-Einstellungen
    (`OpsConfig.admin_emails`); ohne hinterlegte Adresse passiert nichts."""
    from django.urls import NoReverseMatch, reverse
    name = (user.get_full_name() or user.username or "").strip()
    email = (getattr(user, "email", "") or "").strip()
    try:
        link = absolute_url(reverse("admin:auth_user_change", args=[user.pk]))
    except NoReverseMatch:
        link = absolute_url("/admin/auth/user/")
    body = (
        "Ein neuer Benutzer hat sich registriert und wartet auf die Zuordnung zu "
        "einem Mitglieds-Anteil:\n\n"
        f"Benutzer: {user.username}\n"
        f"Name: {name or '—'}\n"
        f"E-Mail: {email or '—'}\n\n"
        "Bitte im Backend das Mitglieds-Profil ausfüllen und einen Tage-Anteil "
        "zuordnen – erst dann kann die Person buchen:\n"
        f"{link}\n\n"
        "Alle noch nicht zugeordneten Benutzer stehen gesammelt oben auf der "
        "Backend-Startseite.\n\nRe:Hof")
    return email_admins("Re:Hof: Neuer Benutzer wartet auf Zuordnung", body)


def _vapid_sub_claim() -> str:
    """Baut den VAPID-`sub`-Claim. **Apple** (web.push.apple.com) ist strikt und
    LEHNT ungültige `sub` ab (z. B. `mailto:admin@localhost`) – Google/FCM sind hier
    nachsichtig. Daher: echte Admin-E-Mail bevorzugen, sonst die öffentliche
    Basis-URL (https-`sub` ist zulässig), erst zuletzt der localhost-Notnagel."""
    from django.conf import settings
    email = (settings.VAPID_ADMIN_EMAIL or "").strip()
    if "@" in email:
        return f"mailto:{email}"
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip()
    if base.startswith("https://"):
        return base
    return "mailto:admin@localhost"


def send_web_push(member, title: str, body: str, url: str = "") -> int:
    """Schickt eine Web-Push-Nachricht an alle Geräte des Mitglieds. Gibt die
    Anzahl erfolgreich zugestellter Push-Nachrichten zurück (0, wenn Push aus
    ist oder kein Abo besteht). Zustellfehler werden protokolliert
    (Logger `booking.push`), damit Push-Probleme nachvollziehbar sind."""
    import json
    import logging
    from urllib.parse import urlsplit
    from django.conf import settings
    log = logging.getLogger("booking.push")
    if not settings.PUSH_ENABLED:
        log.info("Push aus (keine VAPID-Schlüssel) – nichts gesendet.")
        return 0
    subs = list(member.push_subscriptions.all())
    if not subs:
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except Exception:  # pywebpush nicht installiert – Push überspringen
        log.warning("pywebpush nicht installiert – Push übersprungen.")
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url or "/"})
    claims = {"sub": _vapid_sub_claim()}
    sent = 0
    for sub in subs:
        host = urlsplit(sub.endpoint).netloc          # nur Host loggen (kein Token)
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims=dict(claims),   # pywebpush mutiert das dict (aud/exp)
                timeout=10,
            )
            sent += 1
            log.info("Push zugestellt an %s (Mitglied %s).", host, member.pk)
        except WebPushException as exc:
            resp = getattr(exc, "response", None)
            status = getattr(resp, "status_code", None)
            detail = ""
            try:
                detail = (resp.text or "")[:200] if resp is not None else ""
            except Exception:
                detail = ""
            if status in (404, 410):       # Abo abgelaufen/abgemeldet → entfernen
                sub.delete()
                log.info("Push-Abo %s abgelaufen (HTTP %s) – entfernt.", host, status)
            else:
                log.warning("Push an %s fehlgeschlagen: HTTP %s %s",
                            host, status, detail)
        except Exception as exc:           # Netzfehler o.ä. – nicht kippen lassen
            log.warning("Push an %s fehlgeschlagen: %s", host, exc)
    return sent
