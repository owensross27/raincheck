"""The page's rules, read as DATA - tickets 13 and 14's panel wiring, and frontend 05's
seven-layer chassis. Split out of tests/test_live.py by frontend2 01, which also split the
page itself; every assertion below is the one that was there, over a page that is now six
ES modules instead of one file.

There is no JS test runner (spec L: no npm, no build step), so these read the page as DATA
- its layer declarations, its rules, its gate keys, its budgets - and several of them
derive the expected value from the PYTHON side (publish.LIVE_TERMS_VERIFIED,
flood_truth.MAX_AGE_MIN) so that the page and the pipeline cannot drift apart silently.
Every frontend 05 test names, in its docstring, the mutation it kills; all of those
mutations were applied and observed RED before that file was committed.

**WHICH files are the page is itself derived** - `tests/page.py` reads the `site` family's
`.js` keys out of `publish.FAMILIES`, in publish order, so a module a later ticket adds is
under every rule here the moment it is publishable, and a hand list cannot go stale. These
tests catch a deleted rule, not a broken one; the rendering itself is checked by hand in a
VISIBLE tab (MapLibre throttles rAF when hidden, so a headless screenshot is misleading).
"""
import re

from raincheck import contract, flood_truth, publish
# `page`, not `tests.page`: pytest's prepend import mode puts THIS directory on sys.path
# (there is no tests/__init__.py), so the bare name resolves under `pytest tests/...` as
# well as under `make test`. `tests.page` resolves only when the repo root happens to be
# sys.path[0], which is true of `python -m pytest` from the root and of nothing else.
from page import (SPEC_ORDER, budgets, layer_entries, module_js, page_css,
                  page_files, page_html, page_js, style_layers, web)


# ---------------------------------------------------------- the split itself, frontend2 01
def test_every_page_module_is_a_site_family_key_and_nothing_hides_from_these_tests():
    """The page is six ES modules now, and the ONLY thing that puts a module under the
    rules below is being a `site` family key - which is also the only thing that publishes
    it. So the two sets must be equal in both directions: a `.js` file in web/ that the
    family does not name is a file no test reads and no host serves, and a key with no file
    behind it refuses the whole family at publish time.
    MUTATION KILLED: adding a seventh module without adding its key - the page would still
    work locally and every rule here would silently stop covering it."""
    on_disk = {p.name for p in web().glob("*.js")}
    assert on_disk == set(page_files()), "web/*.js and the site family disagree"
    assert page_files()[-1] == "app.js", "the entry module is published last, as it loads"
    assert all((web() / k).is_file() for k in page_files())


def test_the_page_is_one_module_entry_with_no_build_step():
    """ES modules, no bundler, no npm (spec L). index.html carries exactly ONE script tag
    for the page's own code - `type="module"`, app.js - and the vendored MapLibre UMD stays
    a CLASSIC tag, because that is what puts `maplibregl` on window for every module to use.
    MUTATION KILLED: adding a second entry (which evaluates the graph twice), dropping
    `type="module"` (every `import` becomes a syntax error), or making the vendored bundle a
    module (`maplibregl` stops being a global and the map never constructs)."""
    html = page_html()
    assert '<script type="module" src="app.js"></script>' in html
    assert '<script src="vendor/maplibre-gl.js"></script>' in html
    assert html.count("<script") == 2, "one entry module plus the vendored UMD, nothing else"
    for mod in page_files():
        if mod != "app.js":
            assert f'src="{mod}"' not in html, f"{mod} is imported, never tagged"
    for js in module_js().values():                     # no bundler, no loader shim
        assert "require(" not in js and "module.exports" not in js


def test_only_the_boot_module_wires_the_dom_and_the_map():
    """THE load-order rule, and it is not style. The module graph is CYCLIC by construction
    (layers.js needs drawCells inside a LAYERS.draw closure; freshness.js needs liveMeta
    inside srcState), so the bodies evaluate in an order nobody would guess - measured under
    node 25: panel, live, freshness, insight, layers, app. layers.js, which every other
    module reads, evaluates almost LAST. A cycle is safe exactly while no module BODY reads
    another module's binding, which is why every addEventListener, every map.on / map.once
    and both ResizeObservers live in app.js and nowhere else.
    MUTATION KILLED: moving a wiring line back beside the code it drives - the page then
    throws a TDZ ReferenceError at load and the map never paints, which no text assertion
    about layers or freshness would have noticed."""
    wiring = ("addEventListener(", "map.on(", "map.once(", "ResizeObserver")
    for name, js in module_js().items():
        if name == "app.js":
            continue
        for w in wiring:
            assert w not in js, f"{name} wires {w} - it must move to app.js (see its header)"
    boot = module_js()["app.js"]
    for w in wiring:
        assert w in boot, w
    # and the two cross-module writes go through a function, because an imported binding is
    # read-only in the importing module
    assert "export const markStyled" in module_js()["layers.js"]
    assert "export function toggleLive" in module_js()["live.js"]


