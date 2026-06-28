"""Tests für booking.fields.EncryptedCharField (vorbereitet, P2.5/ADR 0061).

Prüft das Feldverhalten ohne echtes Modell, direkt über get_prep_value/
from_db_value: ohne Schlüssel Klartext (gefahrlos einführbar), mit Schlüssel
verschlüsselt-in-DB / entschlüsselt-beim-Lesen, und unverschlüsselter Altbestand
wird beim Lesen unverändert durchgereicht.
"""
from django.test import SimpleTestCase, override_settings

from booking import fieldcrypt
from booking.fields import EncryptedCharField

KEY = fieldcrypt.generate_key()


class EncryptedCharFieldTests(SimpleTestCase):
    def setUp(self):
        self.f = EncryptedCharField(max_length=255)

    @override_settings(FIELD_ENCRYPTION_KEY="")
    def test_ohne_schluessel_klartext(self):
        # Gefahrloser Rollout: ohne Schlüssel wie ein normales CharField.
        stored = self.f.get_prep_value("DE89370400440532013000")
        self.assertEqual(stored, "DE89370400440532013000")
        self.assertEqual(self.f.from_db_value(stored, None, None),
                         "DE89370400440532013000")

    @override_settings(FIELD_ENCRYPTION_KEY=KEY)
    def test_mit_schluessel_round_trip(self):
        stored = self.f.get_prep_value("DE89370400440532013000")
        self.assertNotEqual(stored, "DE89370400440532013000")   # verschlüsselt in der DB
        self.assertEqual(self.f.from_db_value(stored, None, None),
                         "DE89370400440532013000")

    @override_settings(FIELD_ENCRYPTION_KEY=KEY)
    def test_altbestand_klartext_wird_durchgereicht(self):
        # Ein (noch) unverschlüsselter Wert in der DB darf beim Lesen nicht crashen.
        self.assertEqual(self.f.from_db_value("DE89370400440532013000", None, None),
                         "DE89370400440532013000")

    @override_settings(FIELD_ENCRYPTION_KEY=KEY)
    def test_leerwerte(self):
        self.assertIsNone(self.f.get_prep_value(None))
        self.assertEqual(self.f.get_prep_value(""), "")
