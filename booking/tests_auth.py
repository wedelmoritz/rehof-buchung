"""Tests rund um Authentifizierung, Selbstregistrierung und Freischaltung."""
from __future__ import annotations

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from booking import services as svc
from booking.models import Member, Membership, OpsConfig, OutboxEmail, Share
from booking.permissions import VERWALTUNG_GROUP

PW = "Korbflechter7x"


class RegistrierungUndFreischaltungTests(TestCase):
    def test_registrierung_legt_konto_ohne_profil_an(self):
        resp = self.client.post(reverse("register"), {
            "email": "neu@example.org", "name": "Neu Mitglied",
            "password1": PW, "password2": PW,
        })
        self.assertRedirects(resp, reverse("pending"))
        user = User.objects.get(email="neu@example.org")
        self.assertEqual(user.username, "neu@example.org")  # E-Mail = Benutzername
        self.assertFalse(user.is_staff)
        self.assertFalse(hasattr(user, "member"))  # noch kein Buchungs-Profil

    def test_konto_ohne_profil_sieht_nichts(self):
        user = User.objects.create_user("warte", "warte@example.org", PW)
        self.client.force_login(user)
        # Übersicht ist gesperrt → Umleitung auf die Warte-Seite
        self.assertRedirects(self.client.get(reverse("overview")), reverse("pending"))
        self.assertRedirects(self.client.get(reverse("wishlist")), reverse("pending"))
        # Nach Zuordnung eines Mitglieds-Profils ist alles erreichbar
        Member.objects.create(user=user, display_name="Warte")
        self.assertEqual(self.client.get(reverse("overview")).status_code, 200)

    def test_doppelte_email_wird_abgelehnt(self):
        User.objects.create_user("a@example.org", "a@example.org", PW)
        resp = self.client.post(reverse("register"), {
            "email": "a@example.org", "name": "Zwei",
            "password1": PW, "password2": PW,
        })
        self.assertEqual(resp.status_code, 200)  # Formular mit Fehler
        self.assertEqual(User.objects.filter(email="a@example.org").count(), 1)

    def test_unplausibler_name_wird_abgelehnt(self):
        # Name mit Ziffern/Markup -> Formularfehler, kein Konto.
        resp = self.client.post(reverse("register"), {
            "email": "neu2@example.org", "name": "<b>Hack3r",
            "password1": PW, "password2": PW,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="neu2@example.org").exists())

    def test_registrierung_benachrichtigt_verwaltung(self):
        # Mit hinterlegter Verwaltungs-Adresse geht bei Selbstregistrierung eine
        # „neuer Benutzer wartet auf Zuordnung"-Mail in die Outbox.
        cfg = OpsConfig.get_solo()
        cfg.admin_emails = "verwaltung@example.org"
        cfg.save()
        self.client.post(reverse("register"), {
            "email": "frisch@example.org", "name": "Frisch Konto",
            "password1": PW, "password2": PW,
        })
        mail = OutboxEmail.objects.filter(to_email="verwaltung@example.org").first()
        self.assertIsNotNone(mail)
        self.assertIn("Neuer Benutzer", mail.subject)
        self.assertIn("frisch@example.org", mail.body)

    def test_registrierung_ohne_adresse_keine_mail(self):
        # Ohne hinterlegte Verwaltungs-Adresse passiert nichts (kein Fehler).
        self.client.post(reverse("register"), {
            "email": "frisch2@example.org", "name": "Frisch Zwei",
            "password1": PW, "password2": PW,
        })
        self.assertEqual(OutboxEmail.objects.count(), 0)


class NeueBenutzerOhneAnteilTests(TestCase):
    """`users_without_membership`: liefert genau die noch nicht zugeordneten Konten."""

    def test_listet_konten_ohne_anteil_und_blendet_zugeordnete_aus(self):
        # 1) Konto ohne Mitglieds-Profil -> wartet auf Zuordnung
        ohne_profil = User.objects.create_user("ohne", "ohne@e.de", PW)
        # 2) Konto mit Profil aber ohne Anteil -> wartet ebenfalls
        mit_profil = User.objects.create_user("mitprofil", "mp@e.de", PW)
        Member.objects.create(user=mit_profil, display_name="Mit Profil")
        # 3) Vollständig zugeordnetes Konto -> NICHT in der Liste
        fertig = User.objects.create_user("fertig", "f@e.de", PW)
        m = Member.objects.create(user=fertig, display_name="Fertig")
        ms = Membership.objects.create(label="Anteil A")
        Share.objects.create(membership=ms, member=m, night_budget=50)
        # 4) Verwaltungs-Konto -> braucht kein Profil, NICHT in der Liste
        verw = User.objects.create_user("verw", "v@e.de", PW)
        verw.groups.add(Group.objects.get_or_create(name=VERWALTUNG_GROUP)[0])
        # 5) Admin/Superuser -> NICHT in der Liste
        User.objects.create_superuser("chef", "chef@e.de", PW)
        # 6) Externer Gast mit Profil -> NICHT in der Liste
        gast = User.objects.create_user("gast", "g@e.de", PW)
        Member.objects.create(user=gast, display_name="Gast", is_external=True)

        result = set(svc.users_without_membership().values_list("username", flat=True))
        self.assertEqual(result, {"ohne", "mitprofil"})