def test_splitting_the_page_added_keys_and_did_not_move_the_contract_integer():
    """Adding a key is ADDITIVE under `contract.PROMISE[1]` - the frozen promise stays a
    SUBSET of what the publisher renders - so the five new module keys demand no bump and
    tests/test_publish.py's contract test stays green. That asymmetry is the whole design:
    a digest over the surface would have bumped here for a change no consumer can see.
    MUTATION KILLED: renaming or dropping `app.js` (a PROMISED key) while splitting - that
    is a breaking change and this stops being additive."""
    promised = {k for _, k, _ in contract.PROMISE[1]}
    added = set(page_files()) - promised
    assert added == {"layers.js", "freshness.js", "panel.js", "insight.js", "live.js"}
    assert "app.js" in promised, "app.js was promised at contract 1 and must keep its name"
    assert contract.CONTRACT == 1, "an additive change may not bump the contract integer"
    assert not (contract.PROMISE[contract.CONTRACT] - contract.surface())


# ------------------------------------------------------------- the panel's contract in JS
# The page has no JS test runner (spec L: no npm, no build step), so these are text
# assertions on the wiring ticket 13 handed over. They catch a deleted rule, not a broken
# one; the rendering itself is checked by hand in a VISIBLE tab (MapLibre throttles rAF
# when hidden, so a headless screenshot is misleading).
def test_the_page_wires_the_live_panel_ids_ticket_13_stubbed():
    js = page_js()
    html = page_html()
    for el in ("livemeta", "delaystate", "rainstate", "livetoggle"):
        assert f'id="{el}"' in html, el
        assert f'"{el}"' in js, el
    assert 'getSource("live").setData' in js
    # vehicle_id is "MTA NYCT_1234": MapLibre 5.9.0 silently drops a source whose promoted
    # id is not integer-like, so no source may carry an actual promoteId assignment
    assert 'promoteId: "' not in js and "promoteId:'" not in js


def test_the_page_keeps_both_stale_thresholds_and_only_setdata_on_a_clean_tick():
    js = page_js()
    assert "live: 120" in js and "bronze: 900" in js   # spec L's two STALE cuts
    assert "cache: \"no-store\"" in js                 # a cached meta.json is a lie
    assert "STALE: the pipeline is not writing" in js
    # the delay wording is gated and never says "late"
    assert "over 5 min (agency-computed, unvalidated)" in js
    body = js.split("MTA-reported trip delay")[1]
    assert " late" not in body.lower().split("function liveTick")[0]


def test_the_toggle_waits_for_maplibre_to_parse_the_style():
    """Every branch of the toggle handler touches the `live` layer, and MapLibre throws on
    setPaintProperty / getSource for a layer the style has not parsed yet. Measured in a
    real tab: clicking the box the instant the page loaded killed the tick silently and
    left the panel reading "off" under a ticked box - the exact failure the panel exists to
    prevent. The box therefore ships disabled and app.js enables it on `load` - NOT on
    `styledata`, which fires while isStyleLoaded() is still false."""
    html = page_html()
    js = page_js()
    assert 'id="livetoggle" disabled' in html
    gate = js.split("$(\"livetoggle\").addEventListener")[0]
    assert 'map.once("load"' in gate and '$("livetoggle").disabled = false' in gate
    assert 'map.once("styledata", () => { $("livetoggle")' not in js


def test_the_rain_legend_names_the_uncalibrated_source_and_its_valid_stamp():
    html = page_html()
    assert "MRMS RadarOnly QPE 01H, uncalibrated, hour-ending," in html
    assert 'id="rainstate"' in html
    assert "valid ${m.precip_valid_ts}" in page_js()
