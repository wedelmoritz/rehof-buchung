"""`EncryptedCharField` – app-seitige Feld-Verschlüsselung, **VORBEREITET** (P2.5, ADR 0061).

**Noch an KEINEM Modell aktiv.** Das Feld liegt bereit, damit die Umstellung in
Produktion ein kleiner, gezielter Schritt bleibt:

1. `FIELD_ENCRYPTION_KEY` setzen (Schlüssel via `manage.py field_key` erzeugen).
2. Das sensibelste PII-Feld (z.B. `Member.iban`) von `CharField` auf
   `EncryptedCharField` umstellen, `max_length` großzügig (Fernet-Token ist deutlich
   länger als die IBAN) und eine Daten-Migration schreiben, die Altbestände einmalig
   verschlüsselt.

Ohne gesetzten Schlüssel verhält sich das Feld wie ein normales `CharField`
(Klartext) – so lässt es sich gefahrlos einführen und schrittweise scharf schalten.
Details/Trade-offs (Schlüsselverlust = Datenverlust, nicht such-/sortierbar) in
docs/BETRIEB-SICHERHEIT.md § 4.3.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from . import fieldcrypt


def _keys() -> list[str]:
    return fieldcrypt.parse_keys(getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "")


class EncryptedCharField(models.CharField):
    """CharField, dessen Wert app-seitig (Fernet) verschlüsselt in der DB liegt.

    Ist kein Schlüssel konfiguriert, fällt das Feld transparent auf Klartext zurück
    (sicherer, reversibler Rollout). Beim Lesen wird ein nicht entschlüsselbarer Wert
    (z.B. unverschlüsselter Altbestand) unverändert durchgereicht."""

    description = "CharField, app-seitig verschlüsselt (Fernet)"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        keys = _keys()
        if value in (None, "") or not keys:
            return value
        return fieldcrypt.encrypt_value(value, keys)

    def from_db_value(self, value, expression, connection):
        keys = _keys()
        if value in (None, "") or not keys:
            return value
        try:
            return fieldcrypt.decrypt_value(value, keys)
        except Exception:
            # Nicht (mehr) entschlüsselbar → unverändert (Altbestand/Klartext).
            return value
