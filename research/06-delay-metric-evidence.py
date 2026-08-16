"""Ticket 06 evidence, corrected after adversarial review: vehicle-keyed passages,
flap-filtered, dedupe on full ping identity, headways skip same-trip followers,
per-stop EWT, TU stats split by reached/not-reached, coverage reconciliation."""
import glob, zipfile
from zoneinfo import ZoneInfo
from datetime import datetime
import numpy as np, pandas as pd

import sys
S = (sys.argv[1] if len(sys.argv) > 1 else 'SCRATCH').rstrip('/') + '/'  # dir with vp_all.parquet, tu_all.parquet (concat of data/archive/{vp,tu}) and gtfs/*.zip
NY = ZoneInfo('America/New_York'); SD = '20260815'
base = int(datetime(2026, 8, 15, 12, tzinfo=NY).timestamp()) - 12 * 3600

vp = pd.read_parquet(S + 'vp_all.parquet'); tu = pd.read_parquet(S + 'tu_all.parquet')
vp = vp[vp.fetched_at > vp.fetched_at.min() + 3600]  # drop the lone 13:47 smoke poll; continuous archive only
raw = len(vp)
vp = vp.drop_duplicates(['vehicle_id', 'ts', 'stop_id', 'lat', 'lon'])
# time axis: ts, but when the feed republishes a moved vehicle under a frozen ts, fall back to fetched_at
vp = vp.sort_values(['vehicle_id', 'fetched_at']).reset_index(drop=True)
vp['t'] = vp.ts.where(~vp.duplicated(['vehicle_id', 'ts'], keep='first'), vp.fetched_at)
hrs = (vp.fetched_at.max() - vp.fetched_at.min()) / 3600
print(f"continuous window {pd.to_datetime(vp.fetched_at.min(),unit='s')}..{pd.to_datetime(vp.fetched_at.max(),unit='s')} = {hrs:.2f} h; raw rows {raw:,} -> unique pings {len(vp):,}")

# static
zips = sorted(glob.glob(S + 'gtfs/*.zip'))
trips = pd.concat([pd.read_csv(zipfile.ZipFile(z).open('trips.txt'), dtype=str, usecols=['trip_id', 'route_id', 'direction_id', 'service_id']) for z in zips])
cal = pd.concat([pd.read_csv(zipfile.ZipFile(z).open('calendar.txt'), dtype=str) for z in zips])
cd = pd.concat([pd.read_csv(zipfile.ZipFile(z).open('calendar_dates.txt'), dtype=str) for z in zips])
act = set(cal[(cal.saturday == '1') & (cal.start_date <= SD) & (cal.end_date >= SD)].service_id)
added = set(cd[(cd.date == SD) & (cd.exception_type == '1')].service_id); removed = set(cd[(cd.date == SD) & (cd.exception_type == '2')].service_id)
act = (act | added) - removed
print(f"service_ids active {len(act)} (calendar {len(act - added)}, +{len(added)} added, -{len(removed)} removed on {SD})")
rt_trips = pd.Index(pd.concat([vp.trip_id, tu.trip_id]).dropna().unique())
tm = trips.set_index('trip_id')
rt_in_static = rt_trips[rt_trips.isin(tm.index)]
print(f"RT trips {len(rt_trips):,}; in static {len(rt_in_static):,}; of those with an active service_id {tm.loc[rt_in_static].service_id.isin(act).mean():.1%}")
st = pd.concat([(lambda s: s[s.trip_id.isin(rt_trips) | s.trip_id.isin(trips[trips.service_id.isin(act)].trip_id)])(
    pd.read_csv(zipfile.ZipFile(z).open('stop_times.txt'), dtype=str, usecols=['trip_id', 'arrival_time', 'stop_id', 'stop_sequence'])) for z in zips], ignore_index=True)
h = st.arrival_time.str.split(':', expand=True).astype(int); st['sched'] = base + h[0] * 3600 + h[1] * 60 + h[2]
st['stop_sequence'] = st.stop_sequence.astype(int)
st['is_last'] = st.stop_sequence == st.groupby('trip_id').stop_sequence.transform('max')
st['is_first'] = st.stop_sequence == st.groupby('trip_id').stop_sequence.transform('min')
key = st.set_index(['trip_id', 'stop_id'])

