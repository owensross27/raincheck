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

from raincheck import contract, flood_overlay, flood_truth, publish
# `page`, not `tests.page`: pytest's prepend import mode puts THIS directory on sys.path
# (there is no tests/__init__.py), so the bare name resolves under `pytest tests/...` as
# well as under `make test`. `tests.page` resolves only when the repo root happens to be
# sys.path[0], which is true of `python -m pytest` from the root and of nothing else.
from page import (GEO_ORDER, SPEC_ORDER, SUB_ORDER, budgets, layer_entries, module_js,
                  page_css, page_files, page_html, page_js, style_layers, web)


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
    # no-cache, not no-store (frontend3 02): a meta.json served without REVALIDATION is a
    # lie, and no-cache revalidates every fetch - a 304 carries fresh Date+Last-Modified
    # at zero body bytes. no-store meant never stored AND never revalidated, so
    # `public, max-age=300` on files/ did nothing and ~500 KB re-downloaded per repeat load.
    assert "cache: \"no-cache\"" in js
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
    assert [lid for lid in declared
            if lid not in GEO_ORDER and lid not in SUB_ORDER] == SPEC_ORDER


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
                             "routes", "stormwater", "subway", "zones"]
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
    assert len(all_budgets) == 13, "thirteen sources, thirteen budget declarations"
    # frontend2 03 adds two more unbudgeted static payloads (the route lines and the flood
    # zones' manifest). The zones layer's SECOND source is added at draw time and carries
    # `budget: null` too - see test_the_flood_zone_scenario_is_derived_from_a_manifest.
    # frontend 08 graduates the two impact rows (flood 17's derived budgets, asserted from
    # the module below); `mta` deliberately stays AGE - no staleness constant for the
    # alert-side FILE is frozen anywhere in the repo, and a guessed one is the exact
    # failure this test exists to catch.
    assert all_budgets.count("null") == 8

    assert budgets(entries["live"]) == ["STALE_AFTER_S.live", "STALE_AFTER_S.live"]
    assert "const STALE_AFTER_S = { live: 120, bronze: 900 };" in js   # ticket 14's table
    assert budgets(entries["fn"]) == [str(flood_truth.MAX_AGE_MIN * 60)]
    # flood 17's two derived budgets, read from the module that derives them - never a
    # second copy that can drift (122400 = one nightly cycle + daily.TAIL_H; 4200 = the
    # hour + archiver.WINDOW)
    assert budgets(entries["impact"]) == [str(flood_overlay.BUS_BUDGET_S)]
    assert budgets(entries["subway"]) == [str(flood_overlay.SUBWAY_BUDGET_S)]
    for lid in ("basemap", "zones", "cells", "mta", "hist", "routes", "stormwater"):
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
    # `no-cache`, NOT `default` (frontend3 02): default would serve a stored response with
    # a FROZEN Date header - the frozen-age trap through the browser cache - while
    # no-cache revalidates, and a 304 carries the exact header pair subtracted above.
    assert 'cache: "no-cache"' in grab
    assert '"default"' not in grab


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


