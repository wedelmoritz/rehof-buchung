# Konzept (Vorschlag, NICHT umgesetzt): Hofladen vor Ort für externe Gäste

> **Status: Diskussionsvorlage.** Hier ist **nichts implementiert** – dieses Dokument
> analysiert die Aufgabe nach Best Practices und legt entscheidungsreife Optionen vor.
> Eine Umsetzung erfolgt erst nach Entscheidung (dann als ADR + Code).

## 1. Aufgabe

Externe Gäste (überwiegend 60+, oft **ohne Smartphone**) sollen den **Hofladen** vor
Ort nutzen können – an einem **gemeinsamen Gerät** (Tablet oder PC mit Tastatur/
Bildschirm). Gesucht ist eine **einfache** Authentifizierung vor Ort, die **gleichzeitig
die Mitglieder-/Rechnungsdaten sicher** hält. Wenn es keine sichere, einfache Variante
gibt, ist die Alternative **Barzahlung vor Ort** ausdrücklich erlaubt.

## 2. Anforderungen

- **Einfach vor Ort:** kurze Anmeldung (kein langes Passwort tippen).
- **Sicher:** ein geteiltes Gerät darf **keine** sensiblen Daten preisgeben
  (IBAN, Anschriften, fremde Rechnungen, Profile) und **keinen** Weg ins Backend/
  zu anderen Funktionen öffnen.
- **Kein Bargeld-/Kassenzwang neu einführen** (siehe § 6 – wichtig!).
- **Datensparsam** (DSGVO, ADR 0043): am Kiosk nur, was für den Einkauf nötig ist.

## 3. Best-Practice-Recherche (Kurzfassung)

Das gesuchte Muster ist gut erprobt – **Selbstverbucher in Bibliotheken** sind der
nächste Vergleich: Patron meldet sich am **geteilten** Terminal mit Ausweis-Nummer
**+ PIN** an; geschützt wird das über **kurze Sitzungen mit Auto-Logout**, **ver-
schlüsselte Übertragung** und vor allem **Datensparsamkeit** (das Terminal zeigt nur
die Aufgabe, nicht das ganze Konto). Aus dem POS-/Kiosk-Umfeld kommen dazu: **starke
Geräte-Sperre (Kiosk-Mode, nur eine App)**, **Sperre nach N Fehlversuchen**,
**Festplatten-Verschlüsselung**, **Netz-Segmentierung**, **Sichtschutz** und – sobald
**Kartendaten** im Spiel sind – **PCI-DSS**. Letzteres umgehen wir gezielt, indem am
Kiosk **gar nicht** online bezahlt wird (§ 5).

**Kernprinzip aller Quellen:** Schwache Anmeldung (PIN) ist an geteilten Terminals
**akzeptabel – aber nur**, wenn die Sitzung **wenig darf** (reduzierte Rechte),
das **Gerät gehärtet** ist und die **angezeigten Daten minimiert** sind. Sicherheit
entsteht **nicht** durch das Verstecken von Knöpfen in der Oberfläche, sondern durch
**serverseitig erzwungene, kleine Rechte**.

Quellen am Ende des Dokuments.

## 4. Bedrohungsmodell & die fünf Sicherheits-Säulen

| Bedrohung | Gegenmaßnahme |
|---|---|
| **Schulterblick / PIN abgeschaut** | Kurze Sitzung + Auto-Logout; geklaute PIN gibt **nur** Laden-Zugang dieser Person, **kein** Bezahlen, **keine** PII-Bearbeitung |
| **PIN-Brute-Force** (4 Stellen = 10 000) | **6-stellige** PIN, **gehasht** gespeichert, **Sperre nach 5 Fehlversuchen** (wie django-axes), Benachrichtigung |
| **Kiosk-Ausbruch** (neuer Tab → /admin/, /profil/) | **Serverseitige** Beschränkung der Kiosk-Sitzung auf eine **Whitelist** von Hofladen-URLs **+** OS-Kiosk-Mode am Gerät |
| **Fremde Rechnungsdaten sichtbar** | Am Kiosk **keine** Anschrift/IBAN/fremde Rechnungen; nur eigener **Monats-Saldo**; ggf. PIN-Wiedereingabe für die Rechnungsansicht |
| **Kiosk-Modus von Unbefugten genutzt** | Kiosk-Login nur auf **provisioniertem Gerät** (Geräte-Token / IP-Allowlist); und selbst dann gilt: die Sitzung **kann nichts Sensibles** |

**Die fünf Säulen, auf denen ALLES steht (App + Betrieb):**

