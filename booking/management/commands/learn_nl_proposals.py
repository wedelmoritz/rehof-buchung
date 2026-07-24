"""Lern-Lauf für den NL-Parser (ADR 0113, NL-L2): erzeugt aus den pseudonymen
Signalen robuste, menschlich zu bestätigende Vorschläge. Idempotent; nur bei Opt-in.
Läuft nächtlich über den `run_scheduler`.
"""
from django.core.management.base import BaseCommand

from booking import services as svc


class Command(BaseCommand):
    help = "Erzeugt NL-Lern-Vorschläge (Aliase/Reihung) aus den pseudonymen Signalen."

    def handle(self, *args, **opts):
        out = svc.mine_nl_proposals()
        self.stdout.write(
            f"NL-Lernen: {out['alias']} Alias- + {out['ranking']} Reihungs-Vorschläge neu.")
