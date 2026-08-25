"""Cloud ticket 09: the public static host, its five families, and the rules that keep
live.geojson a view of the MTA feed rather than a copy of it.

Seam: `raincheck.publish.plan()` is pure - no network, no credentials, no s3fs - so every
rule below is a data assertion over a tmp_path directory, and `publish()` takes the
transport as an argument so upload ORDER is testable without a bucket.

The page-side halves of this ticket (MTA attribution, and a frozen meta.json reading
STALE) are text assertions on web/, in the style tests/test_live.py established: the page
has no JS test runner, so these catch a deleted rule. The behaviour itself was measured in
a real browser against a frozen meta - see the RUN LOG entry.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from raincheck import contract, publish
import page                       # tests/page.py: the page, read as data

REPO = Path(publish.__file__).parents[2]
LIVE_META = {"as_of_utc": "2026-08-24T04:00:00Z", "source": "live", "error": None,
             "stale": False, "vp_age_s": 20}


@pytest.fixture
def web(tmp_path):
    """A staged `web/` tree: the insight trio and the live pair share one directory,
    exactly as the two writers really leave them."""
    files = tmp_path / "files"
    files.mkdir()
    for name in ("cells.geojson", "headline.json", "zones.geojson"):
        (files / name).write_text('{"type":"FeatureCollection","features":[]}')
    (files / contract.NAME).write_text(json.dumps({"contract": contract.CONTRACT}))
    (files / "live.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (files / "meta.json").write_text(json.dumps(LIVE_META))
    # the `site` family names the page's six ES modules as well as its two vendored files
    # (frontend2 01), so stage what the family says rather than a hand list that goes stale
    for name in publish.FAMILIES["site"].files:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x")
    return tmp_path


@pytest.fixture
def gate_open(monkeypatch):
    monkeypatch.setattr(publish, "LIVE_TERMS_VERIFIED", "2026-01-01: a test, not a verification")


# --- the MTA gate ------------------------------------------------------------------------

def test_live_is_refused_while_the_mta_terms_are_unverified(web):
    """Ross was asked directly on 2026-08-24 and had not verified them, so the shipped
    constant is None and the live family does not publish. This is the ticket's hard
    precondition expressed as code rather than as a note on a page."""
    assert publish.LIVE_TERMS_VERIFIED is None, (
        "the gate was opened without a recorded verification - the constant must carry "
        "the date and what was read")
    with pytest.raises(publish.GateClosed):
        publish.plan("live", web / "files")


def test_the_closed_gate_uploads_nothing_at_all(web):
    """A refusal that has already uploaded half a pair is not a refusal."""
    sent = []
    with pytest.raises(publish.GateClosed):
        publish.publish("live", web / "files", dest="raincheck-public",
                        put=lambda item, dest: sent.append(item))
    assert sent == []


def test_the_closed_gate_is_rc_3_and_the_other_families_still_ship(web):
    """rc 3 is a designed state - cloud 05's supervisor logs it and carries on - and it
    must not be reachable by anything that is merely broken (that is rc 1)."""
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    live = subprocess.run([sys.executable, "-m", "raincheck.publish", "--family", "live",
                           "--src", str(web / "files"), "--dry-run"],
                          capture_output=True, text=True, env=env)
    assert live.returncode == 3 and "NOT verified" in live.stderr
    site = subprocess.run([sys.executable, "-m", "raincheck.publish", "--family", "site",
                           "--src", str(web), "--dry-run"],
                          capture_output=True, text=True, env=env)
    assert site.returncode == 0, site.stderr
    assert "index.html" in site.stdout and "vendor/maplibre-gl.js" in site.stdout


# --- rule 1: current snapshot only ---------------------------------------------------------

def test_the_live_family_is_two_fixed_keys_and_geojson_goes_first(web, gate_open):
    """No served history: the keys are literals, so no tick can write a dated second copy.
    And the ORDER is the honesty: meta.json carries the freshness the page reads, so a
    publisher that dies mid-pair must leave a fresh fleet under an OLD meta (reads stale),
    never a fresh meta over an old fleet (reads live while the city is frozen)."""
    keys = [i.key for i in publish.plan("live", web / "files")]
    assert keys == ["files/live.geojson", "files/meta.json"]


def test_the_live_keys_do_not_move_when_the_payload_does(web, gate_open):
    """The same two keys for a different snapshot - overwritten in place, never versioned."""
    first = [i.key for i in publish.plan("live", web / "files")]
    (web / "files" / "live.geojson").write_text('{"type":"FeatureCollection","features":[1]}')
    (web / "files" / "meta.json").write_text(json.dumps({**LIVE_META, "as_of_utc": "2026-08-24T04:00:30Z"}))
    assert [i.key for i in publish.plan("live", web / "files")] == first


def test_publish_uploads_in_plan_order(web, gate_open):
    sent = []
    publish.publish("live", web / "files", dest="b", put=lambda item, d: sent.append(item.key))
    assert sent == ["files/live.geojson", "files/meta.json"]


def test_half_a_family_is_refused(web, gate_open):
    """Publishing live.geojson without its meta.json leaves the page reading the previous
    meta's freshness over a new fleet - the same lie the ordering rule prevents."""
    (web / "files" / "meta.json").unlink()
    with pytest.raises(publish.Refused, match="incomplete"):
        publish.plan("live", web / "files")