# ------------------------------------------------------------------ rule 1: declare at boot
def test_all_twelve_layers_are_declared_at_boot_in_the_frozen_order():
    """A lazily added layer lands on TOP of the order, so with anything lazy the stacking
    depends on CLICK order, and a `beforeId` naming a not-yet-added layer throws outright.
    MUTATION KILLED: moving any layer in the style block, dropping one, or adding one
    through a later addLayer() instead of declaring it here."""
    assert style_layers(page_js()) == SPEC_ORDER
    assert "addLayer(" not in page_js(), "a lazily added layer lands on top of the order"
    assert "addSource(" not in page_js()


def test_every_source_boots_empty_and_every_data_layer_boots_hidden():
    """An empty FeatureCollection at boot is what lets `cells` and the six not-yet-lit
    layers exist before their payload does; `visibility: "none"` is what stops them
    painting before the reader asks. MUTATION KILLED: booting a source straight off its
    URL again (which also re-creates the double fetch/parse of the 2.3 MB cells.geojson),
    or shipping a layer visible."""
    js = page_js()
    sources = js.split("sources: {", 1)[1].split("},", 1)[0]
    names = re.findall(r"(\w+): empty\(\)", sources)
    assert sorted(names) == ["cells", "fn", "hist", "impact", "live", "locate", "mta", "zones"]
    assert "empty = () => ({ type: \"geojson\", data: { type: \"FeatureCollection\", features: [] } })" in js
    assert 'data: "files/' not in sources, "a source booting off a URL cannot report its age"

    block = js.split("layers: [", 1)[1].split("\n    ],", 1)[0]
    for entry in re.split(r"\n      (?=\{ id: )", block):
        lid = re.search(r'\{ id: "([a-z-]+)"', entry)
        if not lid or lid.group(1) == "bg":     # `bg` is the background paint, not a source
            continue
        assert 'layout: { visibility: "none" }' in entry, lid.group(1)


# ------------------------------------------------- rule 4: the exclusive Cell fill channel
def test_the_cell_fill_is_a_radio_and_delay_cells_is_its_only_lit_option():
    """The delay layer and flood 17's impact overlay are the same quantity over the same
    Cells at two time-scales, so they share one channel. Exactly two layers claim it, the
    control is a RADIO in one named group, and the second option is dark until ticket 08
    lights the vehicle gate side. MUTATION KILLED: rendering the fill rows as checkboxes,
    dropping the group name (which makes two radios independently checkable), or marking
    a third layer `fill: true`."""
    js = page_js()
    entries = layer_entries(js)
    fills = [lid for lid, e in entries.items() if "fill: true" in e]
    assert fills == ["cells", "impact"]
    assert "impact" in entries and 'gate: "mta-vehicles"' in entries["impact"]
    row = js.split("function rowHTML", 1)[1].split("\n}", 1)[0]
    assert 'const kind = lyr.fill ? "radio" : "checkbox";' in row
    assert '\'name="cellfill"\'' in row
    assert "role=\"radiogroup\"" in page_html()


def test_two_cell_fills_can_never_be_held_at_once():
    """The radio group makes two fills unaskable in the markup; this makes them unholdable
    in the state, however the toggle was reached (a restored URL, a later slice calling
    toggle() directly). MUTATION KILLED: deleting the clear-the-others line from toggle(),
    or defaulting a second fill layer on."""
    js = page_js()
    body = js.split("async function toggle(id, want)", 1)[1].split("\n}", 1)[0]
    assert ("if (want && lyr.fill) for (const o of LAYERS) if (o.fill && o.id !== id) "
            "on[o.id] = false;") in body
    lit = [lid for lid, e in layer_entries(js).items()
           if "fill: true" in e and "open: true" in e]
    assert lit == ["cells"], "exactly one fill option opens lit"


# ------------------------------------------------------- the five states, and their order
def test_the_freshness_vocabulary_is_five_states_in_a_fixed_precedence():
    """FRESH / STALE(+reason) / OFF / GATED / AGE, one row per SOURCE. The ORDER is the
    contract: a gated layer reads GATED before it can read OFF, an unfetched one reads OFF
    before it can read STALE, and a source with no age reads STALE before any budget
    comparison - absent must never render as fresh-and-empty. MUTATION KILLED: dropping a
    state, reordering the branches (e.g. testing `on[]` before the gate, which would make a
    gated layer read OFF and lose the explanation), or letting a missing age fall through
    to FRESH."""
    body = page_js().split("function srcState(lyr, s)", 1)[1].split("\n}", 1)[0]
    order = [m for m in re.findall(r's: "(FRESH|STALE|OFF|GATED|AGE)"', body)]
    assert order == ["GATED", "OFF", "STALE", "AGE", "FRESH", "STALE"]
    assert "if (shut(lyr))" in body
    assert "if (!on[lyr.id])" in body
    assert "if (age === null || age === undefined)" in body
    assert "if (s.budget === null)" in body
    assert "age <= s.budget" in body
    # a layer is only as fresh as its worst source, and the worst-first order matches
    worst = page_js().split("const worst = (lyr)", 1)[1].split("};", 1)[0]
    assert '["GATED", "STALE", "OFF", "AGE", "FRESH"]' in worst


