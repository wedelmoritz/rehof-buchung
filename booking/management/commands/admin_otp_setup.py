"""Richtet Zwei-Faktor (TOTP) für ein Backend-/Admin-Konto ein (ADR 0061).

Provisioniert ein **bestätigtes** TOTP-Gerät und gibt die `otpauth://`-URI sowie
einen QR-Code (ASCII) aus, den die Authenticator-App (z.B. Aegis, FreeOTP,
Google Authenticator) einscannt. Danach verlangt das Backend für dieses Konto
einen 6-stelligen Code (sofern ADMIN_OTP_REQUIRED an ist – in Produktion Default).

    python manage.py admin_otp_setup --user admin
    python manage.py admin_otp_setup --user admin --reset   # altes Gerät ersetzen

Sicherheitshinweis: Die URI/der QR enthält das gemeinsame Geheimnis. Nur auf einem
vertrauenswürdigen Terminal ausführen und die Ausgabe nicht aufbewahren.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Richtet ein bestätigtes TOTP-Gerät für ein Backend-Konto ein (2FA)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", required=True,
            help="Benutzername des Kontos, für das 2FA eingerichtet wird.")
        parser.add_argument(
            "--name", default="Backend",
            help="Anzeigename des Geräts (Default: Backend).")
        parser.add_argument(
            "--reset", action="store_true",
            help="Vorhandene TOTP-Geräte dieses Kontos vorher löschen.")

    def handle(self, *args, **opts):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        User = get_user_model()
        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"Kein Konto mit Benutzername '{opts['user']}'.")

        if not (user.is_staff or user.is_superuser):
            self.stdout.write(self.style.WARNING(
                "Hinweis: Dieses Konto ist weder Staff noch Superuser – 2FA wirkt "
                "erst, wenn es Backend-Zugang hat."))

        if opts["reset"]:
            n, _ = TOTPDevice.objects.filter(user=user).delete()
            if n:
                self.stdout.write(f"{n} vorhandene(s) TOTP-Gerät(e) gelöscht.")

        existing = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        if existing and not opts["reset"]:
            raise CommandError(
                "Konto hat bereits ein bestätigtes TOTP-Gerät. Mit --reset ersetzen.")

        # confirmed=True: sofort wirksam (das Geheimnis wird hier ausgegeben, der
        # erste App-Code verifiziert sich implizit beim nächsten Login).
        device = TOTPDevice.objects.create(user=user, name=opts["name"], confirmed=True)
        uri = device.config_url

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"TOTP-Gerät '{opts['name']}' für '{user.username}' angelegt."))
        self.stdout.write("")
        self.stdout.write("1) Diesen QR-Code in der Authenticator-App scannen:")
        self.stdout.write("")
        self._print_qr(uri)
        self.stdout.write("")
        self.stdout.write("   …oder die URI manuell eintragen:")
        self.stdout.write(f"   {uri}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(
            "2) Ausgabe NICHT aufbewahren (enthält das 2FA-Geheimnis)."))
        self.stdout.write(
            "3) Beim nächsten Backend-Login zusätzlich den 6-stelligen Code eingeben.")

    def _print_qr(self, uri: str):
        """QR als ASCII ins Terminal – ohne Bilddatei, scanbar von der App."""
        try:
            import qrcode
        except Exception:  # pragma: no cover - qrcode ist Pflichtabhängigkeit
            self.stdout.write("   (qrcode nicht installiert – bitte URI manuell nutzen)")
            return
        qr = qrcode.QRCode(border=1)
        qr.add_data(uri)
        qr.make(fit=True)
        qr.print_ascii(out=self.stdout, invert=True)