# --- rule 2: no bulk or protobuf endpoint --------------------------------------------------

def test_a_protobuf_or_parquet_in_a_published_tree_is_refused(web, tmp_path):
    """The allowlist is what makes a bulk endpoint impossible to create by accident -
    including by a later writer staging feed bytes into a directory family."""
    docs = tmp_path / "data_docs"
    docs.mkdir()
    (docs / "index.html").write_text("<html>")
    (docs / "raw.pb").write_bytes(b"\x08\x01")
    with pytest.raises(publish.Refused, match="not a publishable web payload"):
        publish.plan("docs", docs)
    (docs / "raw.pb").unlink()
    (docs / "vp.parquet").write_bytes(b"PAR1")
    with pytest.raises(publish.Refused, match="not a publishable web payload"):
        publish.plan("docs", docs)


def test_the_insight_family_never_sweeps_up_the_live_pair(web):
    """The two families share `web/files/`, so a directory sync would publish live.geojson
    on every build - straight past the gate above - and would republish a stale live pair
    under a fresh insight build. Families name their files for exactly this reason."""
    keys = [i.key for i in publish.plan("insight", web / "files")]
    assert keys == ["files/cells.geojson", "files/headline.json", "files/zones.geojson",
                    "files/index.json"]
    assert not any("live.geojson" in k or "meta.json" in k for k in keys)


# --- the bucket: public and the archive can never be the same mistake ----------------------

def test_the_serve_bucket_is_never_the_archive(monkeypatch):
    monkeypatch.setenv("RAINCHECK_R2_SERVE_BUCKET", "raincheck-bronze")
    with pytest.raises(publish.Refused, match="never be raincheck-bronze"):
        publish.bucket()
    monkeypatch.setenv("RAINCHECK_R2_SERVE_BUCKET", "raincheck-public-2")
    assert publish.bucket() == "raincheck-public-2"
    monkeypatch.delenv("RAINCHECK_R2_SERVE_BUCKET")
    assert publish.bucket() == publish.PUBLIC_BUCKET


def test_the_bucket_name_matches_the_serve_service_accounts_annotation():
    """cloud 07 scoped the serve R2 token to ONE bucket by SA annotation, and this module
    writes to a name of its own. Renaming either one alone would point the publisher at a
    bucket the token cannot reach - a failure that would otherwise appear as a 403 on the
    first publish, weeks later."""
    sas = [d for d in yaml.safe_load_all((REPO / "deploy" / "k8s" / "serviceaccounts.yaml").read_text())
           if d and d.get("kind") == "ServiceAccount"]
    annotated = {sa["metadata"]["name"]: sa["metadata"]["annotations"]["raincheck.io/r2-bucket"]
                 for sa in sas}
    assert annotated["raincheck-serve"] == publish.PUBLIC_BUCKET
    assert annotated["raincheck-serve"] != annotated["raincheck-build"] != ""