# ---- passages: per (vehicle, trip), monotone envelope on stop_sequence, first forward crossing ----
vp = vp.join(key.stop_sequence.rename('seq'), on=['trip_id', 'stop_id'])
vp = vp.dropna(subset=['seq']).sort_values(['vehicle_id', 'trip_id', 't'])
g = vp.groupby(['vehicle_id', 'trip_id'], sort=False)
vp['seq_prev'] = g.seq.shift(1); vp['t_prev'] = g.t.shift(1); vp['stop_prev'] = g.stop_id.shift(1)
vp['env'] = g.seq.cummax()  # monotone envelope
vp['env_prev'] = g.env.shift(1)
cross = vp[(vp.env_prev.notna()) & (vp.env > vp.env_prev)].copy()  # first time the envelope advances = forward crossing
# the stop passed = the stop at env_prev (last max seen)
cross['pass_ts'] = ((cross.t_prev + cross.t) / 2).astype(int); cross['width'] = cross.t - cross.t_prev
cross['k'] = (cross.env - cross.env_prev).astype(int)
# map env_prev seq back to stop_id
seq2stop = st.set_index(['trip_id', 'stop_sequence']).stop_id
cross['stop_id'] = seq2stop.reindex(list(zip(cross.trip_id, cross.env_prev.astype(int)))).values
cross = cross.dropna(subset=['stop_id'])
pas = cross[['vehicle_id', 'trip_id', 'route_id', 'direction_id', 'start_date', 'stop_id', 'pass_ts', 'width', 'k']].copy()
pas['seq'] = cross.env_prev.astype(int).values
dupkey = pas.duplicated(['trip_id', 'stop_id'], keep=False).mean()
print(f"\nPassages {len(pas):,} (k=1 {(pas.k==1).mean():.1%}, k=2 {(pas.k==2).mean():.1%}, k>=3 {(pas.k>=3).mean():.1%}); width p50 {pas.width.median():.0f} p90 {pas.width.quantile(.9):.0f} p99 {pas.width.quantile(.99):.0f}s; share of rows in duplicated (trip,stop) keys {dupkey:.1%} (multi-vehicle trips)")
nv = vp.groupby('trip_id').vehicle_id.nunique(); print(f"trips with >1 vehicle_id: {(nv>1).mean():.1%}")
pas = pas.join(key[['sched', 'is_first', 'is_last']], on=['trip_id', 'stop_id'])
pas['delay'] = pas.pass_ts - pas.sched
d = pas.delay.dropna(); dn = pas[~pas.is_first.fillna(False)].delay.dropna()
print(f"delay all p10 {d.quantile(.1):.0f} p50 {d.median():.0f} p90 {d.quantile(.9):.0f}; early<-60 {(d<-60).mean():.1%} late>300 {(d>300).mean():.1%} | excluding first stop: p50 {dn.median():.0f}, late>300 {(dn>300).mean():.1%}")
# segment time vs scheduled segment time (local measure)
pas = pas.sort_values(['vehicle_id', 'trip_id', 'seq'])
gg = pas.groupby(['vehicle_id', 'trip_id'], sort=False)
pas['seg_s'] = pas.pass_ts - gg.pass_ts.shift(1); pas['seg_sched_s'] = pas.sched - gg.sched.shift(1)
seg = pas.dropna(subset=['seg_s', 'seg_sched_s']); seg = seg[(seg.k == 1) & (seg.seg_sched_s > 0)]
ex = seg.seg_s - seg.seg_sched_s
print(f"segment excess (actual - scheduled stop-to-stop, k=1 both ends) n={len(seg):,}: p10 {ex.quantile(.1):.0f} p50 {ex.median():.0f} p90 {ex.quantile(.9):.0f}s; ratio p50 {(seg.seg_s/seg.seg_sched_s).median():.2f}")

