"""Erzeugt einen Schlüssel für die app-seitige Feld-Verschlüsselung (P2.5, ADR 0061).

    python manage.py field_key

Die Ausgabe als `FIELD_ENCRYPTION_KEY` in die `.env` eintragen (getrennt von der
DB sichern!). Für eine **Rotation** den neuen Schlüssel **vor** den alten setzen:

    FIELD_ENCRYPTION_KEY=<neu>,<alt>

Hinweis: Die Feld-Verschlüsselung (`EncryptedCharField`) ist vorbereitet, aber noch
an keinem Modellfeld aktiv – siehe docs/BETRIEB-SICHERHEIT.md § 4.3.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from booking import fieldcrypt


class Command(BaseCommand):
    help = "Erzeugt einen Fernet-Schlüssel für FIELD_ENCRYPTION_KEY."

    def handle(self, *args, **opts):
        self.stdout.write("# In die .env eintragen (GETRENNT von der DB sichern!):")
        self.stdout.write(f"FIELD_ENCRYPTION_KEY={fieldcrypt.generate_key()}")