class OnboardingServiceTests(TestCase):
    """Geführte Erst-Zuordnung (ADR 0056): Service-Funktionen."""

    def test_onboard_als_mitglied_neuer_anteil(self):
        u = User.objects.create_user("neu", "neu@e.de", PW)
        share = svc.onboard_as_member(u, display_name="Neu Person",
                                      night_budget=40, wish_night_budget=20)
        u.refresh_from_db()
        self.assertEqual(u.member.display_name, "Neu Person")
        self.assertFalse(u.member.is_external)
        self.assertEqual(share.night_budget, 40)
        self.assertEqual(share.wish_night_budget, 20)
        # nicht mehr „offen"
        self.assertNotIn("neu", svc.users_without_membership().values_list(
            "username", flat=True))

    def test_onboard_als_mitglied_bestehender_anteil(self):
        u = User.objects.create_user("neu2", "neu2@e.de", PW)
        ms = Membership.objects.create(label="Anteil B")
        svc.onboard_as_member(u, display_name="Zwei", night_budget=10,
                              wish_night_budget=5, membership_id=ms.pk)
        self.assertEqual(ms.shares.count(), 1)
        self.assertEqual(ms.shares.first().member.user, u)

    def test_onboard_als_terminal_macht_hofladen_gast(self):
        u = User.objects.create_user("term", "term@e.de", PW)
        m = svc.onboard_as_terminal(u, display_name="Terminal Gast")
        self.assertTrue(m.is_external)
        self.assertTrue(m.terminal_enabled)
        self.assertEqual(m.shares.count(), 0)        # kein Buchungs-Anteil
        self.assertNotIn("term", svc.users_without_membership().values_list(
            "username", flat=True))

    def test_deactivate(self):
        u = User.objects.create_user("weg", "weg@e.de", PW)
        svc.deactivate_account(u)
        u.refresh_from_db()
        self.assertFalse(u.is_active)


class OnboardingAdminTests(TestCase):
    """Die geführte Seite im Backend (Superuser): GET + die vier Aktionen."""

    def setUp(self):
        self.su = User.objects.create_superuser("root", "root@e.de", PW)
        self.client.force_login(self.su)
        self.url = reverse("admin:booking_pendinguser_changelist")

    def _pending(self):
        u = User.objects.create_user("kandidat", "k@e.de", PW)
        return u

    def test_seite_zeigt_offene_konten(self):
        self._pending()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "kandidat")

    def test_aktion_mitglied(self):
        u = self._pending()
        self.client.post(self.url, {
            "action": "member", "user_id": u.pk, "display_name": "Kandidat",
            "membership": "new", "new_label": "Anteil X",
            "night_budget": "30", "wish_night_budget": "15"})
        u.refresh_from_db()
        self.assertEqual(u.member.shares.first().night_budget, 30)
        self.assertEqual(Membership.objects.filter(label="Anteil X").count(), 1)

    def test_aktion_terminal(self):
        u = self._pending()
        self.client.post(self.url, {
            "action": "terminal", "user_id": u.pk, "display_name": "Kandidat"})
        u.refresh_from_db()
        self.assertTrue(u.member.is_external)
        self.assertTrue(u.member.terminal_enabled)

    def test_aktion_deaktivieren_und_loeschen(self):
        u = self._pending()
        self.client.post(self.url, {"action": "deactivate", "user_id": u.pk})
        u.refresh_from_db(); self.assertFalse(u.is_active)
        u2 = User.objects.create_user("weg2", "weg2@e.de", PW)
        self.client.post(self.url, {"action": "delete", "user_id": u2.pk})
        self.assertFalse(User.objects.filter(pk=u2.pk).exists())


class LoginTests(TestCase):
    def test_login_per_email_und_benutzername(self):
        user = User.objects.create_user("hans", "hans@example.org", PW)
        Member.objects.create(user=user, display_name="Hans")
        # per E-Mail
        ok = self.client.post(reverse("login"),
                              {"username": "hans@example.org", "password": PW})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        # per Benutzername
        self.client.post(reverse("login"), {"username": "hans", "password": PW})
        self.assertIn("_auth_user_id", self.client.session)

    def test_losdurchlauf_kann_nicht_manuell_angelegt_werden(self):
        """Regression: das manuelle Anlegen schlug mit 500 fehl (Pflicht-Seed
        nicht setzbar). Die Add-Ansicht ist jetzt gesperrt."""
        su = User.objects.create_superuser("root", "root@example.org", PW)
        self.client.force_login(su)
        resp = self.client.get("/admin/booking/lotteryrun/add/")
        self.assertEqual(resp.status_code, 403)

    def test_brute_force_sperrt_auch_korrektes_passwort(self):
        user = User.objects.create_user("opfer", "opfer@example.org", PW)
        Member.objects.create(user=user, display_name="Opfer")
        for _ in range(5):
            self.client.post(reverse("login"),
                             {"username": "opfer", "password": "falsch-falsch"})
        # Auch mit korrektem Passwort jetzt gesperrt (django-axes)
        self.client.post(reverse("login"), {"username": "opfer", "password": PW})
        self.assertNotIn("_auth_user_id", self.client.session)