def test_every_page_fetch_revalidates_and_none_bypasses_the_browser_cache():
    """frontend3 02's inherited no-store -> no-cache fix, over BOTH fetch sites - grab()
    and the basemap style fetch, which previously had no test at all (the wave-11 box
    named that gap). `no-store` is never-stored-and-never-revalidated, so the families'
    own Cache-Control did nothing; `no-cache` revalidates (a 304 carries fresh Date +
    Last-Modified, the pair the reader-dating subtracts, at zero body bytes); `default`
    would serve a stored response with a frozen Date - the frozen-age trap.
    MUTATION KILLED: reverting either site to no-store, or 'fixing' one to default."""
    js = page_js()
    assert js.count('cache: "no-cache"') == 2, "grab() and the basemap style fetch"
    assert '"no-store"' not in js


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
                     "impact": '"mta-vehicles"', "subway": '"mta-vehicles"', "hist": "null",
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
    mode. A layer whose payload has not landed names the ticket that owes it; frontend 08
    landed the draws for the tier points and both impact overlays, so those four claim
    their payloads now and owe nothing. MUTATION KILLED: deleting a not-yet-landed layer
    until its writer ships, claiming a payload the page cannot draw, or leaving a stale
    `owed:` note over a layer whose draw exists."""
    entries = layer_entries(page_js())
    owed = {lid: re.search(r'owed: (\"[a-z0-9 ]+\"|null)', e).group(1)
            for lid, e in entries.items()}
    assert owed == {"basemap": "null", "zones": "null", "cells": "null", "live": "null",
                    "fn": "null", "mta": "null", "impact": "null", "subway": "null",
                    "hist": "null",   # notify 05 landed its manifest; frontend 07 lit it
                    "routes": "null", "stormwater": "null"}
    for lid, fn in (("fn", "drawFn"), ("mta", "drawMta"),
                    ("impact", "drawImpact"), ("subway", "drawImpactSub")):
        assert f"{fn}(" in entries[lid], f"{lid}'s draw is {fn}"
        assert "draw: null" not in entries[lid], lid


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
    assert points == {"live", "fn", "mta", "hist", "subway"}
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
    # BOUNDED at the strip's own close (frontend3 02): an unbounded split-once slice reads
    # everything to end-of-file as "inside" the strip, so content added after it - a
    # dialog, a script - would satisfy "the credit is in the always-visible strip" from a
    # collapsed surface. The strip is the page's <footer>; the info dialog sits BEFORE it
    # in source order, and this bound is what keeps that arrangement honest.
    strip = html.split('id="provenance"')[1].split("</footer>")[0]
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
    # by SHAPE, not the one literal (frontend3 02): "bottom: 84px" banned only the guess
    # that happened once - any OTHER literal clearance in a column rule defeats the
    # measured --prov mechanism just the same, and a reflow could reintroduce one at a
    # different number. The rule is: no pixel-literal `bottom:` inside either column rule.
    for col in ("#left", "#right"):
        rule = css.split(col + " { position: absolute;", 1)[1].split("}", 1)[0]
        assert "bottom: var(--prov)" in rule, col
        assert not re.search(r"bottom:\s*\d", rule), f"{col}: a literal clearance"
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
            "ROUTE_PLAIN": "#5b6572",
            # frontend 08: the subway impact overlay's one hue - a new mark family
            # (complex-grain points) gets a new hue rather than overloading ALERT, which
            # already means "an MTA station with water on the tracks"
            "SUBWAY": "#e07ba0"}
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
    # bounded at </footer>, same rationale as the basemap-attribution test above
    strip = html.split('id="provenance"')[1].split("</footer>")[0]
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


# ==================================== frontend 08: the flood tiers and the impact overlays
def test_the_tier_vocabulary_is_read_from_the_payload_and_never_spelled():
    """The tier words come from flood 11's display.tier_labels via flood_panel.strings(),
    the same artifact every notify message reads - so the page and a message cannot
    disagree, and Ross recording flood 12's verdict changes the payload with no page edit.
    The frozen honesty string is likewise READ (strings.operating_truth), never mirrored:
    a page constant that mirrors a src/ constant pins the mirror to itself (TRAPS).
    MUTATION KILLED: typing a tier word into the page; pasting the operating-truth
    sentence into JS; or rendering a unit's tier without going through tier_labels."""
    js = page_js()
    for word in ('"NONE"', '"ELEVATED"', '"HIGH"', '"elevated"', '"high"', "not flagged"):
        assert word not in js, f"the page spells {word} instead of reading tier_labels"
    assert "tier_labels" in js, "the tier word is looked up, never typed"
    assert "ranks where a flood REPORT is likely" not in js, "the honesty string is mirrored"
    assert "operating_truth" in js, "the honesty string is read from the payload"
    # nothing may print an absent value: the unit line filters absent members out
    body = js.split("export function drawFn(f)", 1)[1].split("\n}", 1)[0]
    assert ".filter(Boolean).join(" in body
    assert "(s.tier_labels || {})[u.tier]" in body
    assert "u.asset_id" in body, "names are not unique at any grain - the id prints beside them"