def test_only_a_source_with_a_frozen_budget_may_render_a_verdict():
    """frontend 02 D6, re-derived here rather than restated: of the nine sources the page
    reads, exactly THREE have a staleness budget frozen anywhere in the repo - the live
    pair (STALE_AFTER_S.live) and FloodNet (flood_truth.MAX_AGE_MIN). The other six render
    an AGE and judge nothing. MUTATION KILLED: guessing a budget for an unbudgeted source
    (the test counts them), copying the FloodNet number instead of deriving it (the test
    reads MAX_AGE_MIN), or giving the live pair a second, drifting copy of 120."""
    js = page_js()
    entries = layer_entries(js)
    all_budgets = [b for e in entries.values() for b in budgets(e)]
    assert len(all_budgets) == 9, "nine sources, nine budget declarations"
    assert all_budgets.count("null") == 6

    assert budgets(entries["live"]) == ["STALE_AFTER_S.live", "STALE_AFTER_S.live"]
    assert "const STALE_AFTER_S = { live: 120, bronze: 900 };" in js   # ticket 14's table
    assert budgets(entries["fn"]) == [str(flood_truth.MAX_AGE_MIN * 60)]
    for lid in ("zones", "cells", "mta", "impact", "hist"):
        assert budgets(entries[lid]) == ["null"] * len(budgets(entries[lid]))


def test_the_age_is_read_off_the_response_headers_and_never_off_a_payload():
    """frontend 01 D2. `Date` - `Last-Modified`, both from the origin, so a browser clock
    an hour behind cannot clamp an age to 0 and a CDN's cached copy errs stale. A payload
    stamp was rejected: it breaks test_export.py's byte-identity invariant AND it dates the
    write rather than the newest input. MUTATION KILLED: swapping either header for
    Date.now(), or reading an `as_of_utc` out of the body."""
    grab = page_js().split("async function grab(lyrId, s)", 1)[1].split("\n}", 1)[0]
    assert 'res.headers.get("Date")' in grab and 'res.headers.get("Last-Modified")' in grab
    assert "Date.now()" not in grab, "a browser clock cannot be allowed to fake freshness"
    assert "Math.max(0, (d - m) / 1000)" in grab
    assert 'cache: "no-store"' in grab


def test_a_missing_payload_is_stale_with_a_reason_and_never_an_empty_map():
    """A 404 and an empty FeatureCollection must not both paint an empty map under a fresh
    clock, and on the public host "run make live-export" is false in both halves - the
    files are not served because the gate is shut. MUTATION KILLED: treating !res.ok as a
    normal response, or recording an age for a response that carried no payload."""
    js = page_js()
    grab = js.split("async function grab(lyrId, s)", 1)[1].split("\n}", 1)[0]
    assert "if (!res.ok)" in grab
    assert 'res.status === 404 ? "not published on this host"' in grab
    assert "return null;" in grab
    assert 'whys["live/files/meta.json"] === "not published on this host"' in js


# --------------------------------------------------------------- the lineage gate, two sides
def test_both_lineage_gate_sides_exist_and_agree_with_the_publish_constant():
    """The MTA gate cuts by LINEAGE, so it has two sides: withholding the vehicles must
    never withhold the FloodNet tier, and opening the vehicles must never open MTA-derived
    alert rows. Ticket 08 lights a side by flipping ONE of these booleans. The expected
    value is DERIVED from publish.LIVE_TERMS_VERIFIED, so a page claiming a side is open
    while the pipeline refuses to publish it goes red here. MUTATION KILLED: one global
    switch instead of two keys, or a side opened on the page without the receipt."""
    js = page_js()
    block = js.split("const GATE = {", 1)[1].split("};", 1)[0]
    sides = dict(re.findall(r'"([a-z-]+)": (true|false)', block))
    assert set(sides) == {"mta-vehicles", "mta-alerts"}
    expected = "true" if publish.LIVE_TERMS_VERIFIED else "false"
    assert set(sides.values()) == {expected}, (
        "the page's gate sides disagree with publish.LIVE_TERMS_VERIFIED")
    assert "const shut = (lyr) => Boolean(lyr.gate) && !GATE[lyr.gate];" in js


