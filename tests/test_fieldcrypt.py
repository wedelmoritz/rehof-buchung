"""Reine Tests für die (vorbereitete) Feld-Verschlüsselung – ohne Django/DB.

Deckt die Krypto-Naht ab: Round-Trip, Vertraulichkeit (Token != Klartext),
Integrität (fremder Schlüssel scheitert) und Rotation (alter Schlüssel
entschlüsselt nach Re-Encrypt mit neuem weiter).
"""
import pytest

from booking import fieldcrypt


def test_round_trip():
    key = fieldcrypt.generate_key()
    token = fieldcrypt.encrypt_value("DE89370400440532013000", [key])
    assert token != "DE89370400440532013000"
    assert fieldcrypt.decrypt_value(token, [key]) == "DE89370400440532013000"


def test_leer_und_none_unveraendert():
    key = fieldcrypt.generate_key()
    assert fieldcrypt.encrypt_value("", [key]) == ""
    assert fieldcrypt.encrypt_value(None, [key]) is None
    assert fieldcrypt.decrypt_value("", [key]) == ""
    assert fieldcrypt.decrypt_value(None, [key]) is None


def test_fremder_schluessel_scheitert():
    from cryptography.fernet import InvalidToken
    k1, k2 = fieldcrypt.generate_key(), fieldcrypt.generate_key()
    token = fieldcrypt.encrypt_value("geheim", [k1])
    with pytest.raises(InvalidToken):
        fieldcrypt.decrypt_value(token, [k2])


def test_rotation_alter_schluessel_entschluesselt_weiter():
    alt = fieldcrypt.generate_key()
    token_alt = fieldcrypt.encrypt_value("IBAN", [alt])
    neu = fieldcrypt.generate_key()
    # Rotation: neuer Schlüssel zuerst, alter bleibt zum Entschlüsseln dabei.
    keys = [neu, alt]
    assert fieldcrypt.decrypt_value(token_alt, keys) == "IBAN"
    # Neu verschlüsselt nutzt den ersten (neuen) Schlüssel.
    token_neu = fieldcrypt.encrypt_value("IBAN", keys)
    assert fieldcrypt.decrypt_value(token_neu, [neu]) == "IBAN"


def test_parse_keys():
    assert fieldcrypt.parse_keys("") == []
    assert fieldcrypt.parse_keys("a, b ,c") == ["a", "b", "c"]
