"""The pitch deck at /deck: served, self-contained, and four minutes long."""

import re

from test_ui import client  # noqa: F401  (fixture)

from clayzer.ui.app import STATIC

DECK = STATIC / "deck"


def test_deck_is_served_with_its_modules(client):  # noqa: F811
    c, _ = client
    page = c.get("/deck")
    assert page.status_code == 200
    for src in re.findall(r'"(static/deck/[^"]+)"', page.text):
        assert c.get("/" + src).status_code == 200, src


def test_every_relative_import_resolves():
    for js in DECK.glob("*.js"):
        for target in re.findall(r'from "(\./[^"]+)"', js.read_text()):
            assert (DECK / target).is_file(), f"{js.name} imports {target}"


def test_no_network_dependencies():
    for f in [*DECK.glob("*.js"), *DECK.glob("*.css"), DECK / "index.html"]:
        assert not re.search(
            r"(src|href)=\"https?://|url\(\"?https?://|from \"https?://", f.read_text()
        ), f.name


def test_slide_budgets_add_up_to_four_minutes():
    seconds = [int(s) for s in re.findall(r"seconds: (\d+)", (DECK / "slides.js").read_text())]
    assert sum(seconds) == 4 * 60
