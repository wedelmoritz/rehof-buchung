# 0028 – Rechnungs-PDF mit WeasyPrint (reine HTML-Erzeugung von der Ausgabe getrennt)

## Status

Accepted (2026-06-26)

## Kontext

Rechnungen müssen als **PDF** (§14-konform) vorliegen – herunterladbar und als
E-Mail-Anhang. PDF-Erzeugung bringt schwere native Abhängigkeiten mit; gleichzeitig
soll die Rechnungs-Darstellung testbar bleiben, ohne in jedem Test ein PDF zu rendern.

## Entscheidung

PDF-Erzeugung mit **WeasyPrint** aus HTML, mit klarer Trennung von Inhalt und Ausgabe
(`shop/pdf.py`):

- `invoice_context`/`invoice_html` erzeugen den **reinen** HTML-Inhalt
  (Druckvorlage `shop/templates/shop/invoice_pdf.html`) – ohne native Libs, gut
  testbar (`shop/tests.py:InvoicePdfTests`).
- `invoice_pdf_bytes` rendert daraus das PDF; `weasyprint_available` erlaubt
  Skip/Degradation, wenn die nativen Libs fehlen (Tests überspringen sauber).
- **Native Libs** (Pango/Cairo/GDK-Pixbuf, Schriften) stecken im `Dockerfile` und im
  CI-Job (`.github/workflows/tests.yml`) – auf dem Host ist nichts zu installieren.
- Auslieferung über `shop_invoice_pdf` (eigene Rechnung; Staff alle); das PDF hängt
  an der „Rechnung erstellt“-Mail (über `OutboxEmail`-Anhänge, ADR 0027).

## Betrachtete Alternativen

- **ReportLab (Low-Level-PDF):** volle Kontrolle, aber viel Layout-Code statt HTML/CSS.
- **Headless-Browser (wkhtmltopdf/Chromium):** schwerer/komplexer im Betrieb als
  WeasyPrint für einfache Rechnungslayouts.
- **HTML rendern und PDF nicht trennen:** Tests bräuchten überall die nativen Libs.

## Konsequenzen

**Positiv**
- Layout in HTML/CSS pflegbar; Inhaltserzeugung ohne native Libs testbar.
- PDF als Download **und** Mail-Anhang aus einer Quelle.

**Negativ**
- Native Abhängigkeiten vergrößern das Image; müssen in Docker **und** CI gepflegt
  werden.
- WeasyPrint deckt nicht jedes komplexe Druck-Layout ab (für Rechnungen ausreichend).