# ---- coverage reconciliation ----
t0, t1 = vp.fetched_at.min() + 1800, vp.fetched_at.max() - 1800
act_trips = trips[trips.service_id.isin(act)]
win = st[st.trip_id.isin(act_trips.trip_id) & (st.sched >= t0) & (st.sched <= t1) & (~st.is_last)]
seen = set(vp.trip_id)
print(f"\nscheduled non-terminal arrivals in window {len(win):,} from {win.trip_id.nunique():,} trips; trips seen in VP {win.trip_id.isin(seen).mean():.1%}")
pw = pas[(pas.pass_ts >= t0) & (pas.pass_ts <= t1) & (~pas.is_last.fillna(False))]
print(f"observed passages in window {len(pw):,} -> ratio to scheduled {len(pw)/len(win):.3f}; ratio restricted to trips seen in VP {len(pw)/max(1,win.trip_id.isin(seen).sum()):.3f}")
# per-trip recall for trips seen: passages / scheduled non-terminal stops of that trip inside VP coverage of the trip
tp = pas.groupby('trip_id').size().rename('n_pass'); ts_ = st[~st.is_last].groupby('trip_id').size().rename('n_stops')
rec = pd.concat([tp, ts_], axis=1).dropna(); rec = rec[rec.index.isin(seen)]
r = rec.n_pass / rec.n_stops
print(f"per-trip recall (passages / non-terminal scheduled stops) for VP-seen trips: p10 {r.quantile(.1):.2f} p50 {r.median():.2f} p90 {r.quantile(.9):.2f}; note trips partly outside the window count low")
# scheduled trips fully inside window (first and last sched inside) but never seen: service delivered proxy
span = st.groupby('trip_id').sched.agg(['min', 'max']); full = span[(span['min'] >= t0) & (span['max'] <= t1) & span.index.isin(act_trips.trip_id)]
print(f"scheduled trips fully inside window {len(full):,}; never seen in VP {(~full.index.isin(seen)).mean():.1%}; never seen in TU {(~full.index.isin(set(tu.trip_id))).mean():.1%}")

# ---- TU series split by reached / not reached ----
tu = tu.sort_values(['trip_id', 'stop_id', 'fetched_at'])
agg = tu.groupby(['trip_id', 'stop_id'], sort=False).agg(first_fetch=('fetched_at', 'first'), last_fetch=('fetched_at', 'last'), n=('arrival_time', 'size'), first_pred=('arrival_time', 'first'), last_pred=('arrival_time', 'last'), pmin=('arrival_time', 'min'), pmax=('arrival_time', 'max'), nuniq=('arrival_time', 'nunique')).reset_index()
done = agg[agg.last_fetch < tu.fetched_at.max() - 600]
p1 = pas[~pas.duplicated(['trip_id', 'stop_id'], keep=False)][['trip_id', 'stop_id', 'pass_ts', 'width']]  # single-vehicle keys only
m = done.merge(p1, on=['trip_id', 'stop_id'], how='left')
reached = m[m.pass_ts.notna()]; nr = m[m.pass_ts.isna()]
print(f"\nTU completed series {len(done):,}: with VP passage {len(reached):,} ({len(reached)/len(done):.1%}), without {len(nr):,}")
print(f"  reached: polls p50 {reached.n.median():.0f}, distinct preds p50 {reached.nuniq.median():.0f}, churn range p50 {(reached.pmax-reached.pmin).median():.0f}s p90 {(reached.pmax-reached.pmin).quantile(.9):.0f}s, first horizon p50 {((reached.first_pred-reached.first_fetch)/60).median():.0f} min")
print(f"  not reached: polls p50 {nr.n.median():.0f}, last pred still {((nr.last_pred-nr.last_fetch)).median():.0f}s ahead at last poll (trip vanished / short-turned / reassigned)")
x = reached.last_pred - reached.pass_ts
print(f"  last TU pred - VP passage: p10 {x.quantile(.1):.0f} p50 {x.median():.0f} p90 {x.quantile(.9):.0f}s; |d|<=60 {(x.abs()<=60).mean():.1%} <=120 {(x.abs()<=120).mean():.1%}")
ser = tu.merge(p1, on=['trip_id', 'stop_id']); ser['hz'] = ser.pass_ts - ser.fetched_at; ser['err'] = ser.arrival_time - ser.pass_ts
ser = ser[(ser.hz > 0) & (ser.hz < 3600)]; ser['hb'] = pd.cut(ser.hz / 60, [0, 2, 5, 10, 15, 30, 60])
e = ser.groupby('hb', observed=True).err.agg(n='size', p50='median', abs_p50=lambda s: s.abs().median(), within120=lambda s: (s.abs() <= 120).mean())
print("  prediction error by horizon (min):\n" + e.round(2).to_string())
mm = reached.join(key.sched.rename('sched'), on=['trip_id', 'stop_id']).dropna(subset=['sched'])
print(f"  schedule delay same events n={len(mm):,}: TU-last p50 {(mm.last_pred-mm.sched).median():.0f} VP p50 {(mm.pass_ts-mm.sched).median():.0f}; late>300 TU {((mm.last_pred-mm.sched)>300).mean():.1%} VP {((mm.pass_ts-mm.sched)>300).mean():.1%}")