def test_the_bus_overlay_joins_by_hex_and_paints_absent_ratio_grey_on_the_frozen_ramp():
    """flood 17: `cells` is keyed by the H3 HEX STRING cells.geojson already carries, so
    the join needs no lookup - and the geometry is read from the map's own `cells` source
    because cells.geojson is fetched ONCE (frontend 05 retired the double parse). There is
    no capture-era baseline today, so `ratio` is an ABSENT key on every Cell and
    ["!", ["has", "ratio"]] paints grey - the chassis's own rule; the ramp is RATIO_STOPS
    spread into the boot declaration, never a second table. The payload's reason sentence
    is rendered, not restated. MUTATION KILLED: giving the overlay its own stops; painting
    absent ratio as a zero (a 0.5-clamped dark red lie); fetching cells.geojson a second
    time; or dropping the baseline.reason render."""
    js = page_js()
    block = js.split('{ id: "impact-fill"', 1)[1].split('{ id: "cells-line"', 1)[0]
    assert '["case", ["!", ["has", "ratio"]], GREY,' in block
    assert '["interpolate", ["linear"], ["get", "ratio"], ...RATIO_STOPS.flat()]' in block
    body = js.split("export function drawImpact(b)", 1)[1].split("\n}", 1)[0]
    assert 'map.getSource("cells")' in body, "the geometry the page already parsed"
    assert "(b.cells || {})[f.properties.cell]" in body, "the hex-keyed join"
    assert 'fetch("files/cells.geojson"' not in js, "cells.geojson is fetched once"
    assert "b.baseline.reason" in body, "the payload says WHY there is no ratio - render it"
    assert "b.n_cells" in body and "b.densest_cells" in body, (
        "the sparse head is said, not just painted")


def test_the_subway_overlay_is_points_beside_the_alert_dots_with_a_clamped_rel_ramp():
    """flood 17: complex-grain POINTS, never a second Cell fill - a Cell overlay and a
    complex overlay in one legend would be lying about their grain, so it is its own layer
    on its own channel, declared at boot in the gap between the two flood tier point
    layers (the bounds derived from SPEC_ORDER's tail, the GEO_ORDER shape). `rel` runs to
    18.7 against a median drop_share of 0.0247, so the ramp is CLAMPED at REL_CLAMP - an
    interpolate holds its last output past its last stop, so the clamp is the expression -
    and a complex below min_planned carries NO rel: absent, not zero, rendered as a RING
    (the fn layer's established present-but-no-value mark). MUTATION KILLED: declaring it
    `fill: true` (a third option in the frozen radio); an unclamped ramp (one station and
    437 flat ones); or writing `rel: 0` for a withheld complex."""
    js = page_js()
    declared = style_layers(js)
    assert [lid for lid in declared if lid in SUB_ORDER] == SUB_ORDER
    lo, hi = declared.index(SPEC_ORDER[-2]), declared.index(SPEC_ORDER[-1])
    for lid in SUB_ORDER:
        assert lo < declared.index(lid) < hi, f"{lid} sits between the two tier point layers"
    entry = layer_entries(js)["subway"]
    assert "fill: true" not in entry, "never a second Cell fill"
    assert "point: true" in entry
    block = js.split('{ id: "subway", type: "circle"', 1)[1].split('{ id: "mta"', 1)[0]
    assert '["interpolate", ["linear"], ["get", "rel"], 1, 3.5, REL_CLAMP, 9]' in block
    assert "const REL_CLAMP = 4;" in js
    assert '["case", ["has", "rel"], SUBWAY, "rgba(0,0,0,0)"]' in block, "absent rel is a ring"
    body = js.split("export function drawImpactSub(d)", 1)[1].split("\n}", 1)[0]
    assert '..."rel" in c ? { rel: c.rel } : {}' in body.replace("(", "").replace(")", ""), \
        "rel rides only when the payload carries it - absent, never zero"


