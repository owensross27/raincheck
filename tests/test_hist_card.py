"""frontend 07: the history layer and the record card, read as data.

The page has no JS runner (spec L), so these are text assertions over the `site` family
through tests/page.py - the page-as-data seam, extended and not forked. The data contract
under them is notify 05's landed surface (RUN-LOG-ARCHIVE, 2026-08-26, `e86cacb`):
a six-key manifest at files/history/manifest.geojson, per-asset files/history/<id>.json
with the id VERBATIM, `name` ABSENT on every Cell, and 928 entrance files with NO
`exposure` key at all.
"""
import re

from page import layer_entries, module_js, page_css, page_html, page_js


# -------------------------------------------------------- the network discipline IS the rule
def test_the_hist_entry_fetches_the_manifest_alone_and_only_on_toggle():
    """The boot-vs-toggle decision, pinned: the manifest is 1,458,148 B RAW (nothing on
    this host compresses) and ~40% of the current first paint, so it loads on the FIRST
    TICK and never at boot - which is `open: false` plus the chassis's own
    nothing-is-fetched-until-you-tick-it rule. Its payload landed (notify 05), so the row
    owes nobody; no budget is frozen for it anywhere in the repo, so its row reads a bare
    AGE rather than a guessed verdict.
    MUTATION KILLED: `open: true` (a 1.5 MB boot cost nobody decided), a second `srcs`
    entry (a per-asset fetch before any click), or a guessed budget."""
    e = layer_entries(page_js())["hist"]
    assert e.count("k: ") == 1, "the hist layer fetches ONE file: the manifest"
    assert 'k: "files/history/manifest.geojson"' in e
    assert "open: false" in e
    assert "owed: null" in e
    assert "budget: null" in e


def test_the_record_fetch_exists_only_in_the_card_and_only_a_click_reaches_it():
    """No per-asset fetch happens before a click. The per-asset URL is built in exactly
    one place - the card - from the manifest's own `asset_id`, VERBATIM (flat tree, no
    shards, no encoding: the registry charset is [A-Za-z0-9:._-], measured over all
    20,544 ids). The wiring is a CLICK on the hist layer, in app.js like all wiring, and
    never a hover: hover would fire thousands of fetches panning across 8,146 markers,
    and a touch screen has no hover at all.
    MUTATION KILLED: fetching the record from a hover handler, deriving the URL from the
    NAME (not unique at any grain), or fetching detail at draw time."""
    mods = module_js()
    url = '"files/history/" + p.asset_id + ".json"'
    assert url in mods["insight.js"]
    for name, js in mods.items():
        if name != "insight.js":
            assert '"files/history/" +' not in js, f"{name} builds a per-asset URL"
    assert '"files/history/" + p.name' not in page_js(), "a URL is derived from the id, never the name"
    app = mods["app.js"]
    assert 'map.on("click", "hist"' in app
    assert 'map.on("mousemove", "hist"' not in app
    assert 'map.on("mouseenter", "hist"' not in app


# ------------------------------------------------------------------ what the card must say
def test_the_title_falls_back_to_the_id_and_the_id_prints_even_when_named():
    """`name` is an ABSENT key on all 1,276 Cells (undefined, never null, never the word)
    - and the most-flooded assets are exactly the Cells, so a name-keyed title puts the
    literal word "null" at the TOP of the ranking. `||` covers undefined AND null. And the
    id line prints UNCONDITIONALLY even when a name exists: "86 St" names SIX complexes,
    and bus:200163/bus:200173 are one name, 26 events each, metres apart - a click between
    them is ambiguous and only the id resolves it. Both strings are set as textContent:
    the name originates in the GTFS registry, a trust boundary.
    MUTATION KILLED: `p.name` alone in the title (the "null"/undefined title), or
    dropping the id line for named assets."""
    ins = module_js()["insight.js"]
    assert "h.textContent = p.name || p.asset_id" in ins
    assert '$("card-id").textContent = `${p.kind} · ${p.asset_id}`' in ins


def test_an_absent_exposure_key_is_a_sentence_never_a_zero_and_the_ask_is_offered():
    """928 of the 8,146 files - every entrance - have NO `exposure` key AT ALL. There is
    no null and no zero to check, because a fabricated 0.0 would read as "safe"; the
    branch therefore tests the KEY's presence, renders the honest sentence, and offers
    `exposure_unavailable.ask` - the complex that DOES answer.
    MUTATION KILLED: defaulting the score (`|| 0` / `?? 0`), or a blank block."""
    ins = module_js()["insight.js"]
    assert "doc.exposure === undefined" in ins, "the branch tests the KEY, not a value"
    assert "No flood-exposure score for this asset kind" in ins
    assert ".ask" in ins
    assert "score_index || 0" not in ins and "score_index ?? 0" not in ins


def test_the_score_wording_is_the_rank_and_never_the_linear_predictor():
    """`score_index` is the within-kind RANK bounded (0, 1] - the one human-facing number
    - rendered beside the payload's own `estimand` sentence verbatim (never re-worded
    here). The two linear-predictor numbers are negative for nearly every Unit and are
    NOT probabilities, so the card does not render them at all. `modelled: false` marks
    the 60 kind-median stops and may never read as a modelled rank; an absent
    `surge_margin_ft` is NOT a zero (zero means water AT the doorway), so it renders only
    behind a presence check. Flag meanings are linked, not re-worded.
    MUTATION KILLED: rendering score_ref/score_severe (no honest one-line gloss exists),
    calling a kind-median row a modelled rank, or defaulting the surge margin."""
    js = page_js()
    ins = module_js()["insight.js"]
    assert "rank within its kind, in (0, 1]" in ins
    assert "esc(e.estimand" in ins, "the estimand is the payload's sentence, verbatim"
    assert "score_ref" not in js and "score_severe" not in js
    assert "e.modelled === false" in ins and "kind-median" in ins
    assert "e.surge_margin_ft !== undefined" in ins
    assert "surge_margin_ft || " not in js and "surge_margin_ft ?? " not in js
    assert "research/flood-10-coefficients.json" in ins