class ProfilAnmeldedatenTests(TestCase):
    """Mitglied ändert E-Mail (= Login) und Passwort selbst im Profil."""

    def setUp(self):
        self.user = User.objects.create_user("max", "max@example.org", PW)
        Member.objects.create(user=self.user, display_name="Max")
        self.client.force_login(self.user)

    def test_email_aendern_setzt_login_und_ist_eindeutig(self):
        # Bestätigung mit dem aktuellen Passwort, KEIN neues Passwort nötig.
        resp = self.client.post(reverse("profile"), {
            "action": "change_email", "email": "neu@example.org",
            "password": PW})
        self.assertRedirects(resp, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "neu@example.org")
        # Login folgt der E-Mail: Benutzername = neue E-Mail
        self.assertEqual(self.user.username, "neu@example.org")
        # Passwort unverändert
        self.assertTrue(self.user.check_password(PW))
        # Anmeldung mit der neuen E-Mail klappt, mit der alten nicht mehr
        self.client.logout()
        self.client.post(reverse("login"),
                         {"username": "neu@example.org", "password": PW})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        self.client.post(reverse("login"),
                         {"username": "max@example.org", "password": PW})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_email_aendern_braucht_korrektes_passwort(self):
        resp = self.client.post(reverse("profile"), {
            "action": "change_email", "email": "neu@example.org",
            "password": "falsch-falsch"})
        self.assertEqual(resp.status_code, 200)   # Formular mit Fehler
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "max@example.org")  # unverändert

    def test_email_aendern_lehnt_fremde_email_ab(self):
        User.objects.create_user("other", "other@example.org", PW)
        resp = self.client.post(reverse("profile"), {
            "action": "change_email", "email": "other@example.org",
            "password": PW})
        self.assertEqual(resp.status_code, 200)   # Formular mit Fehler
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "max@example.org")  # unverändert

    def test_passwort_aendern_bleibt_eingeloggt(self):
        new_pw = "Drachenflieger9z"
        resp = self.client.post(reverse("profile"), {
            "action": "change_password",
            "old_password": PW,
            "new_password1": new_pw, "new_password2": new_pw})
        self.assertRedirects(resp, reverse("profile"))
        # Session bleibt gültig (update_session_auth_hash)
        self.assertIn("_auth_user_id", self.client.session)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_pw))


class HealthCheckTests(TestCase):
    """/healthz/ ist ohne Login erreichbar und meldet die DB-Erreichbarkeit."""

    def test_healthz_ok_ohne_login(self):
        r = self.client.get(reverse("healthz"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ok")

    def test_healthz_nicht_freigeschaltet_erreichbar(self):
        # Eingeloggt, aber ohne Mitglieds-Profil – die Aktivierungs-Sperre darf
        # den Health-Check nicht umleiten.
        u = User.objects.create_user("warte_h", "warte_h@example.org", PW)
        self.client.force_login(u)
        r = self.client.get(reverse("healthz"))
        self.assertEqual(r.status_code, 200)


class RechtstexteTests(TestCase):
    """Impressum (Pflicht), Datenschutz & AGB – öffentlich erreichbar, im Fuß verlinkt."""

    def test_impressum_oeffentlich(self):
        from shop.models import ShopConfig
        ShopConfig.objects.create(
            coop_name="Re:Hof eG", coop_address="Hofweg 1\n12345 Dorf",
            board="Vorstand X", contact_email="info@example.org")
        r = self.client.get(reverse("imprint"))      # anonym
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Re:Hof eG")
        self.assertContains(r, "§ 5 DDG")
        self.assertContains(r, reverse("imprint"))   # Fuß verlinkt Impressum

    def test_datenschutz_und_agb(self):
        from shop.models import ShopConfig
        ShopConfig.objects.create(
            privacy_policy="Wir schützen deine Daten.", terms_agb="Es gelten AGB.")
        self.assertContains(self.client.get(reverse("privacy")), "schützen")
        self.assertContains(self.client.get(reverse("terms")), "AGB")
        # Im Fuß verlinkt, weil gepflegt
        self.assertContains(self.client.get(reverse("imprint")), reverse("privacy"))

    def test_nicht_freigeschalteter_nutzer_erreicht_impressum(self):
        from shop.models import ShopConfig
        ShopConfig.objects.create(coop_name="Re:Hof eG")
        u = User.objects.create_user("warte9", "warte9@example.org", PW)
        self.client.force_login(u)   # eingeloggt, aber kein Mitglied
        self.assertEqual(self.client.get(reverse("imprint")).status_code, 200)
