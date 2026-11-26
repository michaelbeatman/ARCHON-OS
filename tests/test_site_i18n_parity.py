"""Parität und Vollständigkeit der 11 Landingpage-Sprachversionen (GitHub Pages).

Prüft:
(a) alle Kataloge tragen dieselben Keys und keine leeren Werte,
(b) jeder Text ist lokalisiert (kein Wert gleicht noch der EN-Quelle),
(c) Screenshot-Captions und Alt-Texte sind in allen Sprachen übersetzt,
(d) keine englischen Fließtexte aus der EN-Quelle tauchen in einer Übersetzung auf,
(e) die eingecheckten Seiten stimmen mit Template + Katalogen überein,
(f) HTML-Metadaten pro Sprache: lang, canonical, hreflang, Asset-Basis, selected.

Hintergrund: Die Sprachseiten waren früher 1:1-Kopien der EN-Seite, bei denen nur
Header und Hero übersetzt waren. Screenshots und Funktionsbeschreibungen blieben EN.
"""
from __future__ import annotations

import html
import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "build_site_i18n.py"

spec = importlib.util.spec_from_file_location("build_site_i18n", GENERATOR)
assert spec and spec.loader
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

TAG_RE = re.compile(r"<[^>]+>")
SHOT_KEYS = tuple(k for k in build.load_catalogs()["en"] if k.startswith("shots.") and k != "shots.title")


Ctx = tuple[str, dict[str, dict[str, str]], dict[str, str]]


@pytest.fixture(scope="module")
def ctx() -> Ctx:
    template = build.TEMPLATE.read_text(encoding="utf-8")
    catalogs = build.load_catalogs()
    rendered = {lang: build.render(template, lang, catalogs[lang]) for lang in build.LANGS}
    return template, catalogs, rendered


def plain(text: str) -> str:
    return html.unescape(TAG_RE.sub("", text)).strip()


def test_catalogs_have_identical_keys(ctx: Ctx) -> None:
    _, catalogs, _ = ctx
    reference = set(catalogs["en"])
    assert reference, "EN-Katalog ist leer"
    for lang, cat in catalogs.items():
        assert set(cat) == reference, f"{lang}: Keys weichen von EN ab"


def test_no_empty_catalog_values(ctx: Ctx) -> None:
    _, catalogs, _ = ctx
    for lang, cat in catalogs.items():
        for key, value in cat.items():
            assert isinstance(value, str) and value.strip(), f"{lang}:{key} ist leer"


def test_generator_validation_is_clean(ctx: Ctx) -> None:
    template, catalogs, _ = ctx
    assert build.validate(template, catalogs) == []


def test_every_string_is_localized(ctx: Ctx) -> None:
    """Der ursprüngliche Bug: ~90 % der Texte waren noch identisch mit EN."""
    _, catalogs, _ = ctx
    en = catalogs["en"]
    leftovers = [
        f"{lang}:{key}"
        for lang, cat in catalogs.items()
        if lang != "en"
        for key, value in cat.items()
        if value == en[key]
    ]
    assert not leftovers, f"Nicht übersetzte Strings: {leftovers}"


def test_screenshot_captions_and_alts_are_localized(ctx: Ctx) -> None:
    """Regressionstest für die gemeldeten englischen Screenshots."""
    _, catalogs, _ = ctx
    en = catalogs["en"]
    assert len(SHOT_KEYS) == 12, "Erwartet: 6 Alt-Texte + 6 Captions"
    for lang, cat in catalogs.items():
        if lang == "en":
            continue
        for key in SHOT_KEYS:
            assert cat[key] != en[key], f"{lang}:{key} (Screenshot) ist noch englisch"


def test_no_english_prose_leaks_into_translated_pages(ctx: Ctx) -> None:
    _, catalogs, rendered = ctx
    english_prose = {
        key: plain(value)
        for key, value in catalogs["en"].items()
        if len(plain(value)) >= 40 and " " in plain(value)
    }
    assert english_prose, "Keine EN-Fließtexte zum Prüfen gefunden"
    for lang, page in rendered.items():
        if lang == "en":
            continue
        for key, text in english_prose.items():
            assert text not in page, f"{lang}: EN-Fließtext von {key} ist noch enthalten"


def test_generated_pages_are_current(ctx: Ctx) -> None:
    _, _, rendered = ctx
    for lang, expected in rendered.items():
        path = build.output_path(lang)
        assert path.is_file(), f"{path} fehlt"
        assert path.read_text(encoding="utf-8") == expected, (
            f"{lang}: Seite ist veraltet - python scripts/build_site_i18n.py ausführen"
        )


def test_no_unresolved_placeholders(ctx: Ctx) -> None:
    _, _, rendered = ctx
    for lang, page in rendered.items():
        # Nicht auf "}}" prüfen: CSS enthält legitime geschachtelte Regelenden.
        assert not build.PLACEHOLDER_RE.search(page), f"{lang}: Platzhalter übrig"


def test_html_metadata_per_language(ctx: Ctx) -> None:
    _, _, rendered = ctx
    for lang, page in rendered.items():
        html_lang, label = build.LANGS[lang]
        assert f'<html lang="{html_lang}">' in page, f"{lang}: falsches lang-Attribut"
        assert f'<link rel="canonical" href="{build.canonical(lang)}">' in page, (
            f"{lang}: falsche canonical-URL"
        )
        assert page.count('rel="alternate" hreflang=') == len(build.LANGS) + 1, (
            f"{lang}: hreflang-Tags fehlen"
        )
        assert page.count(" selected>") == 1, f"{lang}: Sprachumschalter ohne Auswahl"
        assert f">{label}</option>" in page, f"{lang}: Eigenes Label fehlt im Umschalter"
        asset = "archon_hand.png"
        expected = f'src="{asset}"' if lang == "en" else f'src="../{asset}"'
        assert expected in page, f"{lang}: Asset-Basis stimmt nicht"