def test_the_impact_rows_graduate_with_a_reader_dated_data_age_composite():
    """The impact payloads carry their own staleness INLINE (no meta files, flood 17):
    `staleness.age_min` is the DATA's age at write, and the header age grab() recorded is
    the file's age since - their sum is the data's age now, dated at the reader, counting
    up after the writer dies. Without it a freshly rewritten file over a stale Gold hour
    reads FRESH, which is the frozen-age trap through a new door. Both draws add it; the
    verdict itself stays srcState()'s, against the frozen budgets the module derives.
    MUTATION KILLED: dropping the composite from either draw (the bus row then reads
    FRESH today while the payload's own state is STALE at 40 h), or clamping the sum so a
    negative writer skew subtracts age."""
    js = page_js()
    body = js.split("function addDataAge(lyrId, body)", 1)[1].split("\n}", 1)[0]
    assert "ages[key] += Math.max(0, body.staleness.age_min * 60);" in body
    for draw, lid in (("drawImpact(b)", '"impact"'), ("drawImpactSub(d)", '"subway"')):
        fn = js.split(f"export function {draw}", 1)[1].split("\n}", 1)[0]
        assert f"addDataAge({lid}" in fn, draw
    assert js.count("addDataAge(") == 3, "defined once, called by exactly the two overlays"


def test_the_design_storm_sentence_renders_only_when_present_and_never_a_placeholder():
    """flood-build 20's frozen shape (landed same wave): `display.sentence` carries ONE
    placeholder, {mm_1h}, substituted per Cell from cells[hex].design_storm - a dict
    present on SCORED Cells only, ONLY while raining there. The page renders the wettest
    such Cell's sentence and the three bound qualifier notes WITH it; `bracket_sentence`
    only when that Cell carries `bracket` (absent below Limited). An absent block, a
    pre-fb20 payload, and a dry night (block present, zero per-Cell keys) all render
    NOTHING - no placeholder, no 'coming soon', and no literal rate typed into JS (the
    intensities have ONE home, stormwater_extent.SCENARIOS, and reach the page only
    through the payload's own strings). MUTATION KILLED: printing the raw {mm_1h}
    placeholder; rendering the block on a dry night; rendering bracket_sentence without
    a bracket; typing a rate; or a placeholder when the key is absent."""
    js = page_js()
    body = js.split("export function drawFn(f)", 1)[1].split("\n}", 1)[0]
    assert "const dsB = f.design_storm;" in body
    assert "if (dsB && dsB.display) {" in body
    assert "if (rain.length) {" in body, "a dry night renders nothing"
    assert '.replace("{mm_1h}", worst.mm_1h)' in body, "the placeholder is substituted"
    assert "if (worst.bracket && dsB.display.bracket_sentence)" in body
    assert '.replace("{bracket}", worst.bracket)' in body
    assert '["bracket_note", "climate_note", "extent_note"]' in body, (
        "the three bound qualifiers travel with the claim")
    for literal in ("54.10", "44.96", "92.96", "1.77", "2.13", "3.66"):
        assert literal not in js, f"a design-storm rate {literal} is typed into the page"
    assert "coming soon" not in js.lower()


