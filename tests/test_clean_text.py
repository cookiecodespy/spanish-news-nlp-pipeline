from src.clean_text import dedupe, dedupe_key, normalize_title


def test_normalize_strips_trailing_outlet():
    assert (
        normalize_title("Gobierno anuncia nueva política - La Tercera")
        == "Gobierno anuncia nueva política"
    )


def test_normalize_keeps_internal_score_hyphens():
    assert normalize_title("Chile vence 2-1 a Perú - Cooperativa") == "Chile vence 2-1 a Perú"


def test_normalize_collapses_whitespace():
    assert normalize_title("  Doble   espacio\tcon tab ") == "Doble espacio con tab"


def test_dedupe_key_ignores_case_and_accents():
    assert dedupe_key("Economía CHILENA") == dedupe_key("economia chilena")


def test_dedupe_keeps_first_occurrence():
    records = [
        {"title": "Economía chilena crece", "label": "economia"},
        {"title": "ECONOMIA CHILENA CRECE", "label": "economia"},
        {"title": "Otro titular distinto", "label": "nacional"},
    ]
    assert len(dedupe(records)) == 2
