"""Dünne Anbindung an die Mollie Payments API – NUR aktiv, wenn in den
„Rechtliche & Zahlungs-Einstellungen“ ein `test_…`/`live_…`-Key hinterlegt ist. Bewusst minimal
(Zahlung anlegen + Status abfragen) und ohne Fremd-Abhängigkeit (stdlib).

Im Test-Modus (kein Key) wird dieses Modul nie importiert – dann läuft die
eingebaute Sandbox (siehe `shop/payments.py`)."""
from __future__ import annotations

import json
import urllib.request
from decimal import Decimal

API = "https://api.mollie.com/v2"


def _request(api_key: str, path: str, payload: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(API + path, data=data, headers=headers,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def create_payment(*, api_key, amount, currency, description, redirect_url,
                   webhook_url="", metadata=None):
    """Legt eine Mollie-Zahlung an; liefert (payment_id, checkout_url)."""
    payload = {
        "amount": {"currency": currency, "value": f"{Decimal(amount):.2f}"},
        "description": description,
        "redirectUrl": redirect_url,
        "metadata": metadata or {},
    }
    # Mollie akzeptiert keine localhost-Webhooks – nur öffentliche URLs senden.
    if webhook_url.startswith("http") and "localhost" not in webhook_url \
            and "127.0.0.1" not in webhook_url:
        payload["webhookUrl"] = webhook_url
    data = _request(api_key, "/payments", payload)
    return data["id"], data["_links"]["checkout"]["href"]


def payment_status(api_key: str, provider_id: str) -> str:
    """Aktueller Status einer Mollie-Zahlung (z. B. „paid“, „open“, „expired“)."""
    return _request(api_key, f"/payments/{provider_id}")["status"]
