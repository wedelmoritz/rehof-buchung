"""App-seitige Feld-Verschlüsselung – **vorbereitet, noch nicht aktiv** (P2.5, ADR 0061).

Django-frei (daher in `tests/` ohne DB testbar). Nutzt **Fernet** aus `cryptography`
(AES-128-CBC + HMAC-SHA256, authentifiziert – schützt Vertraulichkeit UND Integrität).
Mehrere Schlüssel erlauben **Rotation**: der erste verschlüsselt, alle entschlüsseln
(MultiFernet). Schlüssel sind base64url-kodierte 32-Byte-Fernet-Keys.

Diese Funktionen sind die reine Krypto-Naht; die Anbindung an ein Modellfeld liegt in
`booking/fields.py` (`EncryptedCharField`). **Noch an keinem Feld aktiv** – Aktivierung
für Produktion: Schlüssel via `FIELD_ENCRYPTION_KEY` setzen und das betreffende Feld
auf `EncryptedCharField` umstellen (siehe docs/BETRIEB-SICHERHEIT.md § 4.3).
"""
from __future__ import annotations

from typing import Optional, Sequence


def generate_key() -> str:
    """Erzeugt einen neuen Fernet-Schlüssel (base64url, 32 Byte) als Text."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("ascii")


def parse_keys(raw: str) -> list[str]:
    """Zerlegt einen `FIELD_ENCRYPTION_KEY`-Wert (komma-separiert) in eine Liste.
    Erlaubt Rotation: `neuer_key,alter_key` – verschlüsselt mit dem ersten,
    entschlüsselt mit jedem."""
    return [k.strip() for k in (raw or "").split(",") if k.strip()]


def _fernet(keys: Sequence[str]):
    from cryptography.fernet import Fernet, MultiFernet
    if not keys:
        raise ValueError("Kein Schlüssel für die Feld-Verschlüsselung angegeben.")
    return MultiFernet([Fernet(k.encode("ascii")) for k in keys])


def encrypt_value(plaintext: Optional[str], keys: Sequence[str]) -> Optional[str]:
    """Verschlüsselt Klartext zu einem Fernet-Token (ASCII). None/'' bleiben unverändert."""
    if plaintext is None or plaintext == "":
        return plaintext
    return _fernet(keys).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_value(token: Optional[str], keys: Sequence[str]) -> Optional[str]:
    """Entschlüsselt einen Fernet-Token. None/'' bleiben unverändert. Wirft bei
    ungültigem/fremdem Token (InvalidToken) – die Feld-Klasse fängt das ab."""
    if token is None or token == "":
        return token
    return _fernet(keys).decrypt(token.encode("ascii")).decode("utf-8")
