"""End-to-End-Smoke-Tests der kritischen Pfade gegen einen laufenden Stack.

Bewusst wenige, robuste Tests: erreichbar bleiben (Health), Anmeldung, die
Buchungs-Seite lädt, und der Geld-Pfad Hofladen (Artikel → Kasse → Rechnung).
Sie ergänzen die Django-Integrationstests um die echte Browser-/Server-Naht
(gunicorn, WhiteNoise, Cookies, JS), die `manage.py test` nicht abdeckt.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect


def test_healthz(page, base_url):
    """Der Health-Endpoint ist ohne Login erreichbar und meldet ok."""
    resp = page.request.get(f"{base_url}/healthz/")
    assert resp.status == 200
    assert resp.json().get("status") == "ok"


def test_anmeldung_fuehrt_zur_uebersicht(login, page, base_url):
    login()
    page.goto(f"{base_url}/")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url
    assert page.get_by_role("heading", name=re.compile("Übersicht")).first.is_visible()


def test_falsche_anmeldung_scheitert(login, page, base_url):
    login(password="falsch-falsch")
    # Bleibt auf der Login-Seite (keine Session)
    assert "/login" in page.url


def test_buchen_kalender_laedt(login, page, base_url):
    login()
    page.goto(f"{base_url}/buchen/")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url
    assert page.locator("table.book-cal").first.is_visible()


def test_hofladen_einkauf_bis_rechnung(login, page, base_url):
    """Geld-Pfad: Artikel in den Warenkorb, zur Kasse, verbindlich kaufen +
    sofort abrechnen → eine Rechnung entsteht."""
    login()
    page.goto(f"{base_url}/hofladen/")
    page.wait_for_load_state("networkidle")
    # Ein Produkt OHNE Pflicht-Termin wählen (Dienstleistungen brauchen ein Datum).
    plain = page.locator(
        "form.tile:not(:has(input[name=service_date])) button[type=submit]")
    assert plain.count() > 0, "keine Produkte im Katalog (Testdaten?)"
    plain.first.click()
    # Auf die Warenkorb-Zeile warten (Add läuft per AJAX, tauscht <main>).
    expect(page.locator(".cart-row").first).to_be_visible(timeout=8000)

    # Zur Kasse, „sofort abrechnen" ankreuzen und verbindlich kaufen.
    page.goto(f"{base_url}/hofladen/kasse/")
    page.wait_for_load_state("networkidle")
    page.check("input[name=invoice_now]")
    page.click("button:has-text('Verbindlich kaufen')")
    # Landet auf einer Rechnung mit Nummer HL-JJJJ-MM-NNN.
    expect(page.locator("body")).to_contain_text(
        re.compile(r"HL-\d{4}-\d{2}-\d{3}"), timeout=8000)