def test_every_layer_names_its_gate_side_by_lineage():
    """Vehicle positions carry the live fleet AND flood 17's bus overlay; the alert rows
    carry the MTA flood tier. Nothing else is MTA-derived. MUTATION KILLED: gating the
    FloodNet tier (a layer with no MTA content) or leaving the bus overlay ungated."""
    entries = layer_entries(page_js())
    gates = {lid: re.search(r"gate: (\"[a-z-]+\"|null)", e).group(1)
             for lid, e in entries.items()}
    assert gates == {"zones": "null", "cells": "null", "live": '"mta-vehicles"',
                     "fn": "null", "mta": '"mta-alerts"', "impact": '"mta-vehicles"',
                     "hist": "null"}


def test_a_gated_layer_renders_dark_and_explained_never_absent():
    """Absence should be explained, not mysterious: the row stays, the box is disabled, the
    chip keeps its own hue and the reason is printed - and a gated layer never fetches.
    MUTATION KILLED: filtering gated layers out of the panel, or letting toggle() fetch one."""
    js, html = page_js(), page_html()
    row = js.split("function rowHTML", 1)[1].split("\n}", 1)[0]
    assert "const dark = shut(lyr);" in row
    assert "dark || !styled ? \"disabled\" : \"\"" in row
    assert "does not exist" in row                       # the printed reason
    toggle = js.split("async function toggle(id, want)", 1)[1].split("\n}", 1)[0]
    assert "if (shut(lyr)) return;" in toggle
    assert "not\n  verified" in html and 'id="mta-gate"' in html   # the deploy-time sentence


def test_the_four_not_yet_landed_sources_are_honest_off_or_gated_chips():
    """Rendering truthfully with layers dark is the design requirement, not a degraded
    mode. Each of the four names the ticket that owes its payload, so a reader is told what
    is missing rather than shown an empty map. MUTATION KILLED: deleting a not-yet-landed
    layer until its writer ships (which is what forces the re-plumbing tickets 07/08 are
    meant to be spared), or claiming a payload the page cannot draw."""
    entries = layer_entries(page_js())
    owed = {lid: re.search(r'owed: (\"[a-z0-9 ]+\"|null)', e).group(1)
            for lid, e in entries.items()}
    assert owed == {"zones": "null", "cells": "null", "live": "null", "fn": '"flood 15"',
                    "mta": '"flood 15"', "impact": '"flood 17"', "hist": '"notify 05"'}
    for lid in ("fn", "mta", "impact"):
        assert "draw: null" in entries[lid], f"{lid} may not claim to paint a payload it has not seen"


# ---------------------------------------------------------------- keyboard, mobile, layout
def test_toggling_a_layer_restores_focus_the_way_the_hour_buttons_do():
    """Rebuilding the rows destroys the control the reader just activated and focus falls to
    <body>, so a keyboard user tabs through the map and every other row again on each
    toggle - measured by clicking the prototype, not by eye. setHour() already solved this
    for the hour buttons; renderLayers reuses the same restore. MUTATION KILLED: dropping
    the restore from either place."""
    js = page_js()
    for fn in ("function renderLayers()", "function setHour(k)"):
        body = js.split(fn, 1)[1].split("\n}", 1)[0]
        assert "document.activeElement" in body, fn
        assert ".focus();" in body, fn
    restore = js.split("function renderLayers()", 1)[1].split("\n}", 1)[0]
    assert 'document.querySelector(`#layers [data-l="${keep}"]`)' in restore
    # the change handler is delegated to the stable container, so a rebuilt row keeps working
    assert '$("layers").addEventListener("change"' in js


