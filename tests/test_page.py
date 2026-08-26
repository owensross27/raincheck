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
from page import (GEO_ORDER, SPEC_ORDER, budgets, layer_entries, module_js, page_css,
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
    """ES modules, no bundler, no npm (spec L). index.html carries exactly ONE script tag for
    the page's OWN code - `type="module"`, app.js - and the vendored library UMDs stay
    CLASSIC tags, because that is what puts `maplibregl` and `pmtiles` on window for every
    module to use. frontend2 02 added the second UMD and it could not be an import: the
    pmtiles ESM build carries a bare `from "fflate"`, which no browser resolves without an
    import map (measured - node's resolver refused it). The rule that matters is ONE ENTRY,
    so it is asserted as one module tag and classic tags that are all vendored, rather than
    as a count that a later vendored library would make wrong for no reason.
    MUTATION KILLED: adding a second entry module (which evaluates the graph twice),
    dropping `type="module"` (every `import` becomes a syntax error), making a vendored
    bundle a module (its global disappears and the map never constructs), or tagging one of
    the page's own modules instead of importing it."""
    html = page_html()
    assert '<script type="module" src="app.js"></script>' in html
    assert html.count('type="module"') == 1, "exactly one entry for the page's own code"
    tags = re.findall(r'<script(?: type="(\w+)")? src="([^"]+)"></script>', html)
    assert html.count("<script") == len(tags), "no inline script: no build step, no shim"
    assert [src for kind, src in tags if kind != "module"] == \
        ["vendor/maplibre-gl.js", "vendor/pmtiles.js"]
    for kind, src in tags:
        if kind != "module":
            assert src in publish.FAMILIES["site"].files, f"{src} is not vendored+published"
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
    assert added == {"layers.js", "freshness.js", "panel.js", "insight.js", "live.js",
                     "basemap.js"}          # frontend2 02 added the seventh, additively
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
    The twelve are asserted on their RELATIVE order with frontend2 03's geography band
    taken out first - the same re-derivation frontend2 02 made rather than a longer literal,
    because a longer literal is what stops being a statement about the frozen order.
    MUTATION KILLED: moving any layer in the style block, dropping one, or adding one
    through a later addLayer() instead of declaring it here."""
    declared = style_layers(page_js())
    assert [lid for lid in declared if lid not in GEO_ORDER] == SPEC_ORDER


def test_the_geography_band_sits_above_the_basemap_and_below_every_answer_layer():
    """frontend2 03. Routes and flood zones are GROUND: they must be above `bg` and above
    all 66 basemap layers, and below every layer that carries an answer. Both halves of
    that are one placement, and it is not the obvious one: every basemap layer is inserted
    with `beforeId: "zones-fill"` (SPEC_ORDER[1]), so anything declared BELOW `zones-fill`
    lands UNDER the whole basemap and is never seen. The band therefore sits in the gap
    between SPEC_ORDER[1] and SPEC_ORDER[2], and both bounds are derived from SPEC_ORDER
    rather than named again.
    MUTATION KILLED: declaring the band below `zones-fill` (invisible under the basemap),
    above `cells` (a second fill over the answer, which is what D1's one-ramp rule forbids),
    or reordering the three within the band so a fill paints over its own outline."""
    declared = style_layers(page_js())
    assert [lid for lid in declared if lid in GEO_ORDER] == GEO_ORDER, "the band's own order"
    lo, hi = declared.index(SPEC_ORDER[1]), declared.index(SPEC_ORDER[2])
    for lid in GEO_ORDER:
        assert lo < declared.index(lid) < hi, f"{lid} is outside the one gap it may sit in"
    # and the basemap's insertion point is still the first of the twelve, not one of these
    assert f'const FIRST_DATA_LAYER = "{SPEC_ORDER[1]}";' in module_js()["basemap.js"]


def test_the_basemap_goes_above_bg_and_below_every_one_of_the_twelve():
    """frontend2 02. The basemap's layer ids come from a VENDORED style, not from this
    repo, so the order rule cannot be a longer literal - there is nothing honest to write
    down. It is an INVARIANT instead: the twelve keep their frozen relative order (the test
    above), and every basemap layer is inserted with a `beforeId` naming the FIRST of the
    twelve after `bg`, which places all of it in the one gap between the background and the
    ground. That is also the only sanctioned addLayer/addSource on this page, and it lives
    in one module, so "declare at boot" still holds for everything this repo authors.
    MUTATION KILLED: dropping the `beforeId` (the whole basemap then lands ON TOP of the
    delay Cells and hides the answer), pointing it at a later layer, adding a second
    addLayer site in another module, or reordering SPEC_ORDER so `bg` is not first."""
    mods = module_js()
    base = mods["basemap.js"]
    assert SPEC_ORDER[0] == "bg", "the background is the only layer below the basemap"
    # the insertion point is DERIVED from the frozen order, never a second copy of the name
    assert f'const FIRST_DATA_LAYER = "{SPEC_ORDER[1]}";' in base
    assert "map.addLayer(l, FIRST_DATA_LAYER);" in base, "every basemap layer carries it"
    for name, js in mods.items():
        if name == "basemap.js":
            continue
        assert "addLayer(" not in js, f"{name}: a lazily added layer lands on top"
        assert "addSource(" not in js, name
    assert base.count("map.addLayer(") == 1 and base.count("map.addSource(") == 1


def test_the_basemap_falls_back_to_the_flat_bg_rectangle_and_never_throws():
    """A basemap is the least important thing on this page: the delay Cells are the answer
    and the ground is context. So every failure path - the archive not published, the
    vendored style missing, MapLibre refusing a layer - ends in the layer turning ITSELF
    off, the partial insert being removed, and the page painting the `bg` rectangle it has
    always had. Nothing here may throw into the boot handler, which awaits every layer's
    draw in turn: one rejection there and no layer after it ever loads.
    MUTATION KILLED: letting drawBasemap reject (dropping the try/catch), leaving a partial
    layer set behind on failure, or claiming the layer is still on after a failed fetch."""
    base = module_js()["basemap.js"]
    body = base.split("export async function drawBasemap(ok)", 1)[1]
    assert "if (!ok) { on.basemap = false; return; }" in body
    assert "} catch (err) {" in body and "dropBasemap();" in body
    assert "on.basemap = false;" in body.split("} catch (err) {", 1)[1]
    drop = base.split("function dropBasemap()", 1)[1].split("\n}", 1)[0]
    assert "map.removeLayer(id)" in drop and "map.removeSource(SRC)" in drop
    # idempotent: toggling the layer off and back on must not re-add an existing source
    assert "if (map.getSource(SRC)) return;" in body
    # and the fallback it falls back TO is still declared at boot
    assert '{ id: "bg", type: "background"' in page_js()


def test_the_basemap_is_vendored_and_names_no_third_host_at_demo_time():
    """spec L, unchanged since ticket 13: a demo must not be one unpkg request from a black
    screen. All three of the basemap's web assets come through `make vendor` with their own
    sha256 pins and are `site` family keys; the archive is the `tiles` family. Every URL the
    page uses for them is RELATIVE, so the bucket being the web/ tree is what makes them
    same-origin - which is also what lets the archive's age be read off its own response.
    MUTATION KILLED: pointing the style, the protocol or the glyphs at a CDN."""
    js = page_js()
    for host in ("unpkg.com", "cdn.", "protomaps.github.io", "api.protomaps.com"):
        assert host not in js, f"the page must not fetch from {host} at demo time"
    assert 'export const TILES = "tiles/nyc.pmtiles";' in js
    assert 'export const STYLE = "vendor/basemap-dark.json";' in js
    assert 'glyphs: "vendor/{fontstack}-{range}.pbf",' in js
    keys = set(publish.FAMILIES["site"].files)
    assert {"vendor/pmtiles.js", "vendor/basemap-dark.json",
            "vendor/notosans-0-255.pbf"} <= keys
    assert publish.FAMILIES["tiles"].files == ("nyc.pmtiles",)
    assert "tiles/nyc.pmtiles" not in keys, "the archive is never a site key, never committed"


def test_every_source_boots_empty_and_every_data_layer_boots_hidden():
    """An empty FeatureCollection at boot is what lets `cells` and the six not-yet-lit
    layers exist before their payload does; `visibility: "none"` is what stops them
    painting before the reader asks. MUTATION KILLED: booting a source straight off its
    URL again (which also re-creates the double fetch/parse of the 2.3 MB cells.geojson),
    or shipping a layer visible."""
    js = page_js()
    sources = js.split("sources: {", 1)[1].split("},", 1)[0]
    names = re.findall(r"(\w+): empty\(\)", sources)
    assert sorted(names) == ["cells", "fn", "hist", "impact", "live", "locate", "mta",
                             "routes", "stormwater", "zones"]
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
    assert len(all_budgets) == 12, "twelve sources, twelve budget declarations"
    # frontend2 03 adds two more unbudgeted static payloads (the route lines and the flood
    # zones' manifest). The zones layer's SECOND source is added at draw time and carries
    # `budget: null` too - see test_the_flood_zone_scenario_is_derived_from_a_manifest.
    assert all_budgets.count("null") == 9

    assert budgets(entries["live"]) == ["STALE_AFTER_S.live", "STALE_AFTER_S.live"]
    assert "const STALE_AFTER_S = { live: 120, bronze: 900 };" in js   # ticket 14's table
    assert budgets(entries["fn"]) == [str(flood_truth.MAX_AGE_MIN * 60)]
    for lid in ("basemap", "zones", "cells", "mta", "impact", "hist", "routes", "stormwater"):
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


def test_the_basemap_archive_is_dated_by_a_head_and_a_failed_fetch_is_explained():
    """Two halves of one rule. (a) A 52 MB archive still owes the reader an age, and the age
    must not cost 52 MB to learn - so its source is read with HEAD, which returns the same
    `Date` and `Last-Modified` every other source is dated from. It cannot be dated any
    other way: the tiles inside it are fetched by MapLibre's own pmtiles protocol, and a
    source MapLibre fetches for itself hands this page no headers at all (the same trap that
    made every other source boot from an empty FeatureCollection). (b) A layer that turned
    ITSELF off because its payload was not there prints the RECORDED reason instead of
    "nothing is being fetched" - so a missing basemap is an explained chip, never a silently
    black ground. A layer the reader unticked still reads the generic text, because
    forget() clears the reason.
    MUTATION KILLED: GETting the archive (52 MB per freshness poll), dating the basemap off
    a payload or a clock, or swallowing the reason on the OFF row."""
    js = page_js()
    grab = js.split("async function grab(lyrId, s)", 1)[1].split("\n}", 1)[0]
    assert 'method: s.head ? "HEAD" : "GET"' in grab
    assert "return s.head ? true : await res.json();" in grab
    assert "head: true" in layer_entries(js)["basemap"], "the archive is HEAD-ed, not fetched"
    state = js.split("function srcState(lyr, s)", 1)[1].split("\n}", 1)[0]
    assert 'return { s: "OFF", why: whys[key] || "nothing is being fetched" };' in state
    forget = js.split("function forget(lyrId)", 1)[1].split("\n}", 1)[0]
    assert "delete whys[" in forget, "an unticked layer must not inherit an old reason"


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
    assert gates == {"basemap": "null", "zones": "null", "cells": "null",
                     "live": '"mta-vehicles"', "fn": "null", "mta": '"mta-alerts"',
                     "impact": '"mta-vehicles"', "hist": "null",
                     # frontend2 03: the geometry is STATIC GTFS (the published schedule
                     # bundle), not the GTFS-Realtime feeds, and the numbers are the same
                     # historical 2021/2023 aggregate `cells` already publishes ungated off
                     # the same Gold table. Same lineage, same vintage, same gate side.
                     "routes": "null", "stormwater": "null"}


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
    assert owed == {"basemap": "null", "zones": "null", "cells": "null", "live": "null",
                    "fn": '"flood 15"', "mta": '"flood 15"', "impact": '"flood 17"',
                    "hist": '"notify 05"', "routes": "null", "stormwater": "null"}
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
    assert opens == {"basemap", "zones", "cells"}, "the ground, the basemap and the fill"
    assert "basemap" not in points, (
        "the basemap is GROUND, not a point layer: a phone that opens on a black rectangle "
        "is worse than one that opens on geography, and it costs no legibility to keep")
    assert "@media (max-width: 900px)" in page_css()


def test_the_basemap_attribution_is_in_the_mode_invariant_strip():
    """Attribution is a CONDITION of using this data, not a credit line, so it lives in the
    always-mounted #provenance strip - the same reason cloud 09 put the MTA line there
    rather than only inside MapLibre's compact control, which ships collapsed behind a
    button. The strings below are the two upstream requirements as READ on 2026-08-25, not
    paraphrased: the OSMF Attribution Guidelines want "(c) OpenStreetMap contributors"
    adjacent to the map, made clear to be under the Open Database License by linking
    openstreetmap.org/copyright; github.com/protomaps/basemaps requires a Produced Work to
    visibly attribute (c) OpenStreetMap and asks for credit to Protomaps.
    MUTATION KILLED: moving the credit into the compact control alone, dropping the ODbL
    sentence (attribution without the licence is not attribution under these guidelines),
    or dropping either link."""
    html = page_html()
    strip = html.split('id="provenance"')[1]
    assert '<p id="basemap-attribution">' in strip
    for s_ in ("OpenStreetMap contributors",
               "https://www.openstreetmap.org/copyright",
               "Open Database License (ODbL)",
               "Protomaps",
               "https://github.com/protomaps/basemaps"):
        assert s_ in strip, s_
    # and it survives the page's one styling switch: the strip has no mode-conditional rule
    assert "#provenance" in page_css()
    assert "no basemap" not in html, "the ticket 14 sentence is retired, not left standing"


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
    hues = {"WATER": "#35d6c2", "ALERT": "#ffc447", "HIST": "#8f7bd6", "GATED_HUE": "#d2a24c",
            # frontend2 03: two tones of ONE hue for the two modelled depths, plus a
            # NEUTRAL for DEP's exclusion mask that is deliberately not GREY (which already
            # means "no publishable value" on the Cell fill), and an uncoloured route line.
            "ZONE_DEEP": "#2e7d5b", "ZONE_NUISANCE": "#8fcfae", "ZONE_MASK": "#7a8794",
            "ROUTE_PLAIN": "#5b6572"}
    for name, hue in hues.items():
        assert f'const {name} = "{hue}";' in js
    assert len(set(hues.values())) == len(hues), "two meanings on one hue"
    ramp = {c for _, c in re.findall(r"\[([\d.]+), \"(#\w+)\"\]", js)}
    assert not ramp & set(hues.values())
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


# ==================================== frontend2 03: the geography layers ==================
def test_one_ramp_on_screen_is_a_paint_rule_and_not_a_promise():
    """DESTINATION-PLAN D1. The Cell fill is an exclusive radio and it is frozen; the flood
    zones are non-Cell polygons and the route line is a separate channel, so neither JOINS
    that radio. What binds them to it is applyRamp(), and it is asserted on the PAINT
    EXPRESSIONS because that is where the rule can actually be broken:

      a Cell fill is lit  -> the zone fill goes to opacity 0 (outlines only) and the route
                             line is ROUTE_PLAIN at the thin width - geometry, no number
      no Cell fill is lit -> the zone fill paints and the route line carries the SAME ramp,
                             on the SAME property, through the SAME colorExpr() the Cell
                             fill uses. Not a second ramp and not a second mapping table.

    MUTATION KILLED: inverting the test (`fillOn ? ZONE_FILL_OPACITY : 0`, which puts two
    fills on one geography); ramping the line unconditionally; giving the route its own
    stops instead of the fill's; or dropping the `styled` guard, which makes every paint
    call throw before MapLibre has parsed the style."""
    js = page_js()
    body = js.split("export function applyRamp()", 1)[1].split("\n}", 1)[0]
    assert "if (!styled) return;" in body, "every paint call throws before the style parses"
    assert ("const fillOn = LAYERS.some(l => l.fill && on[l.id] && !shut(l));") in body
    assert 'map.setPaintProperty("stormwater-fill", "fill-opacity", fillOn ? 0 : ZONE_FILL_OPACITY);' in body
    assert "const ramped = !fillOn && view !== null;" in body
    assert 'map.setPaintProperty("routes", "line-color", ramped' in body
    assert ("? colorExpr(activeProp(), view.kind === \"speed\" ? SPEED_STOPS : RATIO_STOPS, "
            "ROUTE_PLAIN)") in body
    assert ": ROUTE_PLAIN);" in body
    assert 'map.setPaintProperty("routes", "line-width", ramped ? ROUTE_W_RAMP : ROUTE_W_THIN);' in body
    # and it re-runs on every event that can change which fill is lit or which view is shown
    assert "applyRamp();   // the route line follows the view it is showing (D1)" in js
    boot = module_js()["app.js"]
    assert "applyRamp();" in boot.split('map.on("load"', 1)[1]
    assert boot.count("applyRamp()") >= 3, "boot, a layer toggle and the fill-off option"


def test_the_cell_fill_can_actually_be_turned_off():
    """The other half of D1 is unreachable without this and that is not a style point. A
    radio cannot be un-checked by clicking it, and the only other fill option (`impact`) is
    gated and therefore rendered disabled - so before frontend2 03 the Cell fill could
    never be off, which means the flood zones could never fill and the route line could
    never carry the ramp. The OFF row declares no layer and claims no channel: `fill: true`
    is still exactly {cells, impact} (the test above), and it simply clears whichever fill
    is lit through the existing toggle().
    MUTATION KILLED: dropping the row (D1's ramp branch becomes dead code that no reader
    can reach), or implementing it as a third `fill: true` layer, which would put a third
    option in a channel frontend 02 froze at two."""
    js = page_js()
    row = js.split("const noFillHTML = () =>", 1)[1].split("`;", 1)[0]
    assert 'name="cellfill"' in row, "it is IN the frozen radio group, not beside it"
    assert 'data-nofill="1"' in row
    assert 'LAYERS.some(l => l.fill && on[l.id]) ? "" : "checked"' in row
    assert '$("layers-fill").innerHTML = LAYERS.filter(l => l.fill).map(rowHTML).join("") + noFillHTML();' in js
    handler = module_js()["app.js"].split('$("layers").addEventListener', 1)[1].split("\n});", 1)[0]
    assert "const lit = LAYERS.find(l => l.fill && on[l.id]);" in handler
    assert "if (lit) await toggle(lit.id, false);" in handler


def test_the_flood_zone_scenario_is_derived_from_a_manifest_and_never_a_file_name():
    """`geo` is a TREE family: its served set is DERIVED from silver/stormwater_extent, so
    a scenario appears the day the table has one. A browser cannot list a directory, so the
    page would otherwise have to name `stormwater-moderate.geojson` in JavaScript - and the
    day a second scenario is readable that is a page edit, i.e. the rewrite this layer is
    told not to require. The layer's FIRST source is the manifest; the scenario payload is a
    second source the draw adds, fetched through the same grab() every other source uses so
    it carries a freshness row that follows the radio.
    MUTATION KILLED: hard-coding a scenario file name or a list of three names; building
    the radio from a literal; or fetching the payload outside grab(), which would give the
    layer a row naming a file it is not showing."""
    js = page_js()
    entry = layer_entries(js)["stormwater"]
    assert 'k: "files/geo/scenarios.json", url: "files/geo/scenarios.json"' in entry
    for name in ("moderate", "limited", "extreme"):
        assert f"stormwater-{name}" not in js, f"the page names {name} - that is the rewrite"
    body = js.split("export async function drawZones(manifest)", 1)[1].split("\n}", 1)[0]
    assert "scenarios = manifest && Array.isArray(manifest.scenarios) ? manifest.scenarios : [];" in body
    assert 'const src = { k: "files/geo/" + row.key, url: "files/geo/" + row.key, budget: null };' in body
    assert "const body = await grab(lyr.id, src);" in body
    assert "lyr.srcs = [lyr.srcs[0], src];" in body
    # one scenario visible at a time, and a single option must not break the radio
    assert "if (!scenarios.some(s => s.scenario === scenario)) scenario = scenarios[0].scenario;" in body
    assert "if (!scenarios.length) {" in body, "no scenario published is a sentence, not a throw"
    opts = js.split("const optsHTML = (lyr) =>", 1)[1].split("`;", 1)[0]
    assert 'type="radio" name="${lyr.id}-opt"' in opts and 'data-sc="${o.id}"' in opts


def test_the_exclusion_mask_is_a_legend_entry_and_is_never_painted_clear():
    """DEP's "Area not included in analysis" is a CATEGORY, not an absence: the whole flood
    chain refuses to impute it to "no flooding" (features.sample()'s own rule) and
    silver/stormwater_extent carries it as polygons for exactly this reason. A legend that
    shows two flood depths and silently omits the mask tells the reader that everything
    unpainted was modelled and found dry, which is false. So it gets its own swatch, its own
    sentence, and a hue that is NOT a third depth tone and NOT the page's existing GREY.
    MUTATION KILLED: dropping the mask from ZONE_LEGEND; painting it with a depth tone;
    rendering the legend only for the categories a payload happens to carry (a build that
    lost the mask would then show a shorter legend rather than an empty count)."""
    js = page_js()
    assert '"not_analyzed", ZONE_MASK, ZONE_MASK];' in js, "named AND the default"
    legend = js.split("export const ZONE_LEGEND = [", 1)[1].split("];", 1)[0]
    ids = re.findall(r'\["(\w+)", (\w+),', legend)
    assert ids == [("deep", "ZONE_DEEP"), ("nuisance", "ZONE_NUISANCE"),
                   ("not_analyzed", "ZONE_MASK")]
    assert "NOT" in legend and "no flooding" in legend, "the mask says what it is not"
    body = js.split("function zoneLegend(body, row)", 1)[1].split("\n}", 1)[0]
    assert "ZONE_LEGEND.map(" in body, "every row is rendered, present in the payload or not"
    assert "not an ` +" in body and "observation of water" in body
    # the swatch reads the same table the paint does - never a second copy of a colour
    assert 'style="background:${hue}"' in body


def test_the_geography_credits_are_read_off_the_payload_and_mounted_while_it_is_shown():
    """Attribution is a CONDITION of displaying this data, not a credit line - so it lives
    in the always-mounted `#provenance` strip beside the OSM and MTA lines. It is READ OFF
    THE PAYLOAD's own `attribution` member rather than mirrored into the page, which is the
    repo's standing rule for any string the page shares with a writer in src/: a mirrored
    constant pins the mirror to itself, and here it would let a wording change in
    stormwater_extent.ATTRIBUTION drift silently away from what the page prints. It fills
    when a geography layer is on and empties when it is off, because with the layer off no
    DEP or GTFS geometry is being displayed.
    MUTATION KILLED: writing DEP's sentence into the page (the mirror); setting it with
    innerHTML (it is a string out of a payload); or leaving it mounted after the layer is
    unticked, which credits a source nothing on screen came from."""
    html, js = page_html(), page_js()
    strip = html.split('id="provenance"')[1]
    assert '<p id="geo-attribution"></p>' in strip, "mounted, and EMPTY until a layer draws"
    for mirrored in ("Department of Environmental Protection", "9i7c-xyvv", "design-storm"):
        assert mirrored not in js, f"the page mirrors {mirrored!r} instead of reading it"
    body = js.split("function renderGeoAttribution()", 1)[1].split("\n}", 1)[0]
    assert "if (on.routes && routeAttr) parts.push(routeAttr);" in body
    assert "if (on.stormwater && zoneAttr) parts.push(zoneAttr);" in body
    assert '$("geo-attribution").textContent = parts.join' in body, "text, never markup"
    assert 'routeAttr = (body && body.attribution) || "";' in js
    assert 'zoneAttr = (body && body.attribution) || "";' in js
    assert "renderGeoAttribution();" in js.split("export function applyRamp()", 1)[1]


def test_no_mta_route_bullet_roundel_or_line_colour_reaches_the_page():
    """The MTA website T&C (read by Ross 2026-08-26) makes "the logos for New York City
    Transit subway lines" and "MTA official maps" usable only with prior written permission,
    while stop names, coordinates and delay numbers are facts. frontend2 03 is the first
    ticket that draws route geometry, so it is the first that could break the sweep that has
    been clean until now: a polyline from silver/shapes is a fact and a coloured route
    bullet is MTA IP.
    MUTATION KILLED: painting the route line from a `route_color` property, importing an
    MTA palette, or rendering the route id as a roundel."""
    js, html, css = page_js(), page_html(), page_css()
    for banned in ("route_color", "daytime_routes", "roundel", "bullet"):
        for where, text in (("js", js), ("html", html), ("css", css)):
            assert banned not in text.lower(), f"{banned} in the page's {where}"
    # the route line's hue is this repo's own and does not come out of a payload
    entry = page_js().split('{ id: "routes", type: "line"', 1)[1].split('{ id: "cells"', 1)[0]
    assert '"line-color": ROUTE_PLAIN' in entry
    assert '["get"' not in entry, "no payload property may drive the route line's colour"


def test_the_exclusion_mask_recedes_but_is_never_drawn_clear():
    """Both halves, and they pull against each other. `not_analyzed` polygons are the BIG
    ones - rail corridors, large lots, open space - so at the modelled classes' own opacity
    they wash the city out and hide the flood depths and the route lines under them
    (measured in a real tab at 1500x950, not predicted). It therefore carries less ink than
    a class that carries more information. But it is NEVER zero and never absent: painting
    DEP's exclusion mask as clear says everything unpainted was modelled and found dry.
    MUTATION KILLED: setting the mask's opacity to 0 (which is the lie), or giving it the
    depths' opacity again (which hides the answer under the caveat)."""
    js = page_js()
    for name in ("ZONE_FILL_OPACITY", "ZONE_LINE_OPACITY"):
        expr = js.split(f"export const {name} = ", 1)[1].split(";", 1)[0]
        m = re.match(r'\["match", \["get", "category"\], "not_analyzed", ([\d.]+), ([\d.]+)\]',
                     expr)
        assert m, f"{name} is not a per-category expression: {expr}"
        mask, modelled = float(m.group(1)), float(m.group(2))
        assert 0 < mask < modelled, f"{name}: mask {mask}, modelled {modelled}"
    assert '"fill-opacity": ZONE_FILL_OPACITY' in js
    assert '"line-opacity": ZONE_LINE_OPACITY' in js


def test_an_unpublishable_route_crossing_is_uncoloured_and_not_invisible():
    """spec L's grey guard, on a mark it was not calibrated for. GREY (#3a4049) is the
    Cell fill's "no publishable value" and it is chosen to recede AMONG coloured Cells; as a
    sub-pixel hairline on the dark basemap it disappears, so a route crossing whose interval
    is too wide would read as no route at all. `colorExpr` takes the absent colour as a
    parameter and the route passes ROUTE_PLAIN - the hue that already means "geometry, no
    number". One meaning, two marks, and neither is a new colour.
    MUTATION KILLED: dropping the parameter (the network develops holes wherever the
    evidence is thin), or giving the route a fourth grey of its own."""
    js = page_js()
    assert "function colorExpr(prop, stops, absent = GREY) {" in js
    assert '["case", ["!", ["has", prop]], absent, interp];' in js
    fill = js.split("function paint()", 1)[1].split("\n}", 1)[0]
    assert "colorExpr(activeProp(), s)" in fill, "the Cell fill keeps spec L's grey"
    assert "ROUTE_PLAIN)" in js.split("export function applyRamp()", 1)[1]
