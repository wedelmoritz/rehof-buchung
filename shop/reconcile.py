"""Kontoabgleich: Kontoauszug importieren und offene Rechnungen über
Betrag + Rechnungsnummer im Verwendungszweck automatisch als bezahlt verbuchen.

Konservativ: automatisch verbucht wird nur bei einem **eindeutigen** Treffer
(Rechnungsnummer im Verwendungszweck UND exakt passender Betrag). Alles andere
bleibt unzugeordnet und wird in der Verwaltung manuell behandelt. Der Status
einer Rechnung bleibt in der Verwaltung jederzeit manuell änderbar.
"""
from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

from . import bankimport, services
from .models import BankImport, BankTransaction, Invoice


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def find_invoice_for(txn: BankTransaction) -> Invoice | None:
    """Sucht die eindeutig passende, noch nicht bestätigte Rechnung."""
    norm_purpose = _norm(txn.purpose)
    if not norm_purpose:
        return None
    candidates = (Invoice.objects.exclude(status=Invoice.CONFIRMED)
                  .select_related("member").order_by("year", "month", "number"))
    for inv in candidates:
        if _norm(inv.number) in norm_purpose and txn.amount == inv.total_gross:
            return inv
    return None


@transaction.atomic
def book_payment(txn: BankTransaction, invoice: Invoice, note: str = "") -> None:
    """Verbucht eine Zahlung: Rechnung → bestätigt, Verknüpfung setzen und das
    Mitglied benachrichtigen (In-App + E-Mail)."""
    services.confirm_invoice(invoice)
    txn.matched_invoice = invoice
    txn.matched_at = timezone.now()
    txn.note = note or "automatisch zugeordnet"
    txn.save(update_fields=["matched_invoice", "matched_at", "note"])

    from booking.models import Notification
    from booking.services import email_member, absolute_url
    url = f"/hofladen/rechnung/{invoice.id}/"
    Notification.objects.create(
        member=invoice.member,
        message=f"Rechnung {invoice.number} wurde als bezahlt verbucht.",
        url=url)
    email_member(
        invoice.member, f"Zahlungseingang zu Rechnung {invoice.number}",
        f"Hallo {invoice.member.display_name},\n\nwir haben deine Zahlung zu "
        f"Rechnung {invoice.number} über {invoice.total_gross} € erhalten und die "
        f"Rechnung als bezahlt verbucht. Vielen Dank!\n\n{absolute_url(url)}\n\n"
        f"Viele Grüße\nRe:Hof")


def reconcile_unmatched(queryset=None) -> int:
    """Versucht, noch nicht zugeordnete Eingänge automatisch zu verbuchen.
    Gibt die Anzahl neu verbuchter Zahlungen zurück."""
    qs = queryset if queryset is not None else BankTransaction.objects.all()
    qs = qs.filter(matched_invoice__isnull=True, amount__gt=0)
    n = 0
    for txn in qs:
        inv = find_invoice_for(txn)
        if inv:
            book_payment(txn, inv)
            n += 1
    return n


@transaction.atomic
def import_bank_statement(data: bytes, fmt: str, filename: str = "") -> BankImport:
    """Liest einen Kontoauszug ein, legt neue Zahlungseingänge an (dedupliziert
    über den Fingerabdruck) und gleicht sie sofort ab."""
    parsed = bankimport.parse(data, fmt)
    batch = BankImport.objects.create(
        filename=filename[:200], fmt=fmt, n_total=len(parsed))
    new_txns: list[BankTransaction] = []
    for p in parsed:
        fp = p.fingerprint()
        if BankTransaction.objects.filter(fingerprint=fp).exists():
            continue                       # Doppel-Import desselben Auszugs
        new_txns.append(BankTransaction.objects.create(
            batch=batch, booked_on=p.booked_on, amount=p.amount,
            purpose=p.purpose, counterparty_name=p.name,
            counterparty_iban=p.iban, fingerprint=fp, raw=p.raw))
    matched = reconcile_unmatched(
        BankTransaction.objects.filter(id__in=[t.id for t in new_txns]))
    batch.n_imported = len(new_txns)
    batch.n_matched = matched
    batch.save(update_fields=["n_imported", "n_matched"])
    return batch