def test_a_small_screen_opens_with_the_fill_on_and_every_point_layer_off():
    """frontend 02 D7: the 60vh map strip carries about two layers legibly at 375 px. The
    panel set itself does NOT collapse - it was measured at 375 px and nothing overlaps.
    MUTATION KILLED: a later slice defaulting a point layer on (the rule reads `l.point`,
    so a new point layer is covered without touching this code), or dropping the rule and
    opening seven layers on a phone."""
    js = page_js()
    assert 'window.matchMedia("(max-width: 900px)").matches' in js
    assert "LAYERS.forEach(l => { on[l.id] = l.open && !(SMALL && l.point); });" in js
    entries = layer_entries(js)
    points = {lid for lid, e in entries.items() if "point: true" in e}
    assert points == {"live", "fn", "mta", "hist"}
    opens = {lid for lid, e in entries.items() if "open: true" in e}
    assert opens == {"zones", "cells"}, "nothing but the ground and the fill opens lit"
    assert "@media (max-width: 900px)" in page_css()


def test_nothing_is_positioned_against_a_guessed_provenance_height():
    """The strip is mode-invariant (a spec sec.9 condition), its height changes with the
    attribution text and with every width, and a hard-coded clearance put the last toggle
    UNDERNEATH it in the prototype, where a real click never reached it. MUTATION KILLED:
    restoring a literal clearance, or dropping the observer that measures the strip."""
    css, js = page_css(), page_js()
    assert "bottom: 84px" not in css
    for col in ("#left", "#right"):
        rule = css.split(col + " { position: absolute;", 1)[1].split("}", 1)[0]
        assert "bottom: var(--prov)" in rule, col
    assert '$("provenance").offsetHeight' in js
    assert 'setProperty(\n  "--prov"' in js
    assert 'observe($("provenance"))' in js


def test_the_frozen_ramps_are_byte_untouched_and_the_new_hues_sit_beside_them():
    """frontend 02 D2: four new hues, none on either arm of the diverging ramp, and the
    ramp itself is not renegotiated. MUTATION KILLED: nudging a ramp stop, or reusing an
    existing colour for a new meaning."""
    js = page_js()
    assert ('const RATIO_STOPS = [[0.5, "#7f0000"], [0.65, "#d7301f"], [0.8, "#fc8d59"], '
            '[0.9, "#fdd49e"],\n                     [1.0, "#f7f7f7"], [1.1, "#c7dcef"], '
            '[1.2, "#6baed6"]];') in js
    assert ('const SPEED_STOPS = [[2, "#0d1b2a"], [3.5, "#1b4965"], [5, "#3d7ea6"], '
            '[6.5, "#7fb3d5"], [8, "#cfe6f4"]];') in js
    assert 'const GREY = "#3a4049";' in js
    for name, hue in (("WATER", "#35d6c2"), ("ALERT", "#ffc447"),
                      ("HIST", "#8f7bd6"), ("GATED_HUE", "#d2a24c")):
        assert f'const {name} = "{hue}";' in js
    ramp = {c for _, c in re.findall(r"\[([\d.]+), \"(#\w+)\"\]", js)}
    assert not ramp & {"#35d6c2", "#ffc447", "#8f7bd6", "#d2a24c"}
    assert ".st-GATED { color: #d2a24c; }" in page_css()


def test_a_dry_floodnet_sensor_is_a_hollow_ring_not_a_fifth_grey():
    """At 2.6 px a dry sensor, a dimmed vehicle and the "no publishable value" Cell fill
    were three meanings on one #3a4049. A sensor reporting water is a filled aqua disc; a
    dry or stale one is a STROKE with no fill, so it differs by MARK and not only by hue.
    MUTATION KILLED: painting the dry sensor grey (or any solid fill) again."""
    js = page_js()
    fn = js.split('{ id: "fn", type: "circle"', 1)[1].split('{ id: "mta"', 1)[0]
    assert '"circle-color": ["case", ["get", "display"], WATER, "rgba(0,0,0,0)"]' in fn
    assert '"circle-stroke-color": ["case", ["get", "display"], "#0b0d10", WATER]' in fn
    assert GREY_HEX not in fn, "a dry sensor may not be a fourth meaning on the grey"


GREY_HEX = "#3a4049"


def test_the_page_wires_the_layer_panel_ids():
    """The chassis's own seam: tickets 07 and 08 mount into these ids."""
    html, js = page_html(), page_js()
    for el in ("layers", "layers-fill", "layers-pts", "src-live", "live-chip", "right"):
        assert f'id="{el}"' in html, el
        if el != "right":
            assert f'"{el}"' in js, el
    # the live fleet's row IS the Live panel: one control, never two for one layer
    assert 'toggle: "livetoggle"' in js
    assert 'LAYERS.filter(l => !l.fill && !l.toggle).map(rowHTML)' in js
