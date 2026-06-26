# 0019 – Backend (Django-Admin) als Stammdaten- und Mitgliederverwaltung

## Status

Accepted (2026-06-26)

## Kontext

Stammdaten (Mitglieder, Anteile, Quartiere, Perioden, Buchungsregeln) müssen gepflegt
und Losungen gestartet/bestätigt werden. Das soll robust, rechteabgesichert und ohne
Eigenbau-Masken möglich sein – aber **nur** für Admins (Superuser), getrennt vom
operativen Dashboard (siehe ADR 0014/0018).

## Entscheidung

Wir nutzen das **Django-Admin** als Backend `/admin/` für Stammdaten und kritische
Aktionen (`booking/admin.py`, `shop/admin.py`), zugänglich nur für **Superuser**.

- **Benutzer + Mitglieds-Profil in EINEM Formular:** `User` wird neu registriert mit
  `MemberProfileInline` (`admin.py:136-144`) – „ein Benutzer = eine Person mit Login
  UND Buchungs-/Rechnungsprofil“. `Member` ist aus dem Index ausgeblendet
  (`MemberAdmin.get_model_perms` → `{}`), bleibt aber für Autocomplete registriert
  (`admin.py:147-154`). Tage-Anteile werden am `Membership`/`Share` zugeordnet.
- **Erklärte Oberfläche:** angepasste Startseite mit Erklär-Panel
  (`admin.site.index_template = "admin/custom_index.html"`, `admin.py:49-53`); alle
  Bereiche tragen `description`-Texte.
- **Kritische Aktionen mit Rückfrage:** Losung bestätigen/zurücknehmen
  (`LotteryRunAdmin`), „Anstehende Buchungen“ als Proxy (`UpcomingAllocationAdmin`),
  Fairness-Simulation am Singleton `FairnessSimConfigAdmin` (eigener Admin-Knopf,
  `admin.py:620-650`).

## Betrachtete Alternativen

- **Eigene CRUD-Masken bauen:** viel Aufwand, den das Django-Admin geschenkt liefert.
- **Alles ins Dashboard legen:** vermischte Rollen; das Dashboard soll lesend/operativ
  bleiben, nicht Stammdaten ändern.
- **Member separat im Index führen:** doppelte Pflege von Login und Profil; das
  Inline-Modell hält beides zusammen.

## Konsequenzen

**Positiv**
- Mächtige, rechteabgesicherte Stammdatenpflege praktisch ohne Eigenbau.
- Login und Mitglieds-Profil in einem Schritt – weniger Fehler, weniger Klicks.
- Gefährliche Aktionen (Losung) sind ins Backend gekapselt und bestätigungspflichtig.

**Negativ**
- Das Django-Admin ist roh/technisch – daher die Erklär-Texte und die Trennung zum
  Dashboard.
- Anpassungen (Inlines, ausgeblendete Modelle, Custom-Index) erhöhen die Kopplung an
  Admin-Interna.