1. **Reduzierte Sitzung, serverseitig erzwungen.** Eine PIN-/Kiosk-Sitzung erhält ein
   Flag und darf **ausschließlich** Hofladen-Browsen/Warenkorb/Kasse + die **eigene**
   Monatsrechnung. Jeder andere Pfad (Profil, IBAN, Online-Zahlung, andere Mitglieder,
   Backend) wird **vom Server** abgewiesen – nicht nur in der UI ausgeblendet. → Selbst
   eine vollständig kompromittierte PIN-Sitzung hat einen **winzigen** Schadensradius.
2. **Gerät gehärtet (Betrieb, kein App-Code).** OS-/Browser-**Kiosk-Mode** (nur diese
   eine Seite), **Auto-Update**, **Festplatten-Verschlüsselung**, **eigenes/segmentiertes
   Netz**, **Sichtschutzfolie**, physische Sicherung. Ohne diese Basis ist **kein**
   geteiltes Terminal sicher – unabhängig von der App.
3. **PIN-Härtung.** 6-stellig, gehasht, Sperre + Alarm nach Fehlversuchen, **kurzes
   Idle-Timeout mit Auto-Logout**.
4. **Kiosk-Mode-Gating.** Die PIN-Login-Sicht ist **nur** auf dem provisionierten Gerät
   erreichbar (langlebiger **Kiosk-Token** in der Geräte-Konfiguration und/oder
   **IP-Allowlist** des Hof-Netzes). Normale Nutzer kommen nicht in den Kiosk-Modus,
   Kiosk-Sitzungen nicht in den Normal-Modus.
5. **Anlage & Freigabe NUR über das Normal-System.** Registrierung am Kiosk ist **nicht**
   möglich. Am Gerät steht ein **QR-Code + kurze URL**; die Person registriert sich
   **zuhause/per Handy** im normalen System, die **Verwaltung gibt frei** (wie bei
   internen Konten), und die Person setzt **dort** ihre Kiosk-PIN. Der Kiosk ist damit
   reine **Konsum-Oberfläche**, nie eine Verwaltungs-/Anlage-Oberfläche.

## 5. Warum am Kiosk NICHT online bezahlt wird

Bewusst: **keine** Online-Zahlung in der PIN-/Kiosk-Sitzung. Das

- hält **Kartendaten/PCI** komplett draußen,
- entwertet eine geklaute PIN (man kann nichts auslösen, was Geld bewegt),
- passt zum bestehenden Modell: Einkäufe laufen auf die **Monatsrechnung**
  (ADR 0016) und werden später beglichen – per Überweisung **oder** online über den
  **eigenen Magic-Link/das Normal-Login** zuhause (nicht am geteilten Gerät).

Das deckt sich exakt mit dem Vorschlag aus der Anfrage.

## 6. Wichtig: „einfach Bargeld" ist NICHT der einfache sichere Ausweg

Die Genossenschaft hat sich bewusst **gegen eine TSE/Kasse** entschieden, **weil es
keine Vor-Ort-Barzahlung gibt** (ADR 0040, KassenSichV/§146a AO). Eine **Bargeldkasse**
vor Ort würde genau diese **Kassen-/TSE-Pflicht** wieder aufwerfen (technische
Sicherheitseinrichtung, Belegausgabe, Kassenführung) – steuer-/kassenrechtlich der
**aufwendigere** Weg, nicht der einfachere. Der **rechnungsbasierte digitale Kiosk
ohne Bargeld** ist also nicht nur sicherer für die Daten, sondern auch **konsistent**
mit der bestehenden Entscheidung. (Keine Rechts-/Steuerberatung – vor Go-Live klären.)

## 7. Optionen zur Entscheidung

### Option A — **Empfohlen:** Kiosk-Modus mit PIN, reduzierte Sitzung, keine Zahlung
Eigener **Kiosk-Login** (Benutzername + 6-stellige PIN) auf dem provisionierten Gerät;
serverseitig **streng** auf Hofladen + eigene Monatsrechnung beschränkt; Anlage/Freigabe
über das Normal-System (QR). Die PIN ist eine **zusätzliche** Anmeldeart am bestehenden
(externen) Konto, kein zweites Konto.
- **Pro:** einfach vor Ort; minimaler Schadensradius; PCI-frei; konsistent mit ADR 0040;
  das vom Nutzer skizzierte Modell, sauber abgesichert.
- **Contra/Aufwand:** **mittel** – neues Sitzungs-/Rechte-Konzept (Middleware-Whitelist),
  PIN-Modell (Hash + Lockout), Kiosk-Login-Sicht + Geräte-Gating, Doku/Betriebs-Runbook
  fürs Gerät. Sicherheit hängt an **allen fünf Säulen** (auch Betrieb!).
- **Risiko bei sauberer Umsetzung:** gering und **begrenzbar** (reduzierte Rechte).

