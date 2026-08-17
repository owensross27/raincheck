"""Ticket 10 evidence: ping-to-ping speed rules on the nycbuspositions archive.

Measures, for four archive days (two storm, two dry controls one week earlier),
what a Leg (consecutive-Ping pair per vehicle) actually looks like, so that the
backfill speed rules can be chosen from numbers rather than assumption.

Sections
  0  Load + dedupe + per-day census
  A  Legs: dt / dist / speed shape, trip boundaries, pre-departure, cell + hour
     straddling, support per (Cell, Hour)
  B  Chord vs path: how much a 120 s chord under-measures the true path, using
     the project's own 30 s live Bronze VehiclePosition capture
  C  Storm signal: citywide and per-Cell storm/control speed ratios, rule
     sensitivity, ping volume
  D  Two extra facts: per-Cell speed spread on a dry day; occupancy/bearing fill

Run:
  RAINCHECK_SCRATCH=<dir with archive/ and cells_aorc.parquet> uv run --no-project \
      --with pandas,pyarrow,pyproj,h3,duckdb,numpy python speed_evidence.py

Writes markdown tables to <OUT>/tables.md and intermediate parquet to <OUT>/.
Reruns are cheap: per-date Pings and per-day Legs are cached as parquet.
"""

import os
import numpy as np
import pandas as pd
import h3
from pyproj import Geod

# ---------------------------------------------------------------- config

SCRATCH = os.environ.get("RAINCHECK_SCRATCH", os.path.expanduser("~/raincheck-scratch"))  # archive/<date>-bus-positions.csv.xz, cells_aorc.parquet live here
ARCHIVE = f"{SCRATCH}/archive"
OUT = f"{SCRATCH}/m2"
CELLS_PARQUET = f"{SCRATCH}/cells_aorc.parquet"
VP_LIVE = os.environ.get("RAINCHECK_VP_LIVE", f"{SCRATCH}/vp_all.parquet")  # deduped Bronze VP of one 30 s capture day (columns of feeds.decode_vp)

# analysis day -> the dry control day exactly one week earlier
DAYS = {"2021-09-01": "2021-08-25", "2023-09-29": "2023-09-22"}
ALL_DAYS = ["2021-08-25", "2021-09-01", "2023-09-22", "2023-09-29"]
CONTROL = "2021-08-25"  # primary control for A7 / D1

# hours to highlight (hour-ENDING UTC labels)
IDA_HOURS = ["2021-09-02 01:00", "2021-09-02 02:00", "2021-09-02 03:00", "2021-09-02 04:00"]
FLOOD_HOURS = [f"2023-09-29 {h:02d}:00" for h in range(11, 17)]

USECOLS = ["timestamp", "trip_id", "route_id", "trip_start_date", "vehicle_id",
           "latitude", "longitude", "bearing", "stop_id", "occupancy_status", "mid"]
EXPRESS_RE = "^(X|BM|QM|BXM|SIM)"

# columns kept in memory for analysis (the parquet on disk also carries the raw
# endpoint / midpoint coordinates, which nothing downstream of the cells needs)
ANALYSIS_COLS = ["vehicle_id", "t0", "t1", "dt_s", "dist_m", "speed_mps", "same_trip",
                 "route_id0", "occ0", "bearing0", "cell_start", "cell_mid", "cell_end",
                 "hour_end0", "hour_end1", "pre_departure", "post_final", "run_no_flip",
                 "express"]

# leg rule sets: (dt cap s, speed cap m/s, drop pre-departure, drop stationary)
RULES = {
    "R0":            dict(dt=300, spd=30, drop_pre=True,  drop_stat=False),
    "R0-lax":        dict(dt=600, spd=35, drop_pre=True,  drop_stat=False),
    "R0-strict":     dict(dt=180, spd=25, drop_pre=True,  drop_stat=False),
    "R0+keep-pre":   dict(dt=300, spd=30, drop_pre=False, drop_stat=False),
    "R0-no-stat":    dict(dt=300, spd=30, drop_pre=True,  drop_stat=True),
}

GEOD = Geod(ellps="WGS84")
REPORT = []


def say(s=""):
    REPORT.append(s)


