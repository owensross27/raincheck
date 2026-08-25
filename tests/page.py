"""The page, read as DATA - and the ONE place a test learns which files ARE the page.

The page has no JS test runner (spec L: no npm, no build step), so every page rule in this
repo is a text assertion over `web/`. frontend2 01 split one 781-line `app.js` into six ES
modules, which turns "read web/app.js" into a question with a wrong answer: a hand-written
list of module names here would go stale the first time a ticket adds one, and every rule
below it would silently stop covering the new file.

So `page_js()` DERIVES the list from `publish.FAMILIES["site"]` - the same table the
publisher uploads from - in publish order. A module that is not a `site` key is not
published, and a module that IS one is automatically under every rule in
tests/test_page.py. This is the repo's standing derive-in-test rule (TRAPS: "a page
constant that mirrors a Python constant will drift"), applied to the file list itself.

Import it as `page`, never `tests.page`: pytest's prepend import mode puts `tests/` on
sys.path (there is no `tests/__init__.py`), so the bare name resolves under every
invocation - `pytest tests/test_page.py`, `make test`, a single `-k` run. `tests.page`
resolves only when the repo root happens to be sys.path[0], which `python -m pytest` from
the root gives you and a bare `pytest` does not.

The one exclusion is `vendor/` and it is not a taste call: the vendored MapLibre bundle is
a `site` `.js` key, it is written by `make vendor` and is absent from a fresh worktree
(gitignored), and it contains `addLayer(` - so concatenating it would both crash the read
and turn `test_all_twelve_layers_are_declared_at_boot_in_the_frozen_order` red on
MapLibre's own source. The page's code is the site `.js` keys that are not vendored.
"""
import re
from pathlib import Path

from raincheck import publish

# frontend 02 D3, verbatim: ambient at the bottom, urgent on top.
SPEC_ORDER = ["bg", "zones-fill", "cells", "impact-fill", "cells-line", "impact-line",
              "zones-line", "locate", "live", "hist", "fn", "mta"]


def web() -> Path:
    """`web/`, from the family's own `src` callable rather than a second path constant."""
    return publish.FAMILIES["site"].src()


def page_files() -> list[str]:
    """Every `.js` key the `site` family publishes, IN PUBLISH ORDER, minus the vendored
    bundle (see the module docstring). These are the files that make up the page."""
    return [k for k in publish.FAMILIES["site"].files
            if k.endswith(".js") and not k.startswith("vendor/")]


def page_js() -> str:
    """The whole page as one text: every module, concatenated in publish order."""
    root = web()
    return "\n".join((root / k).read_text() for k in page_files())


def module_js() -> dict[str, str]:
    """The same files, one text each - for the rules that are about WHICH module a thing
    is in (the load-order rule) rather than about the page as a whole."""
    root = web()
    return {k: (root / k).read_text() for k in page_files()}


def page_html() -> str:
    return (web() / "index.html").read_text()


def page_css() -> str:
    return (web() / "app.css").read_text()


def style_layers(js: str) -> list[str]:
    """The layer ids the map style declares, in declaration order."""
    block = js.split("layers: [", 1)[1].split("\n    ],", 1)[0]
    return re.findall(r'\{ id: "([a-z-]+)"', block)


def layer_entries(js: str) -> dict[str, str]:
    """The LAYERS table, one source-text entry per layer id."""
    block = js.split("const LAYERS = [", 1)[1].split("\n];", 1)[0]
    out = {}
    for entry in block.split("\n\n"):
        m = re.search(r'\{ id: "(\w+)"', entry)
        if m:
            out[m.group(1)] = entry
    return out


def budgets(entry: str) -> list[str]:
    return [b.strip() for b in re.findall(r"budget: ([^,}\n]+)", entry)]