def test_the_events_are_newest_first_and_the_event_grain_caveat_prints():
    """The seam orders events oldest-first (byte-identity needs an ordered aggregate);
    the card is about "what happened here lately", so it reverses to newest-first and
    caps the list rather than burying the panel under 73 rows. The counts caveat is
    load-bearing: `event_source_counts` is city-wide at EVENT grain (gold/flood_labels
    stores no per-source counts per asset - TRAPS), so the card says what the numbers
    are about instead of implying "N reports at THIS stop".
    MUTATION KILLED: oldest-first (the newest flood is what a click asks about), or
    dropping the caveat so the counts read as per-asset."""
    ins = module_js()["insight.js"]
    assert "(doc.events || []).slice().reverse()" in ins
    assert "event_source_counts" in ins
    assert "city-wide at EVENT grain" in ins
    assert "label_version" in ins, "the card states the label version it renders under"


def test_the_record_is_dated_reader_side_through_the_same_seam_as_every_payload():
    """The click's payload carries NO wall clock by design (a writer stamp would break
    notify 05's byte-identity and would date the WRITE, not the newest input). The card
    therefore dates the record the way the page dates everything: through grab(), off the
    response's own Date - Last-Modified headers, and says so on the card.
    MUTATION KILLED: a bare fetch() that reads no headers, or `Date.now()` arithmetic
    against a payload field."""
    ins = module_js()["insight.js"]
    assert 'await grab("hist", src)' in ins
    assert 'ages["hist/" + src.k]' in ins
    assert "Date.now()" not in ins
    assert "record age unknown" in ins, "an unknown age is said, never rendered fresh"


# ------------------------------------------------------------------- layout and keyboard
def test_the_card_is_in_column_hidden_until_a_click_and_never_floating():
    """The card SHARES the right column with the layer panel - a flex sibling inside
    #right that shrinks and scrolls, never floats, so it cannot cover the freshness rows
    or the provenance strip at any width (the real-tab hit test is the other half of this
    claim). It boots hidden: there is no card before a click.
    MUTATION KILLED: position fixed/absolute (a floating card over the rows), or a card
    that is visible at boot."""
    html = page_html()
    assert '<section id="card" class="panel" hidden' in html
    # frontend3 02 merged the live panel INTO the layers card (wave-11 spec sec. 2.4), so
    # the column order is now layers (live row group inside it) -> card: the card is still
    # a flex sibling of #layers inside #right, stacking after it at 375.
    assert html.index('id="right"') < html.index('id="live"') < html.index('id="card"')
    block = re.search(r"#card \{([^}]*)\}", page_css()).group(1)
    assert "fixed" not in block and "absolute" not in block
    assert "relative" in block, "relative only anchors the close button - it stays in flow"
    # the small-screen block lays the card out like its column siblings (#live is inside
    # #layers now and needs no rule of its own; the legend joined the list instead)
    assert re.search(r"#insight, #layers, #card, #legend", page_css())


def test_the_card_is_keyboard_reachable_and_close_returns_focus_to_the_toggle_row():
    """Click, not hover, opens it; opening moves focus to the card's own heading
    (tabindex=-1, the dialog pattern), Escape and a real <button> close it, and close
    returns focus to the hist layer's toggle row - not to <body>, which would make a
    keyboard reader re-tab through the whole page (the same restore renderLayers and
    setHour already do).
    MUTATION KILLED: focus falling to <body> on close, or a close only a mouse can
    reach."""
    html, ins = page_html(), module_js()["insight.js"]
    app = module_js()["app.js"]
    assert '<h2 id="card-h" tabindex="-1">' in html
    assert "h.focus()" in ins
    assert '<button id="card-close" type="button"' in html
    assert '$("card-close").addEventListener("click", closeCard)' in app
    assert '"Escape"' in app and "closeCard()" in app
    assert '\'#layers [data-l="hist"]\'' in ins, "close returns focus to the hist toggle row"


def test_the_panel_states_the_sizes_and_the_boot_vs_toggle_decision_before_the_tick():
    """The two sizes are 66x apart and only one is a boot cost - so the decision (first
    tick, never boot) and both numbers are stated before a reader ticks anything, in RAW
    bytes. frontend3 02 moved the statement from a page-level paragraph into the hist
    ROW's own detail (`det:` on its LAYERS entry, rendered by rowHTML) - one tap away at
    the point of the tick, instead of a warning about a layer the reader may never touch.
    MUTATION KILLED: a silent 1.5 MB tick (deleting the det note), losing the never-at-
    boot decision, or dropping the per-click ceiling."""
    e = layer_entries(page_js())["hist"]
    assert "8,146 assets" in e and "1.5 MB" in e
    assert "once when first ticked" in e and "never at boot" in e
    assert "22 KB" in e
    row = page_js().split("function rowHTML", 1)[1].split("\n}", 1)[0]
    assert "lyr.det" in row, "the det note is dead data unless rowHTML renders it"