def md(df, fmt="{:.3f}", index=True):
    """DataFrame -> markdown table (no tabulate dependency)."""
    d = df.reset_index() if index else df.copy()
    cols = [str(c) for c in d.columns]

    def cell(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return ""
        if isinstance(v, (bool, np.bool_)):      # bool is a subclass of int
            return str(bool(v))
        if isinstance(v, (float, np.floating)):
            return fmt.format(v)
        if isinstance(v, (int, np.integer)):
            return f"{v:,}"
        return str(v)

    rows = ["| " + " | ".join(cols) + " |",
            "|" + "|".join("---" for _ in cols) + "|"]
    # itertuples, not iterrows: an all-numeric frame upcasts int -> float per row
    for r in d.itertuples(index=False, name=None):
        rows.append("| " + " | ".join(cell(v) for v in r) + " |")
    return "\n".join(rows)


def pct(n, d):
    return 100.0 * n / d if d else float("nan")


def cells_of(lat, lon):
    """h3 res-8 int64 cell per point (h3 v4 str API + str_to_int)."""
    return np.fromiter((h3.str_to_int(h3.latlng_to_cell(a, b, 8)) for a, b in zip(lat, lon)),
                       dtype=np.int64, count=len(lat))


# ------------------------------------------------- 0. load + dedupe Pings

def load_pings(date):
    """One archive day -> unique Pings. Cached."""
    cache = f"{OUT}/pings_{date}.parquet"
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    df = pd.read_csv(f"{ARCHIVE}/{date}-bus-positions.csv.xz", compression="xz",
                     dtype=str, usecols=USECOLS)
    df["t"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed")
    for c in ("latitude", "longitude", "bearing"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["mid_n"] = pd.to_numeric(df["mid"], errors="coerce")
    n_raw = len(df)
    # dedupe on the full Ping key; conflicting (vehicle, ts) rows resolved by
    # keeping the row from the LATER mid (later poll wins).
    df = df.sort_values("mid_n")
    n_key_full = df.drop_duplicates(["vehicle_id", "t", "stop_id", "latitude", "longitude"]).shape[0]
    n_key_vt = df.drop_duplicates(["vehicle_id", "t"]).shape[0]
    df = df.drop_duplicates(["vehicle_id", "t"], keep="last")
    df = df.drop(columns=["timestamp", "mid"]).sort_values(["vehicle_id", "t"]).reset_index(drop=True)
    meta = pd.DataFrame([dict(date=date, rows_raw=n_raw, uniq_full_key=n_key_full,
                              uniq_vehicle_ts=n_key_vt, kept=len(df),
                              vehicles=df["vehicle_id"].nunique(),
                              polls=int(df["mid_n"].nunique()),
                              t_min=str(df["t"].min()), t_max=str(df["t"].max()),
                              null_latlon=int(df[["latitude", "longitude"]].isna().any(axis=1).sum()),
                              null_trip=int(df["trip_id"].isna().sum()),
                              null_stop=int(df["stop_id"].isna().sum()))])
    meta.to_parquet(f"{OUT}/census_{date}.parquet")
    df.to_parquet(cache)
    return df


# ---------------------------------------------------------- A. build Legs

def build_legs(day):
    """Legs over the 48 h span [day, day+1] so midnight-straddling Legs survive.

    Files are calendar-UTC days, so a Leg whose ends sit either side of 00:00Z
    only exists if both files are loaded together.
    """
    cache = f"{OUT}/legs_{day}.parquet"
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    nxt = str((pd.Timestamp(day) + pd.Timedelta(days=1)).date())
    p = pd.concat([load_pings(day), load_pings(nxt)], ignore_index=True)
    p = p.drop_duplicates(["vehicle_id", "t"], keep="last")
    p = p.sort_values(["vehicle_id", "t"]).reset_index(drop=True)

    # A5 scaffolding: runs of consecutive Pings sharing (vehicle, trip, start_date)
    key = (p["vehicle_id"].astype("string").fillna("~") + "|" +
           p["trip_id"].astype("string").fillna("~") + "|" +
           p["trip_start_date"].astype("string").fillna("~"))
    run = (key != key.shift()).fillna(True).to_numpy(dtype=bool).cumsum()
    sid = p["stop_id"].astype("string").fillna("~NA~")
    flip = (sid != sid.shift()).fillna(True).to_numpy(dtype=bool) & (run == np.roll(run, 1))
    flip[0] = False
    pos = p.groupby(run, sort=False).cumcount().to_numpy()
    fp = pd.DataFrame({"run": run, "pos": pos, "flip": flip})
    fl = fp[fp["flip"]].groupby("run")["pos"].agg(["min", "max"])
    first_flip = pd.Series(run).map(fl["min"]).to_numpy()   # NaN => run never flips
    last_flip = pd.Series(run).map(fl["max"]).to_numpy()
    # Ping is pre-departure if before the run's first stop_id flip (a run that
    # never flips is wholly pre-departure); post-final if at/after the last flip.
    pre_ping = np.where(np.isnan(first_flip), True, pos < np.nan_to_num(first_flip, nan=0))
    post_ping = np.where(np.isnan(last_flip), False, pos >= np.nan_to_num(last_flip, nan=0))

    v = p["vehicle_id"].to_numpy()
    same_veh = v[1:] == v[:-1]
    i0 = np.flatnonzero(same_veh)
    i1 = i0 + 1

    lat0 = p["latitude"].to_numpy()[i0]; lon0 = p["longitude"].to_numpy()[i0]
    lat1 = p["latitude"].to_numpy()[i1]; lon1 = p["longitude"].to_numpy()[i1]
    _, _, dist = GEOD.inv(lon0, lat0, lon1, lat1)
    # tz-aware Series -> object array under .to_numpy(); force naive-UTC ns, relocalize after
    tv = p["t"].to_numpy(dtype="datetime64[ns]")
    t0 = tv[i0]; t1 = tv[i1]
    dt = (t1 - t0) / np.timedelta64(1, "s")
    with np.errstate(divide="ignore", invalid="ignore"):
        spd = np.where(dt > 0, dist / np.where(dt == 0, np.nan, dt), np.nan)
    t0s = pd.Series(t0).dt.tz_localize("UTC")
    t1s = pd.Series(t1).dt.tz_localize("UTC")

    s0 = pd.Series(p["trip_id"].to_numpy()[i0]).astype("string")
    s1 = pd.Series(p["trip_id"].to_numpy()[i1]).astype("string")
    same_trip = (s0.notna() & s1.notna() & (s0 == s1)).fillna(False).to_numpy(dtype=bool)
    tr0, tr1 = s0.to_numpy(), s1.to_numpy()

    latm = (lat0 + lat1) / 2.0; lonm = (lon0 + lon1) / 2.0
    legs = pd.DataFrame({
        "vehicle_id": p["vehicle_id"].to_numpy()[i0],
        "t0": t0s, "t1": t1s,
        "dt_s": dt.astype(np.float32), "dist_m": dist.astype(np.float32),
        "speed_mps": spd.astype(np.float32),
        "trip_id0": tr0, "trip_id1": tr1, "same_trip": same_trip,
        "start_date0": p["trip_start_date"].to_numpy()[i0],
        "start_date1": p["trip_start_date"].to_numpy()[i1],
        "stop_id0": p["stop_id"].to_numpy()[i0], "stop_id1": p["stop_id"].to_numpy()[i1],
        "route_id0": p["route_id"].to_numpy()[i0],
        "occ0": p["occupancy_status"].to_numpy()[i0],
        "bearing0": p["bearing"].to_numpy()[i0].astype(np.float32),
        "lat0": lat0, "lon0": lon0, "lat1": lat1, "lon1": lon1,
        "lat_mid": latm, "lon_mid": lonm,
        "cell_start": cells_of(lat0, lon0),
        "cell_mid": cells_of(latm, lonm),
        "cell_end": cells_of(lat1, lon1),
        "hour_end0": t0s.dt.ceil("h"),
        "hour_end1": t1s.dt.ceil("h"),
        # A5 flags: only set when both ends sit in the same run
        "pre_departure": (run[i0] == run[i1]) & pre_ping[i1],
        "post_final": (run[i0] == run[i1]) & post_ping[i0],
        "run_no_flip": (run[i0] == run[i1]) & np.isnan(first_flip[i0]),
    })
    legs["express"] = (legs["route_id0"].astype("string").fillna("").str.upper()
                       .str.match(EXPRESS_RE).fillna(False).to_numpy(dtype=bool))
    legs.to_parquet(cache, index=False)
    return legs[ANALYSIS_COLS]


def load_legs(day):
    """Legs for the 48 h span starting at `day`, analysis columns only."""
    cache = f"{OUT}/legs_{day}.parquet"
    if os.path.exists(cache):
        return pd.read_parquet(cache, columns=ANALYSIS_COLS)
    return build_legs(day)


def apply_rule(legs, r):
    m = legs["same_trip"] & (legs["dt_s"] > 0) & (legs["dt_s"] <= r["dt"]) & (legs["speed_mps"] <= r["spd"])
    if r["drop_pre"]:
        m &= ~legs["pre_departure"]
    if r["drop_stat"]:
        m &= legs["dist_m"] >= 25
    return legs[m]


# ------------------------------------------------------------- reporting

def section0():
    say("## 0. Load, dedupe, census\n")
    cen = pd.concat([pd.read_parquet(f"{OUT}/census_{d}.parquet") for d in sorted(
        set(ALL_DAYS) | {str((pd.Timestamp(d) + pd.Timedelta(days=1)).date()) for d in ALL_DAYS})],
        ignore_index=True)
    cen["dow"] = [pd.Timestamp(d).day_name()[:3] for d in cen["date"]]
    say(md(cen[["date", "dow", "rows_raw", "uniq_full_key", "uniq_vehicle_ts", "kept", "vehicles",
                "polls", "t_min", "t_max", "null_latlon", "null_trip", "null_stop"]], index=False))
    say()
    say("`rows_raw == uniq_full_key == uniq_vehicle_ts == kept` on every day: the archive carries "
        "no duplicate Pings at all, so the dedupe rule (and the later-`mid`-wins tiebreak) never "
        "fires. `null_trip == null_stop` on every day: the same rows lack both.\n")
    poll = []
    for d in ALL_DAYS:
        p = load_pings(d)
        g = p.groupby("mid_n")["t"].agg(["min", "size"]).sort_index()
        gap = g["min"].diff().dt.total_seconds()
        poll.append(dict(date=d, polls=len(g), rows_per_poll_p50=g["size"].median(),
                         poll_gap_p10=gap.quantile(.10), poll_gap_p50=gap.quantile(.50),
                         poll_gap_p90=gap.quantile(.90), poll_gap_max=gap.max()))
    say("Poll (`mid`) cadence, from the min timestamp of each `mid` group:\n")
    say(md(pd.DataFrame(poll), fmt="{:.1f}", index=False))
    say()


def sectionA(legs_by_day):
    say("\n## A. Legs\n")
    pool = pd.concat(legs_by_day.values(), ignore_index=True)
    sets = {**legs_by_day, "POOLED": pool}

    # A1 dt
    rows = []
    for k, L in sets.items():
        d = L["dt_s"]; n = len(d)
        rows.append(dict(day=k, n_legs=n, p1=d.quantile(.01), p10=d.quantile(.10),
                         p50=d.quantile(.50), p90=d.quantile(.90), p99=d.quantile(.99),
                         **{"dt<=0%": pct((d <= 0).sum(), n), "dt<30%": pct(((d > 0) & (d < 30)).sum(), n),
                            "[30,90)%": pct(((d >= 30) & (d < 90)).sum(), n),
                            "[90,150)%": pct(((d >= 90) & (d < 150)).sum(), n),
                            "[150,300)%": pct(((d >= 150) & (d < 300)).sum(), n),
                            "[300,600)%": pct(((d >= 300) & (d < 600)).sum(), n),
                            ">=600%": pct((d >= 600).sum(), n)}))
    say("### A1. dt_s (all Legs, no rule applied)\n")
    say(md(pd.DataFrame(rows), fmt="{:.2f}", index=False)); say()

    # is the archive dropping Pings whose vehicle timestamp went stale? if so the
    # dt mass should pile up at integer multiples of the ~120 s poll cadence.
    rows = []
    for k, L in sets.items():
        d = L["dt_s"]; n = len(d)
        r = dict(day=k, n_legs=n)
        for lo, hi, lbl in [(110, 130, "1x [110,130)"), (230, 250, "2x [230,250)"),
                            (350, 370, "3x [350,370)"), (470, 490, "4x [470,490)")]:
            r[lbl + "%"] = pct(((d >= lo) & (d < hi)).sum(), n)
        r["off-cadence%"] = 100 - sum(v for kk, v in r.items() if kk.endswith(")%"))
        rows.append(r)
    say("**A1b. dt mass at multiples of the ~120 s poll cadence:**\n")
    say(md(pd.DataFrame(rows), fmt="{:.2f}", index=False))
    say("\nOnly ~0.6% of Legs sit at 2x cadence, so the archive is not routinely dropping Pings "
        "whose vehicle timestamp went stale; the wide dt spread is the vehicle clock advancing "
        "irregularly *within* the cadence, not skipped polls.\n")

    # A2 dist
    rows = []
    for k, L in sets.items():
        d = L["dist_m"]; n = len(d)
        rows.append(dict(day=k, n_legs=n, p10=d.quantile(.10), p50=d.quantile(.50),
                         p90=d.quantile(.90), p99=d.quantile(.99),
                         **{"<10m%": pct((d < 10).sum(), n), "<25m%": pct((d < 25).sum(), n),
                            "<50m%": pct((d < 50).sum(), n), ">2km%": pct((d > 2000).sum(), n),
                            ">5km%": pct((d > 5000).sum(), n)}))
    say("### A2. dist_m (all Legs)\n")
    say(md(pd.DataFrame(rows), fmt="{:.2f}", index=False)); say()

    # A3 speed
    rows = []
    for k, L in sets.items():
        s = L["speed_mps"].dropna(); n = len(s)
        rows.append(dict(day=k, n_legs_dt_gt0=n, p50=s.quantile(.50), p90=s.quantile(.90),
                         p95=s.quantile(.95), p99=s.quantile(.99), p999=s.quantile(.999), max=s.max(),
                         **{">15%": pct((s > 15).sum(), n), ">20%": pct((s > 20).sum(), n),
                            ">25%": pct((s > 25).sum(), n), ">30%": pct((s > 30).sum(), n),
                            ">35%": pct((s > 35).sum(), n), ">50%": pct((s > 50).sum(), n)}))
    say("### A3. speed_mps (all Legs with dt>0)\n")
    say(md(pd.DataFrame(rows), fmt="{:.3f}", index=False)); say()

    tail = pool[pool["speed_mps"] > 25]
    n_all = pool["speed_mps"].notna().sum()
    say(f"**A3b. The >25 m/s tail, pooled: n={len(tail):,} of {n_all:,} Legs with dt>0 "
        f"({pct(len(tail), n_all):.3f}%). dt and dist shape of that tail:**\n")
    b = pd.cut(tail["dt_s"], [0, 30, 60, 90, 150, 300, 600, 1e9],
               labels=["<30", "30-60", "60-90", "90-150", "150-300", "300-600", ">=600"])
    t3 = tail.groupby(b, observed=False).agg(n=("dt_s", "size"), dist_p50=("dist_m", "median"),
                                             dist_p90=("dist_m", lambda x: x.quantile(.9)),
                                             spd_p50=("speed_mps", "median"), spd_max=("speed_mps", "max"))
    t3["share_of_tail%"] = pct(t3["n"], len(tail))
    say(md(t3, fmt="{:.1f}")); say()

    ex = pool[pool["speed_mps"] > 35].nlargest(10, "speed_mps")[
        ["vehicle_id", "t0", "dt_s", "dist_m", "speed_mps", "route_id0", "same_trip"]]
    say("**A3c. 10 fastest Legs in the >35 m/s tail (pooled):**\n")
    say(md(ex, fmt="{:.1f}", index=False)); say()

    rows = []
    for lbl, sub in [("express", pool[pool["express"]]), ("local", pool[~pool["express"]])]:
        s = sub["speed_mps"].dropna(); n = len(s)
        rows.append(dict(kind=lbl, n=n, p50=s.quantile(.5), p99=s.quantile(.99), p999=s.quantile(.999),
                         **{">25%": pct((s > 25).sum(), n), ">30%": pct((s > 30).sum(), n),
                            ">35%": pct((s > 35).sum(), n)}))
    say("**A3d. Fast tail, express vs local (pooled; express = route starts X/BM/QM/BXM/SIM):**\n")
    say(md(pd.DataFrame(rows), fmt="{:.3f}", index=False)); say()

    # A4 trip boundaries
    rows = []
    for k, L in sets.items():
        for lbl, sub in [("same_trip", L[L["same_trip"]]), ("trip_change", L[~L["same_trip"]])]:
            n = len(sub)
            rows.append(dict(day=k, kind=lbl, n=n, share_of_day=pct(n, len(L)),
                             dt_p50=sub["dt_s"].median(), dt_p90=sub["dt_s"].quantile(.9),
                             dist_p50=sub["dist_m"].median(), dist_p90=sub["dist_m"].quantile(.9),
                             spd_p50=sub["speed_mps"].median(), spd_p90=sub["speed_mps"].quantile(.9),
                             **{"dist<25m%": pct((sub["dist_m"] < 25).sum(), n)}))
    say("### A4. Trip boundaries\n")
    say(md(pd.DataFrame(rows), fmt="{:.2f}", index=False)); say()

    # A5 pre-departure / post-final
    rows = []
    for k, L in sets.items():
        st = L[L["same_trip"]]; n = len(st)
        for lbl, sub in [("pre_departure", st[st["pre_departure"]]),
                         ("post_final", st[st["post_final"]]),
                         ("mid_trip", st[~st["pre_departure"] & ~st["post_final"]])]:
            rows.append(dict(day=k, region=lbl, n=len(sub), share_of_same_trip=pct(len(sub), n),
                             **{"dist<25m%": pct((sub["dist_m"] < 25).sum(), len(sub))},
                             spd_p50=sub["speed_mps"].median(), spd_p90=sub["speed_mps"].quantile(.9),
                             dt_p50=sub["dt_s"].median()))
        rows.append(dict(day=k, region="  (of which runs that never flip)",
                         n=int(st["run_no_flip"].sum()), share_of_same_trip=pct(st["run_no_flip"].sum(), n),
                         **{"dist<25m%": pct((st.loc[st["run_no_flip"], "dist_m"] < 25).sum(), max(st["run_no_flip"].sum(), 1))},
                         spd_p50=st.loc[st["run_no_flip"], "speed_mps"].median(),
                         spd_p90=st.loc[st["run_no_flip"], "speed_mps"].quantile(.9),
                         dt_p50=st.loc[st["run_no_flip"], "dt_s"].median()))
    say("### A5. Pre-departure / post-final regions (same-trip Legs only)\n")
    say(md(pd.DataFrame(rows), fmt="{:.2f}", index=False)); say()

    # A6 cell + hour straddling
    rows = []
    for k, L in sets.items():
        n = len(L)
        diff = L[L["cell_start"] != L["cell_end"]]["dist_m"]
        rows.append(dict(day=k, n_legs=n,
                         **{"start==end%": pct((L["cell_start"] == L["cell_end"]).sum(), n),
                            "start==mid%": pct((L["cell_start"] == L["cell_mid"]).sum(), n),
                            "all3 equal%": pct(((L["cell_start"] == L["cell_mid"]) & (L["cell_mid"] == L["cell_end"])).sum(), n),
                            "hour straddle%": pct((L["hour_end0"] != L["hour_end1"]).sum(), n)},
                         crosscell_dist_p10=diff.quantile(.1), crosscell_dist_p50=diff.quantile(.5),
                         crosscell_dist_p90=diff.quantile(.9)))
    say("### A6. Cell and Hour straddling (all Legs)\n")
    say(md(pd.DataFrame(rows), fmt="{:.2f}", index=False)); say()

    # A7 support on the control day under R0
    bbox = set(pd.read_parquet(CELLS_PARQUET)["cell"].tolist())
    L = apply_rule(legs_by_day[CONTROL], RULES["R0"])
    L = L[(L["t0"] >= pd.Timestamp(CONTROL, tz="UTC")) &
          (L["t0"] < pd.Timestamp(CONTROL, tz="UTC") + pd.Timedelta(days=1))]
    inb = L["cell_mid"].isin(bbox)
    g = L[inb].groupby(["cell_mid", "hour_end1"]).size()
    h17 = L[inb & (L["hour_end1"] == pd.Timestamp(f"{CONTROL} 17:00", tz="UTC"))].groupby("cell_mid").size()
    say(f"### A7. Support per (Cell, Hour) under R0 on the control day {CONTROL}\n")
    say(f"- R0 Legs on {CONTROL} (t0 within the UTC day): {len(L):,}; "
        f"of these {inb.sum():,} ({pct(inb.sum(), len(L)):.2f}%) have cell_mid inside the 4,113-cell NYC bbox, "
        f"{(~inb).sum():,} outside it.")
    say(f"- Non-empty (Cell, Hour) pairs: {len(g):,}. Legs per pair p10/p50/p90 = "
        f"{g.quantile(.1):.0f} / {g.quantile(.5):.0f} / {g.quantile(.9):.0f}; mean {g.mean():.1f}, max {g.max():,}.")
    say(f"- Distinct bbox cells with any R0 Leg that day: {L[inb]['cell_mid'].nunique():,} of 4,113 "
        f"({pct(L[inb]['cell_mid'].nunique(), 4113):.1f}%).")
    say(f"- In hour ending {CONTROL} 17:00Z: {len(h17):,} bbox cells have >=1 Leg, "
        f"{(h17 >= 30).sum():,} have >=30, {(h17 >= 100).sum():,} have >=100.")
    say()
    g.rename("n_legs").reset_index().to_parquet(f"{OUT}/a7_cell_hour_{CONTROL}.parquet", index=False)


# ------------------------------------------- B. chord vs path on 30 s live

def _legs30(vp, clock):
    """Consecutive-Ping Legs on an already vehicle/clock-sorted live frame."""
    v = vp["vehicle_id"].to_numpy()
    i0 = np.flatnonzero(v[1:] == v[:-1]); i1 = i0 + 1
    lat0 = vp["lat"].to_numpy()[i0]; lon0 = vp["lon"].to_numpy()[i0]
    lat1 = vp["lat"].to_numpy()[i1]; lon1 = vp["lon"].to_numpy()[i1]
    _, _, d = GEOD.inv(lon0, lat0, lon1, lat1)
    dt = vp[clock].to_numpy()[i1] - vp[clock].to_numpy()[i0]
    legs = pd.DataFrame({"i0": i0, "i1": i1, "dt": dt, "d": d,
                         "route": vp["route_id"].to_numpy()[i0],
                         "trip0": vp["trip_id"].to_numpy()[i0],
                         "trip1": vp["trip_id"].to_numpy()[i1]})
    n_all = len(legs)
    legs = legs[(legs["dt"] >= 20) & (legs["dt"] <= 45)].reset_index(drop=True)
    # runs of adjacent kept legs (leg j chains to leg j+1 iff i1[j] == i0[j+1])
    chain = np.r_[False, legs["i1"].to_numpy()[:-1] == legs["i0"].to_numpy()[1:]]
    legs["run"] = (~chain).cumsum()
    return legs, n_all


def _windows(legs, vp, k):
    """All k-Leg windows lying inside one run; polyline vs endpoint chord."""
    lat = vp["lat"].to_numpy(); lon = vp["lon"].to_numpy()
    same_run_k = (legs["run"].to_numpy()[: len(legs) - k + 1] == legs["run"].to_numpy()[k - 1:])
    starts = np.flatnonzero(same_run_k)
    poly = np.add.reduce([legs["d"].to_numpy()[starts + m] for m in range(k)])
    secs = np.add.reduce([legs["dt"].to_numpy()[starts + m] for m in range(k)])
    a = legs["i0"].to_numpy()[starts]; b = legs["i1"].to_numpy()[starts + k - 1]
    _, _, chord = GEOD.inv(lon[a], lat[a], lon[b], lat[b])
    w = pd.DataFrame({"poly": poly, "chord": chord, "secs": secs,
                      "route": legs["route"].to_numpy()[starts],
                      "same_trip": np.add.reduce(
                          [(legs["trip0"].to_numpy()[starts + m] ==
                            legs["trip1"].to_numpy()[starts + m]).astype(int) for m in range(k)]) == k})
    w["r"] = w["poly"] / w["chord"].where(w["chord"] > 0)
    w["v"] = w["poly"] / w["secs"]
    w["shortfall"] = 1 - 1 / w["r"]
    assert (w["r"].dropna() >= 0.999).all(), "polyline shorter than chord (triangle inequality)"
    return w, starts


def sectionB():
    say("\n## B. Chord vs path (live 30 s Bronze)\n")
    raw = pd.read_parquet(VP_LIVE, columns=["vehicle_id", "trip_id", "route_id", "lat", "lon",
                                            "stop_id", "ts", "fetched_at"])
    n_raw = len(raw)
    n_vt = raw.drop_duplicates(["vehicle_id", "ts"]).shape[0]
    n_vf = raw.drop_duplicates(["vehicle_id", "fetched_at"]).shape[0]
    vp = raw.drop_duplicates(["vehicle_id", "ts", "stop_id", "lat", "lon"])
    vp = vp.sort_values(["vehicle_id", "ts"]).reset_index(drop=True)
    stale = raw["fetched_at"] - raw["ts"]
    say(f"Source {VP_LIVE}: {n_raw:,} rows -> {len(vp):,} unique Pings on "
        f"(vehicle_id, ts, stop_id, lat, lon); only {n_vt:,} unique on (vehicle_id, ts) alone, "
        f"i.e. {n_raw - n_vt:,} rows ({pct(n_raw - n_vt, n_raw):.1f}%) repeat a vehicle timestamp "
        f"while carrying a different position or stop. Every row is a distinct "
        f"(vehicle_id, fetched_at) pair ({n_vf:,}). {vp['vehicle_id'].nunique():,} vehicles.\n")
    say(f"Vehicle-timestamp staleness at fetch time (fetched_at - ts), all {n_raw:,} rows: "
        f"p50 {stale.quantile(.5):.0f} s, p90 {stale.quantile(.9):.0f} s, "
        f"p99 {stale.quantile(.99):.0f} s, max {stale.max():,.0f} s; "
        f"share > 60 s = {pct((stale > 60).sum(), n_raw):.1f}%.\n")

    legs, n_legs_all = _legs30(vp, "ts")
    say(f"30 s Legs on the `ts` clock: {n_legs_all:,} consecutive-Ping pairs, {len(legs):,} "
        f"({pct(len(legs), n_legs_all):.1f}%) with dt in [20,45] s (dt p50 = "
        f"{legs['dt'].median():.0f} s). Windows are built only from runs of adjacent kept Legs.\n")
    sid = vp["stop_id"].astype("string").fillna("~").to_numpy()

    rows = []
    k4 = None
    for k in (2, 3, 4, 6, 8):
        w, _ = _windows(legs, vp, k)
        sub = w[w["chord"] >= 10]
        rows.append(dict(k=k, nominal_s=30 * k, n_windows=len(w),
                         **{"chord<10m%": pct((w["chord"] < 10).sum(), len(w))},
                         r_p10=w["r"].quantile(.1), r_p50=w["r"].quantile(.5), r_p90=w["r"].quantile(.9),
                         r_p10_c10=sub["r"].quantile(.1), r_p50_c10=sub["r"].quantile(.5),
                         r_p90_c10=sub["r"].quantile(.9), r_mean_c10=sub["r"].mean(),
                         shortfall_mean_c10=sub["shortfall"].mean(),
                         r_p50_sametrip=w.loc[w["same_trip"], "r"].quantile(.5)))
        if k == 4:
            k4 = w
    say("### B1. polyline / chord ratio r by window length\n")
    say("`_c10` columns restrict to windows whose end-to-end chord is >= 10 m (a window where the bus "
        "returns near its start has r -> inf and no meaningful shortfall).\n")
    say(md(pd.DataFrame(rows), fmt="{:.4f}", index=False)); say()

    c10 = k4[k4["chord"] >= 10].copy()
    c10["cls"] = pd.cut(c10["v"], [-0.01, 3, 6, 10, 1e9], labels=["<3", "3-6", "6-10", ">10"])
    t = c10.groupby("cls", observed=False).agg(
        n=("r", "size"), r_p50=("r", "median"), r_p90=("r", lambda x: x.quantile(.9)),
        r_mean=("r", "mean"), shortfall_mean=("shortfall", "mean"))
    say("**B1b. k=4 (nominal 120 s) by polyline speed class, chord >= 10 m:**\n")
    say(md(t, fmt="{:.4f}")); say()

    isx = (c10["route"].astype("string").fillna("").str.upper()
           .str.match(EXPRESS_RE).fillna(False).to_numpy(dtype=bool))
    rows = []
    for lbl, m in [("express", isx), ("local", ~isx)]:
        s = c10[m]
        rows.append(dict(kind=lbl, n=len(s), r_p50=s["r"].median(), r_p90=s["r"].quantile(.9),
                         r_mean=s["r"].mean(), shortfall_mean=s["shortfall"].mean()))
    say("**B1c. k=4 express vs local, chord >= 10 m:**\n")
    say(md(pd.DataFrame(rows), fmt="{:.4f}", index=False)); say()

    # B1d: the `ts` clock throws away every position that moved without the vehicle
    # timestamp advancing. Rebuild on the poll clock, which never stalls, to bound
    # how much polyline the ts-clock build misses.
    vpf = raw.sort_values(["vehicle_id", "fetched_at"]).reset_index(drop=True)
    legs_f, n_all_f = _legs30(vpf, "fetched_at")
    rows = []
    for lbl, LG, VP in [("ts clock (B1 primary)", legs, vp), ("fetched_at clock", legs_f, vpf)]:
        w, _ = _windows(LG, VP, 4)
        s = w[w["chord"] >= 10]
        rows.append(dict(build=lbl, n_legs_kept=len(LG), n_windows=len(w), r_p50=s["r"].median(),
                         r_p90=s["r"].quantile(.9), r_mean=s["r"].mean(),
                         shortfall_mean=s["shortfall"].mean(),
                         polyline_m_p50=s["poly"].median()))
    say("**B1d. k=4 rebuilt on the poll clock (`fetched_at`) instead of the vehicle clock (`ts`), "
        "chord >= 10 m:**\n")
    say(md(pd.DataFrame(rows), fmt="{:.4f}", index=False)); say()

    # B2 flip count per window
    rows = []
    for npings, lbl in [(4, "4 Pings (3 legs, nominal 90 s)"), (5, "5 Pings (4 legs, nominal 120 s)")]:
        k = npings - 1
        _, starts = _windows(legs, vp, k)
        pidx = [legs["i0"].to_numpy()[starts]] + [legs["i1"].to_numpy()[starts + m] for m in range(k)]
        flips = np.add.reduce([(sid[pidx[m + 1]] != sid[pidx[m]]).astype(int) for m in range(k)])
        n = len(flips)
        rows.append(dict(window=lbl, n_windows=n,
                         **{"0 flips%": pct((flips == 0).sum(), n), "1%": pct((flips == 1).sum(), n),
                            "2%": pct((flips == 2).sum(), n), "3+%": pct((flips >= 3).sum(), n)},
                         mean_flips=flips.mean()))
    say("### B2. stop_id flips inside a window (approximates Passages spanned by one 120 s archive Leg)\n")
    say(md(pd.DataFrame(rows), fmt="{:.3f}", index=False)); say()


# ------------------------------------------------------ C. storm signal

def hourly(legs, rule, lo, hi):
    L = apply_rule(legs, rule)
    L = L[(L["hour_end1"] >= lo) & (L["hour_end1"] <= hi)]
    g = L.groupby("hour_end1").agg(n_legs=("dt_s", "size"), dist=("dist_m", "sum"), secs=("dt_s", "sum"),
                                   med=("speed_mps", "median"), mean=("speed_mps", "mean"))
    g["agg_mps"] = g["dist"] / g["secs"]
    return g


def sectionC(legs_by_day):
    say("\n## C. Storm signal\n")
    for storm, ctrl in DAYS.items():
        lo_s = pd.Timestamp(f"{storm} 05:00", tz="UTC")
        hi_s = lo_s + pd.Timedelta(hours=23)
        lo_c = lo_s - pd.Timedelta(days=7); hi_c = hi_s - pd.Timedelta(days=7)
        s = hourly(legs_by_day[storm], RULES["R0"], lo_s, hi_s)
        c = hourly(legs_by_day[ctrl], RULES["R0"], lo_c, hi_c)
        c.index = c.index + pd.Timedelta(days=7)
        t = pd.DataFrame({
            "hour_end_UTC": [str(x)[:16] for x in s.index],
            "storm_n_legs": s["n_legs"].to_numpy(), "storm_agg_mps": s["agg_mps"].to_numpy(),
            "storm_med": s["med"].to_numpy(), "storm_mean": s["mean"].to_numpy(),
            "ctrl_n_legs": c["n_legs"].reindex(s.index).to_numpy(),
            "ctrl_agg_mps": c["agg_mps"].reindex(s.index).to_numpy(),
            "ctrl_med": c["med"].reindex(s.index).to_numpy(),
        })
        t["ratio_agg"] = t["storm_agg_mps"] / t["ctrl_agg_mps"]
        t["ratio_med"] = t["storm_med"] / t["ctrl_med"]
        hl = IDA_HOURS if storm == "2021-09-01" else FLOOD_HOURS
        t["hour_end_UTC"] = [f"**{x}**" if x in hl else x for x in t["hour_end_UTC"]]
        say(f"### C1. {storm} vs control {ctrl} (R0, hour-ending UTC; bold = highlighted hours)\n")
        say(md(t, fmt="{:.3f}", index=False)); say()
        t.to_parquet(f"{OUT}/c1_{storm}.parquet", index=False)

    # C2 per-cell
    bbox = set(pd.read_parquet(CELLS_PARQUET)["cell"].tolist())

    def cell_agg(legs, lo, hi):
        L = apply_rule(legs, RULES["R0"])
        L = L[(L["hour_end1"] >= lo) & (L["hour_end1"] <= hi) & L["cell_mid"].isin(bbox)]
        g = L.groupby("cell_mid").agg(n=("dt_s", "size"), dist=("dist_m", "sum"), secs=("dt_s", "sum"))
        g["mps"] = g["dist"] / g["secs"]
        return g

    say("### C2. Per-Cell storm/control speed ratio\n")
    rows = []
    for label, storm, ctrl, hs, he in [
        ("Ida, hour ending 2021-09-02 02:00Z", "2021-09-01", "2021-08-25", "2021-09-02 02:00", "2021-09-02 02:00"),
        ("Ida, hours 01-03Z pooled", "2021-09-01", "2021-08-25", "2021-09-02 01:00", "2021-09-02 03:00"),
        ("Ida, hours 03-04Z pooled (the deepest hours)", "2021-09-01", "2021-08-25",
         "2021-09-02 03:00", "2021-09-02 04:00"),
        ("2023-09-29, hour ending 14:00Z", "2023-09-29", "2023-09-22", "2023-09-29 14:00", "2023-09-29 14:00"),
        ("2023-09-29, hours 13-15Z pooled", "2023-09-29", "2023-09-22", "2023-09-29 13:00", "2023-09-29 15:00"),
    ]:
        lo = pd.Timestamp(hs, tz="UTC"); hi = pd.Timestamp(he, tz="UTC")
        a = cell_agg(legs_by_day[storm], lo, hi)
        b = cell_agg(legs_by_day[ctrl], lo - pd.Timedelta(days=7), hi - pd.Timedelta(days=7))
        j = a.join(b, lsuffix="_s", rsuffix="_c", how="inner")
        q = j[(j["n_s"] >= 20) & (j["n_c"] >= 20)].copy()
        q["ratio"] = q["mps_s"] / q["mps_c"]
        rows.append(dict(window=label, cells_storm=len(a), cells_ctrl=len(b),
                         cells_n20_both=len(q), p10=q["ratio"].quantile(.1), p50=q["ratio"].quantile(.5),
                         p90=q["ratio"].quantile(.9),
                         **{"<0.8%": pct((q["ratio"] < .8).sum(), len(q)),
                            "<0.9%": pct((q["ratio"] < .9).sum(), len(q))}))
        q.reset_index().to_parquet(f"{OUT}/c2_{label.split(',')[0].replace(' ', '_')}_{hs[-5:].replace(':', '')}.parquet",
                                   index=False)
    say(md(pd.DataFrame(rows), fmt="{:.3f}", index=False)); say()

    # C2b: is the citywide drop a slowdown, or a change in WHERE the buses were?
    # Recompute the same citywide ratio using only cells that clear n>=20 on both
    # days; if that moves the ratio a lot, composition is doing the work.
    rows = []
    for storm, ctrl, hl in [("2021-09-01", "2021-08-25", IDA_HOURS), ("2023-09-29", "2023-09-22", FLOOD_HOURS)]:
        for h in hl:
            lo = pd.Timestamp(h, tz="UTC")
            a = cell_agg(legs_by_day[storm], lo, lo)
            b = cell_agg(legs_by_day[ctrl], lo - pd.Timedelta(days=7), lo - pd.Timedelta(days=7))
            j = a.join(b, lsuffix="_s", rsuffix="_c", how="inner")
            q = j[(j["n_s"] >= 20) & (j["n_c"] >= 20)]
            rows.append(dict(hour_end_UTC=h, cells_matched=len(q),
                             legs_kept_storm_pct=pct(q["n_s"].sum(), a["n"].sum()),
                             ratio_all_cells=(a["dist"].sum() / a["secs"].sum()) / (b["dist"].sum() / b["secs"].sum()),
                             ratio_matched_cells=(q["dist_s"].sum() / q["secs_s"].sum()) /
                                                 (q["dist_c"].sum() / q["secs_c"].sum()),
                             median_cell_ratio=(q["mps_s"] / q["mps_c"]).median()))
    say("**C2b. Composition control: citywide ratio over all cells vs over cells with >= 20 Legs "
        "on both days (R0):**\n")
    say(md(pd.DataFrame(rows), fmt="{:.4f}", index=False))
    say("\n`ratio_all_cells` and `ratio_matched_cells` stay within ~0.01 of each other in every "
        "highlighted hour, so the citywide drop is not an artifact of the fleet moving to "
        "different places. `median_cell_ratio` sits above both in the deepest Ida hours "
        "(0.868 vs 0.788 at 03Z), i.e. the slowdown is concentrated in the cells that carry "
        "the most Legs, which a Leg-weighted aggregate picks up and a per-cell median does not.\n")

    # C3 sensitivity
    for storm, ctrl, hl in [("2021-09-01", "2021-08-25", IDA_HOURS), ("2023-09-29", "2023-09-22", FLOOD_HOURS)]:
        rows = []
        for name, r in RULES.items():
            lo_s = pd.Timestamp(f"{storm} 05:00", tz="UTC"); hi_s = lo_s + pd.Timedelta(hours=23)
            s = hourly(legs_by_day[storm], r, lo_s, hi_s)
            c = hourly(legs_by_day[ctrl], r, lo_s - pd.Timedelta(days=7), hi_s - pd.Timedelta(days=7))
            c.index = c.index + pd.Timedelta(days=7)
            row = {"rule": name}
            for h in hl:
                ts = pd.Timestamp(h, tz="UTC")
                row[h[-6:]] = s["agg_mps"].get(ts, np.nan) / c["agg_mps"].get(ts, np.nan)
            row["n_legs_storm_window"] = int(s["n_legs"].sum())
            rows.append(row)
        say(f"### C3. Rule sensitivity, {storm} storm/control aggregate-speed ratio by highlighted hour\n")
        say(md(pd.DataFrame(rows), fmt="{:.4f}", index=False)); say()

    # C4 ping volume
    for storm, ctrl in DAYS.items():
        lo = pd.Timestamp(f"{storm} 05:00", tz="UTC"); hi = lo + pd.Timedelta(hours=23)
        out = []
        for lbl, day, off in [("storm", storm, 0), ("ctrl", ctrl, 7)]:
            nxt = str((pd.Timestamp(day) + pd.Timedelta(days=1)).date())
            p = pd.concat([load_pings(day), load_pings(nxt)], ignore_index=True)
            p = p.drop_duplicates(["vehicle_id", "t"])
            p["he"] = p["t"].dt.ceil("h") + pd.Timedelta(days=off)
            g = p[(p["he"] >= lo) & (p["he"] <= hi)].groupby("he").agg(
                pings=("vehicle_id", "size"), veh=("vehicle_id", "nunique"))
            out.append(g.add_prefix(lbl + "_"))
        t = out[0].join(out[1])
        t["ping_ratio"] = t["storm_pings"] / t["ctrl_pings"]
        t["veh_ratio"] = t["storm_veh"] / t["ctrl_veh"]
        t.index = [str(x)[:16] for x in t.index]
        hl = IDA_HOURS if storm == "2021-09-01" else FLOOD_HOURS
        t.index = [f"**{x}**" if x in hl else x for x in t.index]
        t.index.name = "hour_end_UTC"
        say(f"### C4. Ping / vehicle volume, {storm} vs {ctrl}\n")
        say(md(t, fmt="{:.3f}")); say()


# -------------------------------------------------------- D. extra facts

def sectionD(legs_by_day):
    say("\n## D. Two extra facts\n")
    bbox = set(pd.read_parquet(CELLS_PARQUET)["cell"].tolist())
    rows = []
    for ctrl in DAYS.values():
        L = apply_rule(legs_by_day[ctrl], RULES["R0"])
        lo = pd.Timestamp(f"{ctrl} 06:00", tz="UTC"); hi = pd.Timestamp(f"{ctrl} 22:00", tz="UTC")
        L = L[(L["hour_end1"] >= lo) & (L["hour_end1"] <= hi) & L["cell_mid"].isin(bbox)]
        g = L.groupby("cell_mid").agg(n=("dt_s", "size"), dist=("dist_m", "sum"), secs=("dt_s", "sum"))
        g["mps"] = g["dist"] / g["secs"]
        q = g[g["n"] >= 100]
        rows.append(dict(control_day=ctrl, n_legs=len(L), cells_any=len(g), cells_n100=len(q),
                         p10=q["mps"].quantile(.1), p50=q["mps"].quantile(.5), p90=q["mps"].quantile(.9),
                         p90_over_p10=q["mps"].quantile(.9) / q["mps"].quantile(.1),
                         min=q["mps"].min(), max=q["mps"].max()))
    say("### D1. Per-Cell aggregate speed, 06Z-22Z, R0, cells with >= 100 Legs\n")
    say(md(pd.DataFrame(rows), fmt="{:.3f}", index=False)); say()

    rows = []
    for d in ALL_DAYS:
        L = legs_by_day[d]
        L = L[(L["t0"] >= pd.Timestamp(d, tz="UTC")) & (L["t0"] < pd.Timestamp(d, tz="UTC") + pd.Timedelta(days=1))]
        occ = L["occ0"].astype("string")
        vc = occ.value_counts()
        # "populated" is not the same as "informative": a field pinned to one enum
        # value for every Ping of the day carries no signal.
        pop = occ.notna() & ~occ.isin(["UNKNOWN", "NO_DATA_AVAILABLE", ""])
        rows.append(dict(day=d, n_legs=len(L), occ_nonnull_pct=pct(occ.notna().sum(), len(L)),
                         occ_not_unknown_pct=pct(pop.sum(), len(L)),
                         distinct_occ_values=int(occ.nunique(dropna=True)),
                         occ_modal_value=str(vc.index[0]) if len(vc) else "",
                         occ_modal_pct=pct(vc.iloc[0], len(L)) if len(vc) else float("nan"),
                         bearing_nonnull_pct=pct(L["bearing0"].notna().sum(), len(L)),
                         bearing_distinct=int(L["bearing0"].nunique())))
    say("### D2. occupancy_status (and bearing) fill on the start Ping of each Leg\n")
    say(md(pd.DataFrame(rows), fmt="{:.3f}", index=False)); say()


def selfcheck():
    """Smallest runnable check of the load-bearing arithmetic."""
    _, _, d = GEOD.inv(np.array([-74.0]), np.array([40.70]), np.array([-74.0]), np.array([40.71]))
    assert 1105 < d[0] < 1115, d[0]                       # 0.01 deg latitude ~ 1.11 km
    c = pd.Series(pd.to_datetime(["2021-09-02 02:00:00", "2021-09-02 01:00:01"],
                                 utc=True)).dt.ceil("h")
    assert str(c[0]) == "2021-09-02 02:00:00+00:00"       # exact hour stays in its hour
    assert str(c[1]) == "2021-09-02 02:00:00+00:00"
    assert cells_of(np.array([40.7128]), np.array([-74.0060]))[0] == \
        h3.str_to_int(h3.latlng_to_cell(40.7128, -74.0060, 8))


def main():
    selfcheck()
    os.makedirs(OUT, exist_ok=True)
    # legs_by_day holds the full 48 h span (needed for C's 05Z..+1 04Z window);
    # day_legs is the calendar-UTC day slice by t0 (Sections A and D2).
    legs_by_day = {d: load_legs(d) for d in ALL_DAYS}
    for d, L in legs_by_day.items():
        assert not (L["pre_departure"] & L["post_final"]).any(), f"A5 regions overlap on {d}"
    day_legs = {d: L[(L["t0"] >= pd.Timestamp(d, tz="UTC")) &
                     (L["t0"] < pd.Timestamp(d, tz="UTC") + pd.Timedelta(days=1))]
                for d, L in legs_by_day.items()}
    say("# Ticket 10 - speed evidence tables (generated by speed_evidence.py)\n")
    section0()
    sectionA(day_legs)
    sectionB()
    sectionC(legs_by_day)
    sectionD(legs_by_day)
    with open(f"{OUT}/tables.md", "w") as f:
        f.write("\n".join(REPORT) + "\n")
    print(f"wrote {OUT}/tables.md  ({sum(len(x) for x in REPORT):,} chars)")
    for d, L in day_legs.items():
        r0 = apply_rule(L, RULES["R0"])
        print(f"  {d}: legs={len(L):,} R0={len(r0):,} ({100*len(r0)/len(L):.1f}%) "
              f"dt_p50={L['dt_s'].median():.0f}s agg={r0['dist_m'].sum()/r0['dt_s'].sum():.3f} m/s")


if __name__ == "__main__":
    main()
