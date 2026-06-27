"""Erzeugt ein VAPID-Schlüsselpaar für Web-Push (mobil, PWA).

Einmalig vor der Aktivierung von Push ausführen; die Ausgabe in die `.env`
eintragen. Ohne diese Schlüssel ist Push aus (siehe ADR 0044).

    python manage.py vapid_keys

Formate (Konvention der Web-Push-Bibliotheken):
  * VAPID_PUBLIC_KEY  = base64url des unkomprimierten EC-P-256-Punkts (65 Byte) –
    geht als `applicationServerKey` an den Browser.
  * VAPID_PRIVATE_KEY = base64url des privaten 32-Byte-Skalars – bleibt geheim,
    wird serverseitig von pywebpush genutzt.
"""
from __future__ import annotations

import base64

from django.core.management.base import BaseCommand


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Command(BaseCommand):
    help = "Erzeugt ein VAPID-Schlüsselpaar (VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY)."

    def handle(self, *args, **opts):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization

        priv = ec.generate_private_key(ec.SECP256R1())
        priv_raw = priv.private_numbers().private_value.to_bytes(32, "big")
        pub_raw = priv.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)

        self.stdout.write("# In die .env eintragen (und web/cron neu starten):")
        self.stdout.write(f"VAPID_PUBLIC_KEY={_b64url(pub_raw)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={_b64url(priv_raw)}")
        self.stdout.write("VAPID_ADMIN_EMAIL=admin@deine-domain.de")