# ==================================== frontend2 05: one page, two audiences ===============
def test_everything_analyst_grade_sits_behind_one_closed_real_details_disclosure():
    """DESTINATION-PLAN D7. The analyst prose - preview_note, the headline's interval
    rows and estimands, the curve, the chord/hidden/gate notes and the legend estimand -
    lives INSIDE one real <details> element, which ships CLOSED (no `open` attribute, so
    the rider view is the default) and whose control is a native <summary>, never a
    div-with-a-click-handler pretending. Everything inside kept its id, so no render call
    changed. The frozen honesty string is NOT in here: it renders in the fn layer's own
    row (flood 15's strings, read from the payload) and stays visible in both views.
    MUTATION KILLED: shipping the disclosure open (the analyst view becomes the default,
    reversing D7); moving one of the seven surfaces back out; a second <details> (the
    decision is ONE disclosure); or replacing <details> with a styled div, which loses
    the platform's keyboard and screen-reader semantics."""
    html = page_html()
    assert html.count("<details") == 1, "ONE disclosure for everything analyst-grade"
    m = re.search(r"<details([^>]*)>(.*?)</details>", html, re.S)
    attrs, block = m.group(1), m.group(2)
    assert 'id="analyst"' in attrs
    assert "open" not in attrs, "default CLOSED: the rider view is the default (D7)"
    assert "<summary>" in block, "a real disclosure element, not a styled div"
    for el in ('id="preview-note"', 'id="headline"', 'id="curve"', 'id="note-chord"',
               'id="note-hidden"', 'id="note-gate"', 'id="legend-estimand"'):
        assert el in block, f"{el} is analyst prose and must sit inside the disclosure"
    assert 'id="answer"' in html.split("<details", 1)[0], "the rider's answer line stays out"


def test_the_disclosure_state_is_remembered_with_both_localstorage_sides_guarded():
    """The reader's choice persists per browser, and localStorage is allowed to fail:
    private windows and storage-blocking settings THROW on access, so both the read and
    the write sit in try/catch and anything but a stored "open" reads as closed - absent,
    unreadable and garbage all land on the rider default. The wiring is app.js's, like
    every listener on this page (the cyclic-module rule).
    MUTATION KILLED: an unguarded read (the page dies at boot in a private window); a
    truthy default (absent state opening the analyst view); or the toggle listener moving
    into another module."""
    app = module_js()["app.js"]
    # by SHAPE, not the verbatim source line (frontend3 02): the old assert pinned the
    # line's exact whitespace, so any reflow of app.js turned it red with the guard fully
    # intact. What the rule actually is: the READ is inside try/catch, and only a stored
    # "open" (strict equality) opens the analyst view - absent/garbage lands closed.
    assert re.search(r'try\s*\{\s*\$\("analyst"\)\.open\s*=\s*localStorage\.getItem\('
                     r'"raincheck\.analyst"\)\s*===\s*"open";?\s*\}\s*catch', app), (
        "the localStorage read must be guarded and default closed")
    assert 'try { localStorage.setItem("raincheck.analyst"' in app
    assert '$("analyst").addEventListener("toggle"' in app
    for name, js in module_js().items():
        if name != "app.js":
            assert "localStorage" not in js, f"{name} touches localStorage - app.js owns it"


def test_the_rider_list_renders_recent_json_strings_verbatim_and_never_says_today():
    """The summary payloads may be RENDERED but their key shapes are frozen by use
    (frontend2 04), and `strings.caveats[]` render VERBATIM on every surface that shows
    them - the page escapes and prints the sentences, it restates nothing. The window is
    anchored on the SPINE'S newest day_end, so the page prints the payload's own dates
    and never the word today. The fetch goes through grab(), the page's one dated seam,
    with `budget: null` (no staleness budget is frozen for this file). Rows are focusable
    (tabindex), so the locate ring answers a keyboard and a tap as well as a hover - and
    the row content is facts (a date span, labelled-asset counts), no analyst vocabulary.
    MUTATION KILLED: paraphrasing the caveats instead of rendering them; captioning the
    window as "today"; a bare fetch() that dates nothing; or mouse-only rows."""
    ins = module_js()["insight.js"]
    body = ins.split("export async function loadRecent()", 1)[1].split("\n}", 1)[0]
    assert '"files/summary/recent.json"' in body and "budget: null" in body
    assert "await grab(" in body, "fetched and dated through the page's one seam"
    assert "s.caveats" in body and "esc(c)" in body, "the caveat sentences render verbatim"
    assert "today" not in body.lower(), "the window ends at the spine's newest day"
    assert "esc(w.since || " in body and "esc(w.until || " in body
    assert "esc(s.label || " in body, "the writer's label line renders verbatim"
    assert 'tabindex="0"' in body and 'data-ev="${i}"' in body
    # the ring reads the map's own cells source - cells.geojson stays ONE fetch - and
    # clears itself; the wiring (mouseover/focusin and their clears) is app.js's
    loc = ins.split("export function locateEvent(i)", 1)[1].split("\n}", 1)[0]
    assert 'map.getSource("cells")' in loc and "serialize" in loc
    assert 'setLayoutProperty("locate", "visibility", "none")' in loc
    app = module_js()["app.js"]
    # mouseleave, NOT mouseout (frontend3 02): mouseout bubbles from every child-to-child
    # move inside the list, so each row-to-row hover cleared and re-set the locate ring.
    # The PAIR is the contract - set on enter (mouseover/focusin), cleared on leave.
    for wire in ('$("recent").addEventListener("mouseover"',
                 '$("recent").addEventListener("mouseleave"',
                 '$("recent").addEventListener("focusin"',
                 '$("recent").addEventListener("focusout"'):
        assert wire in app, wire
    leave = app.split('$("recent").addEventListener("mouseleave"', 1)[1].split("\n", 1)[0]
    assert "locateEvent(null)" in leave, "leaving the list clears the ring"
    assert '"mouseout"' not in app, "mouseout churns the ring on every row-to-row move"
    assert "loadRecent();" in app


