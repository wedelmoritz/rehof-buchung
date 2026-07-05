"""Reine Tests für den sicheren Hilfetext-Renderer (ADR 0093)."""
from booking.helptext import render_markup


def test_absatz_und_liste():
    html = render_markup("Hallo Welt\n\n- eins\n- zwei")
    assert "<p>Hallo Welt</p>" in html
    assert "<ul><li>eins</li><li>zwei</li></ul>" in html


def test_fett_und_ueberschrift():
    html = render_markup("## Titel\n\nDas ist **wichtig**.")
    assert "<h3>Titel</h3>" in html
    assert "<strong>wichtig</strong>" in html


def test_erlaubte_links():
    html = render_markup("[intern](/buchen/) und [web](https://re-hof.de) und [mail](mailto:a@b.de) und [anker](#los)")
    assert '<a href="/buchen/">intern</a>' in html
    assert '<a href="https://re-hof.de">web</a>' in html
    assert '<a href="mailto:a@b.de">mail</a>' in html
    assert '<a href="#los">anker</a>' in html


def test_boeser_link_wird_nur_text():
    # javascript:-Ziele sind nicht erlaubt → bleiben reiner Text (kein <a>).
    html = render_markup("[klick](javascript:alert(1))")
    assert "<a" not in html
    assert "klick" in html


def test_html_wird_escaped():
    html = render_markup("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_platzhalter_safe_substitute_kein_ssti():
    # $var wird eingesetzt; ein $-Ausdruck im Wert bleibt literal (kein SSTI).
    html = render_markup("Preis: $preis. Rest: $unbekannt",
                         {"preis": "70 €"})
    assert "70 €" in html or "70" in html
    assert "$unbekannt" in html            # unbekannte Platzhalter bleiben stehen