### Option B — Betreutes Anschreiben (Personal bedient, kein Gäste-Login)
Ein **Verwaltungs-/Hof-Konto** ist am Gerät angemeldet; eine helfende Person bucht die
Einkäufe der Gäste auf deren Namen (Auswahl aus freigegebenen Externen) → Monatsrechnung.
- **Pro:** **kein** Gäste-Login nötig → kein PIN-/Brute-Force-Thema; sehr einfach für
  die Gäste.
- **Contra:** braucht **Personalpräsenz**; das angemeldete Hof-Konto hat mehr Rechte
  (muss diszipliniert/aufsichtsbasiert bleiben); Selbstbedienung entfällt.
- **Aufwand:** **gering** (eine „auf fremden Namen anschreiben"-Funktion fürs Personal).

### Option C — Bargeldkasse vor Ort, kein digitaler Zugang
Externe zahlen **bar**; keine App vor Ort.
- **Pro:** **null** digitales Datenrisiko; kein App-Aufwand.
- **Contra:** **reaktiviert die Kassen-/TSE-Frage** (§ 6) – steuer-/kassenrechtlich
  aufwendig; Bargeld-Handling/Wechselgeld/Belege; bricht mit ADR 0040.
- **Aufwand:** App **null**, aber **rechtlich/operativ hoch**.

### Option D — Externe nutzen ihr Normal-Login am Kiosk (kein PIN)
Kein neues PIN-Konzept; Gäste tippen E-Mail + Passwort, Gerät erzwingt Reduktion.
- **Pro:** kein zusätzliches Credential.
- **Contra:** **Passwort auf geteiltem Gerät tippen** (Schulterblick auf das *richtige*
  Passwort!), umständlich für 60+ → genau die Friktion, die vermieden werden soll.
- **Bewertung:** schlechter als A (PIN ist gerätegeeigneter und „wegwerfbarer" als das
  Hauptpasswort).

## 8. Empfehlung

**Option A**, mit dem klaren Vorbehalt: Die Sicherheit ruht zu gleichen Teilen auf
**App** (reduzierte, serverseitig erzwungene Sitzung; PIN-Hash + Lockout; Geräte-Gating)
**und Betrieb** (gehärtetes Kiosk-Gerät, Netz, Sichtschutz). Fehlt eine Säule, ist es
nicht sicher – dann lieber **Option B** (betreut) als Zwischenschritt. **Option C**
(Bargeld) nur, wenn man die Kassen-/TSE-Folgen bewusst in Kauf nimmt.

Antwort auf die Leitfrage „gibt es überhaupt eine sichere, einfache Variante?": **Ja –**
PIN-Anmeldung an einem geteilten Terminal ist **sicher genug**, *sofern* die Sitzung
**wenig darf** und das **Gerät gehärtet** ist. Der Knackpunkt ist nicht die PIN, sondern
die **kompromisslose Reduktion der Rechte** und die **Gerätehärtung** – beides ist
machbar.

## 9. Offene Entscheidungen (für die Rückmeldung)

1. **Option A, B oder C** (oder A mit B als Übergang)?
2. Falls A: **PIN-Länge** (Empfehlung 6) und **Sperrschwelle** (Empfehlung 5/​Stunde)?
3. **Geräte-Gating**: Kiosk-Token **und/oder** IP-Allowlist? Wer provisioniert das Gerät?
4. **Rechnungsansicht am Kiosk**: nur Monats-Saldo, oder volle Rechnung hinter erneuter
   PIN-Eingabe? (Datensparsamkeit vs. Komfort)
5. Wer übernimmt die **Gerätehärtung** (OS-Kiosk-Mode, FDE, Netz) – und wird das als
   Betriebs-Runbook dokumentiert (Voraussetzung für A)?

---

### Quellen (Best-Practice-Recherche)

- [POS terminal security best practices – Computer Weekly](https://www.computerweekly.com/tip/POS-terminal-security-Best-practices-for-point-of-sale-environments)
- [Kiosk mode for compliance & data privacy – VantageMDM](https://www.vantagemdm.com/kiosk-app/kiosk-mode-for-compliance-and-data-privacy/)
- [Securing devices in kiosk mode – TECHOM Systems](https://www.techomsystems.com.au/how-to-secure-devices-in-kiosk-mode/)
- [PCI compliance for kiosk operators – Kiosk Marketplace](https://www.kioskmarketplace.com/articles/pci-compliance-essential-for-kiosk-operators/)
- [Kiosk security risks & testing checklist – AFINE](https://afine.com/blogs/kiosk-security-why-self-service-terminals-are-the-weakest-link-in-your-network)
- [PIN now required for Self-Checkout Kiosks – SFU Library](https://www.lib.sfu.ca/borrow/borrow-materials/pin-self-checkout)
- [Self-Check Kiosks in Libraries – LIS Education Network](https://www.lisedunetwork.com/self-check-kiosks-in-libraries-benefits-and-how-they-work/)