def test_every_layer_row_carries_one_plain_rider_sentence():
    """D7's rider surface: ONE sentence per source, visible in both views, under the
    layer's name in its own row. The live fleet is the one exception - its row IS the
    Live panel, which carries its own prose. The sentences are the page's own copy
    (descriptive, no claim a caveat does not already make); the frozen strings still
    come from the payloads.
    MUTATION KILLED: dropping the render from rowHTML (the sentences become dead data),
    or shipping a layer with no rider sentence."""
    entries = layer_entries(page_js())
    for lid, e in entries.items():
        if lid == "live":
            continue
        assert re.search(r'sub: "', e), f"{lid} has no one-sentence rider description"
    row = page_js().split("function rowHTML", 1)[1].split("\n}", 1)[0]
    assert "lyr.sub" in row and 'class="note sub"' in row


# ==================================== frontend3 02: map-first chrome ======================
def test_the_info_control_is_a_native_dialog_and_everything_moved_in_is_still_there():
    """The provenance/licence slab collapses behind the credit strip's info button - a
    native <dialog> (platform focus trap, Esc, ::backdrop), NEVER a second <details>: the
    analyst disclosure stays the page's ONE disclosure and the count test above holds at 1.
    The dialog sits BEFORE #provenance in source order, so the strip's bounded containment
    slices can never be satisfied from inside it. Collapse, never delete: every sentence
    the slab held is in the dialog - including the "nycbuspositions archive" credit, whose
    ONLY other home was the deleted AttributionControl (removed in the same commit).
    MUTATION KILLED: a second <details> as the info control; the dialog placed after the
    strip; deleting (rather than moving) the pipeline sentence, the MTA non-affiliation
    paragraph, the Produced-Work text, the snapshot-only sentence or the archive credit."""
    html = page_html()
    assert html.count("<dialog") == 1 and 'id="info"' in html
    assert html.index("<dialog") < html.index('id="provenance"'), (
        "the dialog precedes the strip, so the strip slice cannot contain it")
    block = html.split("<dialog", 1)[1].split("</dialog>", 1)[0]
    for s_ in ("Kafka 3.9", 'id="prov-files"', "nycbuspositions archive",
               'id="mta-gate"', "Produced Work", "SIL Open Font License",
               'id="attribution"', "affiliated with, endorsed by, or a service of the MTA",
               "Current snapshot only", "no bulk or protobuf",
               "rain: AORC hourly, hour-ending",
               "Each row is one data source and its chip says how current it is"):
        assert s_ in block, s_
    app = module_js()["app.js"]
    assert '$("info").showModal()' in app, "opened as a MODAL dialog, wired in app.js"
    # the CALL, not the word - the comment explaining the removal names the control
    # (the docstring-poisons-the-grep trap, anchored on the code per TRAPS)
    assert "new maplibregl.AttributionControl" not in app, (
        "the compact control rendered EXPANDED over the 375px map strip; the fixed strip "
        "carries the OSMF adjacency at every width now")
    strip = html.split('id="provenance"')[1].split("</footer>")[0]
    assert "Not an MTA service." in strip, "the visible non-affiliation shorthand"
    assert 'id="info-btn"' in strip


