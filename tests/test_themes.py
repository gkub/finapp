from finance_tracker.ui.themes import PALETTES, stylesheet


def _luminance(hex_color):
    values = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first, second):
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_theme_text_and_primary_buttons_have_accessible_contrast():
    for name, palette in PALETTES.items():
        assert _contrast(palette["text"], palette["background"]) >= 7, name
        assert _contrast(palette["muted"], palette["background"]) >= 4.5, name
        assert _contrast(palette["primary_text"], palette["primary"]) >= 4.5, name
        assert palette["text"] in stylesheet(name)
        assert "QFrame#metricGroup" in stylesheet(name)
        assert "QFrame#metricTile" in stylesheet(name)
        assert "QLabel { background:transparent; }" in stylesheet(name)


def test_pink_theme_is_pastel_not_hot_pink():
    pink = PALETTES["pink"]
    assert pink["background"] == "#fff7fb"
    assert pink["primary"] != "#ff00ff"