# --- cache-control: a CDN must not outlive the exporter ------------------------------------

def test_the_live_pair_is_no_cache_and_the_vendored_page_is_not(web, gate_open):
    """A cached live.geojson is a frozen city served under a fresh-looking page - the T14
    failure with a CDN in front of it. The page and its pinned MapLibre can sit for a day."""
    assert {i.cache for i in publish.plan("live", web / "files")} == {"no-cache"}
    assert {i.cache for i in publish.plan("site", web)} == {publish.RARE_CACHE}
    assert {i.cache for i in publish.plan("insight", web / "files")} == {publish.BUILD_CACHE}


def test_geojson_gets_a_content_type_a_browser_understands(web, gate_open):
    types = {Path(i.key).name: i.content_type for i in publish.plan("insight", web / "files")}
    assert types["cells.geojson"] == "application/geo+json"
    assert types["headline.json"] == "application/json"
    assert publish.content_type(Path("index.html")) == "text/html"


def test_the_transport_sends_the_cache_and_type_it_planned(web, gate_open, monkeypatch):
    """The one part of this module that talks to R2. s3fs forwards these kwargs straight
    into put_object, so a typo in either name would silently publish with no Cache-Control
    at all - which is the difference between a stale panel and a frozen one."""
    calls = []

    class FakeFS:
        def __init__(self, **kw):
            calls.append(("fs", kw))

        def put_file(self, lpath, rpath, **kw):
            calls.append(("put", lpath, rpath, kw))

    monkeypatch.setitem(sys.modules, "s3fs", type("m", (), {"S3FileSystem": FakeFS}))
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://acct.r2.cloudflarestorage.com")
    publish.publish("live", web / "files", dest="raincheck-public")
    assert calls[0] == ("fs", {"endpoint_url": "https://acct.r2.cloudflarestorage.com"})
    puts = [c for c in calls if c[0] == "put"]
    assert [c[2] for c in puts] == ["raincheck-public/files/live.geojson",
                                    "raincheck-public/files/meta.json"]
    assert puts[0][3] == {"ContentType": "application/geo+json", "CacheControl": "no-cache"}


# --- the families nobody has written yet ---------------------------------------------------

def test_a_family_whose_writer_has_not_shipped_refuses_by_naming_its_writer(tmp_path):
    """GX Data Docs (orch 08) and the per-asset history (notify 05) do not exist yet. The
    refusal has to say who owes the files, or the first operator to run this reads it as a
    broken publisher."""
    for family, owed in (("docs", "orch 08"), ("history", "notify 05")):
        with pytest.raises(publish.Refused) as exc:
            publish.plan(family, tmp_path / "nothing-here")
        assert "nothing to publish" in str(exc.value) and owed in str(exc.value)


def test_an_unknown_family_lists_the_real_ones(tmp_path):
    with pytest.raises(publish.Refused, match="docs, history, insight, live, site, tiles"):
        publish.plan("everything", tmp_path)


# --- frontend2 02: the basemap archive, its own family -------------------------------------

def test_the_basemap_is_its_own_family_and_never_a_site_key(tmp_path):
    """`web/tiles/` is gitignored and the archive is never committed: it is built by an
    operator running `make basemap` and moves on its own cadence, while `site` moves with
    every page deploy. Publishing them together would either strand the page behind a 52 MB
    rebuild or republish a basemap nobody changed.
    MUTATION KILLED: folding `nyc.pmtiles` into the `site` file list (which would also make
    `make publish FAMILY=site` refuse on a checkout that has never run `make basemap`, since
    a family is all-or-none), or pointing `tiles` at `web/` instead of `web/tiles/`."""
    fam = publish.FAMILIES["tiles"]
    assert fam.files == ("nyc.pmtiles",) and fam.prefix == "tiles/"
    assert fam.cache == publish.RARE_CACHE and not fam.gated
    assert fam.cadence == "deploy-time" and "make basemap" in fam.writer
    assert "nyc.pmtiles" not in publish.FAMILIES["site"].files
    assert fam.src().name == "tiles" and fam.src().parent == publish.WEB

    tiles = tmp_path / "tiles"
    tiles.mkdir()
    (tiles / "nyc.pmtiles").write_bytes(b"PMTiles\x03")
    [item] = publish.plan("tiles", tiles)
    assert item.key == "tiles/nyc.pmtiles"
    assert item.content_type == "application/octet-stream"
    assert item.cache == publish.RARE_CACHE