def test_an_open_row_detail_is_module_state_that_survives_the_rebuilds():
    """renderLayers() rewrites the rows' innerHTML on six events - every toggle, view
    switch, hour switch, scenario change, boot, and every 30 s while the live toggle is on
    - so a detail whose open state lived in the DOM would slam shut on each of them. The
    state is panel.js's `openDet` Set; rowHTML() re-emits hidden/aria-expanded FROM it,
    the delegated click lives in app.js (the cyclic-module rule), the focus restore grows
    a data-det case, and the STATIC live row's detail follows the same Set.
    MUTATION KILLED: emitting the detail unconditionally hidden (openDet unread - an hour
    switch closes every open detail); wiring the chevron inside panel.js; dropping the
    live row's sync; or losing the chevron's focus across a rebuild."""
    js = page_js()
    row = js.split("function rowHTML", 1)[1].split("\n}", 1)[0]
    assert "openDet.has(lyr.id)" in row, "the open state is read from the module Set"
    assert "aria-expanded=" in row
    panel = module_js()["panel.js"]
    assert "export const openDet = new Set()" in panel
    render = panel.split("export function renderLayers()", 1)[1].split("\n}", 1)[0]
    assert '$("det-live").hidden = !openDet.has("live");' in render, "the static live row"
    assert "a.dataset.det" in render, "focus returns to the chevron after a rebuild"
    app = module_js()["app.js"]
    assert "toggleDet(" in app, "the chevron click is delegated from the entry module"


def test_the_legend_shows_while_a_ramp_is_on_screen_and_only_toggles_hidden():
    """Owned by applyRamp(), which already computes the value: `fillOn || ramped` - NOT
    "while a fill is lit", which would hide the key in exactly the state the None row
    exists to reach (fill off, zones/routes carrying the same ramp - D1's other half).
    Only `hidden` is toggled: paint() writes into the legend's five ids unconditionally,
    so destroy-and-recreate throws on the next view switch.
    MUTATION KILLED: keying the legend on the fill alone, or removing a legend id."""
    body = page_js().split("export function applyRamp()", 1)[1].split("\n}", 1)[0]
    assert '$("legend").hidden = !(fillOn || ramped);' in body
    html = page_html()
    for el in ("legend-title", "swatches", "tick-lo", "tick-mid", "tick-hi"):
        assert f'id="{el}"' in html, el


def test_the_page_ships_a_favicon_as_a_site_key():
    """/favicon.ico 404'd on every load of the public page and Cloudflare's 404 body cost
    ~6.8 KB a time (frontend2 06 filed it; frontend3 02 owns it). The icon is a `site`
    key, so it publishes with the page - additive under contract.PROMISE[1], no bump -
    and the <link> is what stops the automatic /favicon.ico probe.
    MUTATION KILLED: the file without the key (never reaches the host), or the key
    without the link (the /favicon.ico 404 continues)."""
    assert "favicon.svg" in publish.FAMILIES["site"].files
    assert (web() / "favicon.svg").is_file()
    assert '<link rel="icon" href="favicon.svg" type="image/svg+xml">' in page_html()