# ---- headways: skip same-trip followers, per (route,dir,stop) EWT with renewal SWT ----
sched_win = st[st.trip_id.isin(act_trips.trip_id) & (st.sched >= t0) & (st.sched <= t1)].merge(act_trips[['trip_id', 'route_id', 'direction_id']], on='trip_id')
sched_win['direction_id'] = sched_win.direction_id.astype(int)
sched_win = sched_win.sort_values(['route_id', 'direction_id', 'stop_id', 'sched']); sched_win['sh'] = sched_win.groupby(['route_id', 'direction_id', 'stop_id']).sched.diff() / 60
sw = sched_win.dropna(subset=['sh'])
rd_sched = sw.groupby(['route_id', 'direction_id']).sh.median().rename('sched_med')
swt = sw.groupby(['route_id', 'direction_id', 'stop_id']).sh.agg(swt=lambda s: (s ** 2).mean() / (2 * s.mean()))
ob = pas[(pas.pass_ts >= t0) & (pas.pass_ts <= t1)].copy(); ob['direction_id'] = ob.direction_id.astype(int)
ob = ob.sort_values(['route_id', 'direction_id', 'stop_id', 'pass_ts'])
gk = ob.groupby(['route_id', 'direction_id', 'stop_id'], sort=False)
ob['prev_trip'] = gk.trip_id.shift(1); ob['prev_veh'] = gk.vehicle_id.shift(1); ob['oh'] = (ob.pass_ts - gk.pass_ts.shift(1)) / 60
ob = ob[(ob.prev_trip.notna()) & (ob.prev_trip != ob.trip_id) & (ob.prev_veh != ob.vehicle_id) & (ob.oh > 0) & (ob.oh < 120)]
ob = ob.join(rd_sched, on=['route_id', 'direction_id']).dropna(subset=['sched_med'])
awt = ob.groupby(['route_id', 'direction_id', 'stop_id']).oh.agg(awt=lambda s: (s ** 2).mean() / (2 * s.mean()), n='size')
ew = awt.join(swt, how='inner').join(rd_sched, on=['route_id', 'direction_id']); ew = ew[ew.n >= 5]; ew['ewt'] = ew.awt - ew.swt
print(f"\nroute-dirs scheduled in window {len(rd_sched)}; sched headway p50 {rd_sched.median():.0f} min; <=10 {(rd_sched<=10).mean():.1%} <=12 {(rd_sched<=12).mean():.1%} <=15 {(rd_sched<=15).mean():.1%}")
for name, lo, hi in [('<=10', 0, 10), ('10-15', 10, 15), ('>15', 15, 999)]:
    s = ob[(ob.sched_med > lo) & (ob.sched_med <= hi)]; e2 = ew[(ew.sched_med > lo) & (ew.sched_med <= hi)]
    print(f"  {name} min routes: headways n={len(s):,}; bunched(<0.5x) {(s.oh<0.5*s.sched_med).mean():.1%}, <2min {(s.oh<2).mean():.1%}, gapped(>1.5x) {(s.oh>1.5*s.sched_med).mean():.1%}, wait_ok(<=sched+3) {(s.oh<=s.sched_med+3).mean():.1%}; per-stop EWT p50 {e2.ewt.median():.1f} min (SWT p50 {e2.swt.median():.1f}, AWT p50 {e2.awt.median():.1f}) over {len(e2)} stops")
pas.to_parquet(S + 'passages_v2.parquet')