def test_a_missing_basemap_refuses_by_naming_who_builds_it(tmp_path):
    """The archive is gitignored, so a fresh checkout has none - and the operator reading
    the refusal needs the command, not a stack trace."""
    with pytest.raises(publish.Refused) as exc:
        publish.plan("tiles", tmp_path / "tiles")
    assert "incomplete" in str(exc.value) and "nyc.pmtiles" in str(exc.value)


def test_the_allowlist_widened_by_two_web_payload_formats_and_not_by_a_category(tmp_path):
    """Rule 2 is an ALLOWLIST so that a bulk or protobuf endpoint cannot be created by
    accident. frontend2 02 added `.pmtiles` (the basemap archive) and `.pbf` (one font glyph
    range - the same category as the `.woff`/`.otf` faces already there, and the only way
    MapLibre can draw a label). Neither widens the refusal the rule exists for, and this
    test asserts BOTH halves: the two new formats pass, and the formats rule 2 names by
    name are still refused.
    MUTATION KILLED: adding `.pb`, `.parquet` or `.gz` alongside them, or swapping the
    allowlist for a denylist (which would have to predict every bulk format)."""
    assert {".pmtiles", ".pbf"} <= publish.PUBLISHABLE
    for suffix in (".pb", ".parquet", ".tar", ".gz", ".zip", ".db", ".csv"):
        assert suffix not in publish.PUBLISHABLE, suffix
    # and the refusal still fires on a real staged tree, not just on the constant
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.html").write_text("<html>")
    (docs / "vehicles.pb").write_bytes(b"\x00")
    with pytest.raises(publish.Refused, match="not a publishable web payload"):
        publish.plan("docs", docs)


# --- rule 3, and the page's half of STALE (text assertions; the browser check is in the log)

def test_the_page_carries_mta_attribution_where_a_visitor_can_see_it():
    """Attribution is a CONDITION of publishing the live view (spec sec.9), so it lives in
    the always-visible provenance panel - not only in MapLibre's compact control, which
    ships collapsed behind a button."""
    html = (REPO / "web" / "index.html").read_text()
    panel = html.split('id="provenance"')[1]
    assert "MTA" in panel and "GTFS-Realtime" in panel
    assert "not\n  affiliated with, endorsed by, or a service of the MTA" in panel
    assert "Current snapshot only" in html and "no bulk or protobuf" in html


def test_the_page_dates_meta_json_itself_so_a_dead_exporter_cannot_read_live():
    """vp_age_s is a number the exporter froze into the file. Without the age of the FILE,
    a dead exporter (or publisher, or a CDN serving a cached copy) reads as a live city
    forever - measured in a browser: a meta written 21 min ago with vp_age_s=20 painted
    LIVE before this, STALE after, with the healthy cases unchanged."""
    js = page.page_js()
    rule = js.split("function isStale")[1].split("\n}")[0]
    assert "metaAge(m)" in rule, "isStale no longer dates meta.json - a dead exporter reads live"
    age = js.split("function metaAge")[1].split("\n}")[0]
    assert "Date.parse(m.as_of_utc)" in age and "Infinity" in age  # unparseable is stale
    assert "Math.max(0," in age, "clock skew must err stale, never fresh"


# --- frontend 06: the discovery file and the contract integer -----------------------------