# ============================== frontend4 02: hover labels on the point layers ============
def test_the_four_point_layers_get_a_mousemove_click_and_mouseleave_tip_in_app_js_only():
    """One mechanism (insight.pointTip), wired for `hist`, `subway`, `mta`, `fn` - the
    layers that answered only to click (hist's own card) or not at all. Click is the touch
    path, the cells tooltip's own pattern this ticket reuses. Wiring stays in app.js ONLY
    (the ES-module-cycle rule test_only_the_boot_module_wires_the_dom_and_the_map already
    enforces for insight.js as a whole); this test pins the four-layer COUNT so dropping one
    layer from the loop cannot pass silently.
    MUTATION KILLED: dropping one layer's mouseleave (or the whole loop) - three of the four
    point layers would stay permanently mute or leave a stuck tip on the map."""
    boot = module_js()["app.js"]
    assert 'import { applyRamp, closeCard, loadRecent, locateEvent, pointTip,' in boot
    loop = boot.split('for (const id of ["hist", "subway", "mta", "fn"]) {', 1)[1] \
               .split("\n}", 1)[0]
    assert 'map.on("mousemove", id, tip)' in loop
    assert 'map.on("click", id, tip)' in loop
    assert 'map.on("mouseleave", id,' in loop
    # hist's own click -> showCard registration follows the loop, so a hist tap's final
    # state is the card open and the tip hidden, never a stale tip stacked on the card
    assert boot.index('for (const id of ["hist"') < boot.index('map.on("click", "hist"')
    assert "export function pointTip(layerId)" not in boot, "pointTip is defined in insight.js"
    assert "export function pointTip(layerId)" in module_js()["insight.js"]


def test_the_hist_tip_falls_back_to_the_asset_id_and_the_id_always_prints():
    """`name` is an ABSENT key (not null) on all 1,276 cell-kind features in
    files/history/manifest.geojson, so a title of `p.name` alone renders the literal word
    "undefined". The sub line prints the id unconditionally - names are not unique at any
    grain ("86 St" names six complexes; two bus stops share one name metres apart).
    MUTATION KILLED: `p.name` alone (renders "undefined" on every Cell-kind marker), or
    dropping `p.asset_id` from the sub line."""
    js = page_js()
    entry = js.split("hist: (p) =>", 1)[1].split("subway:", 1)[0]
    assert "p.name || p.asset_id" in entry, "the fallback is a source-shape assertion"
    assert "p.asset_id" in entry.split("<br>", 1)[1], "the id prints beside the name"
    assert "p.n_events" in entry


def test_every_tips_entry_escapes_its_untrusted_strings():
    """Every TIPS render routes a name or a published sentence through esc() - never a raw
    innerHTML interpolation - because a GTFS-registry name or a FloodNet `label` sentence is
    the one kind of string on this page that crosses a trust boundary (the showTip/showCard/
    eventHTML pattern this ticket reuses, never introduces).
    MUTATION KILLED: interpolating `p.name` or `p.label` directly (`${p.name}`) instead of
    through esc(p.name) in any one TIPS entry."""
    js = page_js()
    tips = js.split("export const TIPS = {", 1)[1].split("\n};", 1)[0]
    assert tips.count("esc(p.name") == 4, "hist/subway/mta/fn each escape a name"
    assert "esc(p.asset_id)" in tips and "esc(p.kind)" in tips
    assert "esc(p.complex_id)" in tips and "esc(p.state)" in tips
    assert "esc(p.label)" in tips, "the published FloodNet sentence is escaped, not raw"
    assert "${p.name}" not in tips and "${p.label}" not in tips, "no raw interpolation"


def test_the_subway_tip_reads_rel_only_when_the_key_is_present():
    """`rel` rides only when the payload carried it (absent below `min_planned`, not zero -
    live.js's own feature rebuild already guards this the same way at `"rel" in c`), so the
    tip's rel line must read the same guard rather than assume the key.
    MUTATION KILLED: making the rel line unconditional (`lines.push(rel ...)` with no
    guard) - a complex below min_planned would render a stray "rel undefined"."""
    js = page_js()
    entry = js.split("subway: (p) => {", 1)[1].split("\n  },", 1)[0]
    assert '"rel" in p' in entry
    assert "lines.push(`rel ${fmt(p.rel, 2)}`)" in entry
