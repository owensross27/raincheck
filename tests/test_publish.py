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

from raincheck import publish

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
    (files / "live.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (files / "meta.json").write_text(json.dumps(LIVE_META))
    for name in ("index.html", "app.js", "app.css"):
        (tmp_path / name).write_text("x")
    (tmp_path / "vendor").mkdir()
    for name in ("maplibre-gl.js", "maplibre-gl.css"):
        (tmp_path / "vendor" / name).write_text("x")
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
    assert keys == ["files/cells.geojson", "files/headline.json", "files/zones.geojson"]
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
    with pytest.raises(publish.Refused, match="docs, history, insight, live, site"):
        publish.plan("everything", tmp_path)


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
    js = (REPO / "web" / "app.js").read_text()
    rule = js.split("function isStale")[1].split("\n}")[0]
    assert "metaAge(m)" in rule, "isStale no longer dates meta.json - a dead exporter reads live"
    age = js.split("function metaAge")[1].split("\n}")[0]
    assert "Date.parse(m.as_of_utc)" in age and "Infinity" in age  # unparseable is stale
    assert "Math.max(0," in age, "clock skew must err stale, never fresh"