def test_the_discovery_file_ships_in_an_explicit_family_list_and_goes_last(web):
    """`files/index.json` is published because `insight` NAMES it, not because anything
    swept `web/files/` - the standing rule this module exists to keep. And it goes LAST,
    for meta.json's reason: it names the three files beside it and the universe that
    stamped them, so an interrupted publish must leave an OLD contract over new payloads,
    never a new contract over payloads that are not there yet."""
    assert "index.json" in publish.FAMILIES["insight"].files
    assert publish.FAMILIES["insight"].files[-1] == "index.json"
    sent = []
    publish.publish("insight", web / "files", dest="b", put=lambda i, d: sent.append(i.key))
    assert sent[-1] == "files/index.json"
    assert [i.cache for i in publish.plan("insight", web / "files")][-1] == publish.BUILD_CACHE


def test_a_build_without_its_discovery_file_is_refused(web):
    """All four or none. A build that published three payloads and no index.json would
    leave a consumer reading the PREVIOUS build's contract - which is the state the
    integer exists to make impossible."""
    (web / "files" / contract.NAME).unlink()
    with pytest.raises(publish.Refused, match="incomplete"):
        publish.plan("insight", web / "files")


def test_the_contract_integer_covers_the_surface_a_consumer_binds_to():
    """THE contract rule, and it is a SUBSET check rather than a digest on purpose.

    `PROMISE[CONTRACT]` is the frozen (family, key, content type) surface this contract
    promised. Removing a key, renaming one, moving it between families or changing its
    content type stops the promise being a subset of what publish.FAMILIES renders today,
    and this test demands the bump. ADDING a family or a key is additive - existing
    consumers keep working - so it stays green, which a digest could not do.

    Mutation-checked (see the RUN LOG entry): dropping headline.json, renaming
    cells.geojson, moving a key between families and changing the .geojson content type
    each turned this RED; adding a new key left it green."""
    missing = contract.PROMISE[contract.CONTRACT] - contract.surface()
    assert not missing, (
        f"BREAKING: contract {contract.CONTRACT} promised {sorted(missing)} and the "
        "publisher no longer renders it. Add a new PROMISE entry beside the old one, "
        "bump contract.CONTRACT, and update docs/read-api-contract.md - in one commit.")


def test_every_contract_ever_promised_is_still_frozen_beside_the_current_one():
    """An edited promise is a contract nobody can audit: the whole value of the integer is
    that a consumer can read what version N meant. Old entries stay; the current one is
    the highest."""
    assert contract.CONTRACT == max(contract.PROMISE)
    assert set(contract.PROMISE) == set(range(1, contract.CONTRACT + 1))


def test_the_promise_names_real_keys_and_the_surface_is_derived_not_copied():
    """The promise is hand-frozen, so it could name a key that never existed; the surface
    is derived from publish.FAMILIES, so it cannot. Cross-check them both ways: every
    promised explicit key is a real file in its family, and every family the publisher has
    is on the surface."""
    for family, key, _ in contract.PROMISE[contract.CONTRACT]:
        fam = publish.FAMILIES[family]
        assert key.startswith(fam.prefix)
        tail = key[len(fam.prefix):]
        assert tail in fam.files if fam.files else tail == "**"
    assert {f for f, _, _ in contract.surface()} == set(publish.FAMILIES)


def test_the_written_contract_document_exists_and_tracks_the_integer():
    """The doc is the human half of the same contract, and a bump that does not reach it
    leaves a consumer reading last version's promise in prose. The expected string is
    DERIVED from the constant, so this cannot pass by mirroring itself."""
    doc = (REPO / contract.DOC).read_text()
    assert f"contract {contract.CONTRACT}" in doc
    for name in publish.FAMILIES:
        assert f"`{name}`" in doc, f"the contract document does not describe family {name}"
    for _, key, _ in contract.PROMISE[contract.CONTRACT]:
        assert key in doc, f"the contract document does not name promised key {key}"
    # the four things the decision made this document responsible for saying
    assert "custom Cloudflare domain" in doc and "load-bearing" in doc
    assert "refused" in doc and "frozen-age trap" in doc         # the build-time merge
    assert "<response `Date`> − <response `Last-Modified`>" in doc   # the reader dates the file
    assert "NOT a consumer" in doc and "never be wired as one" in doc
