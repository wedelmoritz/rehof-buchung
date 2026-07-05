"""Tests für Rollen-Kombinationen und den Mitgliedsstatus (ADR 0087).

Deckt ab:
* Mitgliedsstatus aktiv/passiv/ausgeschieden (Buchsperre, Login-Aus, Übergänge).
* Ausscheide-Workflow (Zukunftsbuchungen löschen/abbrechen) über das Admin-Formular.
* **Rollen-Matrix**: welche Navigation/Zugriffe ein Konto je nach Kombination aus
  Admin (Superuser) · Verwaltung (Rolle/Gruppe) · Mitglied (Profil) + Status sieht,
  inkl. der Kombinationen, die es NICHT geben sollte.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from booking.models import (
    Allocation, EquivalenceClass, Member, Membership, Quarter, Share,
)
from booking.permissions import ensure_verwaltung_group
from booking import services as svc


NEXT = date.today().year + 1


def mk_account(username, *, superuser=False, verwaltung=False, member=True,
               status="active", with_booking=False):
    """Baut ein Konto in einer bestimmten Rollen-/Status-Kombination."""
    user = User.objects.create_user(username=username, password="x" * 12,
                                    email=f"{username}@example.org")
    if superuser:
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=["is_superuser", "is_staff"])
    if verwaltung:
        user.groups.add(ensure_verwaltung_group())
    m = None
    if member:
        m = Member.objects.create(user=user, display_name=username)
        ms = Membership.objects.create(eg_number=f"EG-{username}", label=username,
                                       annual_night_budget=50, wish_night_budget=25)
        Share.objects.create(membership=ms, member=m, night_budget=50,
                             wish_night_budget=25)
        y = date.today()
        if status == "passive":
            m.passive_from = y - timedelta(days=1)
        elif status == "excluded":
            m.excluded_from = y - timedelta(days=1)
        m.save()
        if with_booking:
            q = Quarter.objects.get_or_create(
                name="Zim", defaults={"eq_class": EquivalenceClass.objects.get_or_create(name="K")[0],
                                      "min_occupancy": 1, "max_occupancy": 4})[0]
            Allocation.objects.create(member=m, quarter=q, start=date(NEXT, 6, 1),
                                      end=date(NEXT, 6, 4), persons=2,
                                      source="spontaneous")
    return user, m


class MitgliedsstatusTests(TestCase):
    def setUp(self):
        self.cls = EquivalenceClass.objects.create(name="Klein")
        self.q = Quarter.objects.create(name="K1", eq_class=self.cls,
                                        min_occupancy=1, max_occupancy=4)
        BookingPeriod = __import__("booking.models", fromlist=["BookingPeriod"]).BookingPeriod
        self.period = BookingPeriod.objects.create(
            name="glob", target_year=NEXT, start=date(NEXT, 1, 1),
            end=date(NEXT + 1, 1, 1), status=BookingPeriod.FREE_BOOKING)

    def test_status_property(self):
        _, m = mk_account("s1")
        self.assertEqual(m.status, "active")
        self.assertTrue(m.can_book)
        m.passive_from = date.today()
        self.assertEqual(m.status, "passive")
        self.assertFalse(m.can_book)
        m.excluded_from = date.today()
        self.assertEqual(m.status, "excluded")   # ausgeschieden hat Vorrang
        # Zukunfts-Datum wirkt noch nicht
        m.passive_from = date.today() + timedelta(days=5)
        m.excluded_from = None
        self.assertEqual(m.status, "active")

    def test_passiv_darf_nicht_buchen_oder_wuenschen(self):
        _, m = mk_account("s2", status="passive")
        a, err = svc.book_spontaneous(m, self.q, date(NEXT, 7, 1), date(NEXT, 7, 4))
        self.assertIsNone(a)
        self.assertIn("nicht buchungsberechtigt", err)
        w, werr = svc.add_wish(m, self.period, self.q, date(NEXT, 7, 1), date(NEXT, 7, 4))
        self.assertIsNone(w)
        self.assertIn("nicht buchungsberechtigt", werr)

    def test_ausscheide_uebergang_deaktiviert_login(self):
        user, m = mk_account("s3", status="excluded")
        self.assertTrue(user.is_active)   # erst der Lauf schaltet ab
        n = svc.apply_member_status_transitions()
        self.assertEqual(n, 1)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_ausscheide_workflow_zukunftsbuchung(self):
        from booking.admin import MemberProfileForm
        user, m = mk_account("s4", with_booking=True)  # Buchung 1.–4.6. NEXT
        # Ausscheide-Datum VOR der Buchung ohne Löschfreigabe → ungültig
        data = {"user": m.user_id, "display_name": m.display_name, "factor": "1.0",
                "excluded_from": date(NEXT, 5, 1).isoformat()}
        form = MemberProfileForm(data=data, instance=m)
        self.assertFalse(form.is_valid())
        self.assertIn("excluded_from", form.errors)
        # Mit Löschfreigabe → gültig, Buchung wird storniert
        data["delete_future_bookings"] = "on"
        form2 = MemberProfileForm(data=data, instance=m)
        self.assertTrue(form2.is_valid(), form2.errors)
        form2.save()
        self.assertFalse(Allocation.objects.filter(member=m).exists())


class RollenMatrixTests(TestCase):
    """Welche Navigation/Zugriffe je Rollen-Kombination? Der Nav-Probe-View ist
    `/hilfe/` (für alle eingeloggten Konten erreichbar)."""

    NAV = {
        "buchen": 'href="/buchen/"',
        "wunsch": 'href="/wunschliste/"',
        "meine": 'href="/meine-buchungen/"',
        "uebersicht": 'title="Übersicht"',
        "hofladen": 'href="/hofladen/"',
        "verwaltung": 'href="/verwaltung/"',
        "backend": 'href="/admin/"',
    }

    def _nav(self, user):
        """Nur die Seitenleisten-Navigation (`<aside class="sidenav">…</aside>`)
        auswerten – der Seiten-INHALT der Hilfe verlinkt selbst auf /buchen/ etc."""
        self.client.force_login(user)
        html = self.client.get(reverse("help")).content.decode()
        start = html.find('class="sidenav"')
        end = html.find("</aside>", start)
        assert start != -1 and end != -1, "Seitenleiste nicht gefunden"
        return html[start:end]

    def assertNav(self, html, present, absent):
        for key in present:
            self.assertIn(self.NAV[key], html, f"{key} sollte sichtbar sein")
        for key in absent:
            self.assertNotIn(self.NAV[key], html, f"{key} sollte NICHT sichtbar sein")

    def test_nur_mitglied_aktiv(self):
        user, _ = mk_account("m_only")
        html = self._nav(user)
        self.assertNav(html,
                       present=["buchen", "wunsch", "meine", "uebersicht", "hofladen"],
                       absent=["verwaltung", "backend"])

    def test_mitglied_passiv_ohne_buchung(self):
        user, _ = mk_account("m_pass", status="passive")
        html = self._nav(user)
        self.assertNav(html, present=["hofladen"],
                       absent=["buchen", "wunsch", "meine", "uebersicht",
                               "verwaltung", "backend"])

    def test_mitglied_passiv_mit_buchung(self):
        user, _ = mk_account("m_pass2", status="passive", with_booking=True)
        html = self._nav(user)
        self.assertNav(html, present=["meine", "uebersicht", "hofladen"],
                       absent=["buchen", "wunsch", "verwaltung", "backend"])

    def test_nur_verwaltung(self):
        user, _ = mk_account("v_only", verwaltung=True, member=False)
        html = self._nav(user)
        self.assertNav(html, present=["uebersicht", "verwaltung"],
                       absent=["buchen", "hofladen", "backend"])

    def test_nur_admin(self):
        # Admin (Superuser) ist per Definition auch Verwaltung → sieht Backend.
        user, _ = mk_account("a_only", superuser=True, member=False)
        html = self._nav(user)
        self.assertNav(html, present=["uebersicht", "verwaltung", "backend"],
                       absent=["buchen", "hofladen"])

    def test_mitglied_und_verwaltung(self):
        user, _ = mk_account("mv", verwaltung=True)
        html = self._nav(user)
        self.assertNav(html,
                       present=["buchen", "meine", "hofladen", "verwaltung"],
                       absent=["backend"])

    def test_mitglied_und_admin(self):
        user, _ = mk_account("ma", superuser=True)
        html = self._nav(user)
        self.assertNav(html,
                       present=["buchen", "meine", "hofladen", "verwaltung", "backend"],
                       absent=[])

    # --- Zugriffskontrolle (nicht nur Nav) -------------------------------- #
    def test_zugriff_backend_nur_admin(self):
        vuser, _ = mk_account("z_v", verwaltung=True, member=False)
        auser, _ = mk_account("z_a", superuser=True, member=False)
        self.client.force_login(vuser)
        self.assertNotEqual(self.client.get("/admin/").status_code, 200)  # Login-Redirect
        self.client.force_login(auser)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_zugriff_dashboard_nur_verwaltung(self):
        muser, _ = mk_account("z_m")
        vuser, _ = mk_account("z_v2", verwaltung=True, member=False)
        self.client.force_login(muser)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)  # weg
        self.client.force_login(vuser)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_zugriff_buchen_passiv_gesperrt(self):
        auser, _ = mk_account("z_active")
        puser, _ = mk_account("z_pass", status="passive")
        self.client.force_login(auser)
        self.assertEqual(self.client.get(reverse("book")).status_code, 200)
        self.client.force_login(puser)
        self.assertEqual(self.client.get(reverse("book")).status_code, 302)  # gesperrt
