"""Ticket 10: terminal-region rule variants (R00/R0/R1/R2) on the cached Legs of
10-backfill-speed-evidence.py (m2/legs_<date>.parquet). Run from the directory that
holds m2/: uv run --no-project --with pandas,pyarrow,numpy python 10-backfill-terminal-variants.py"""
import pandas as pd, numpy as np
cols=["t0","dt_s","dist_m","speed_mps","same_trip","trip_id0","pre_departure","post_final","run_no_flip","hour_end1","cell_mid","route_id0"]
def load(d): return pd.read_parquet(f"m2/legs_{d}.parquet", columns=cols)
def base(L): return L.same_trip & (L.dt_s>0) & (L.dt_s<=300) & (L.speed_mps<=30) & L.trip_id0.notna()
def rules(L, v):
    m=base(L); term=(L.pre_departure|L.post_final|L.run_no_flip)
    if v=="R0": m&=~L.pre_departure
    if v=="R1": m&=~(L.pre_departure|L.post_final)   # run_no_flip legs are pre_departure by construction? check
    if v=="R2": m&=~(term & (L.dist_m<25))
    if v=="R00": pass
    return L[m]
def agg(L,h):
    s=L[L.hour_end1==pd.Timestamp(h,tz="UTC")]; return s.dist_m.sum()/s.dt_s.sum(), len(s)
for storm,ctrl,hours in [("2021-09-01","2021-08-25",["2021-09-02 01:00","2021-09-02 02:00","2021-09-02 03:00","2021-09-02 04:00","2021-09-02 06:00","2021-09-02 08:00"]),
                         ("2023-09-29","2023-09-22",["2023-09-29 12:00","2023-09-29 13:00","2023-09-29 14:00","2023-09-29 19:00"])]:
    S=load(storm); C=load(ctrl)
    ch=[str(pd.Timestamp(h)-pd.Timedelta(days=7))[:16] for h in hours]
    print(f"\n{storm} vs {ctrl}  (n same-trip legs storm {S.same_trip.sum():,})")
    for v in ["R00","R0","R1","R2"]:
        s=rules(S,v); c=rules(C,v)
        print(f"{v:4s} kept {len(s)/len(S):.3f}", " ".join(f"{h[-5:]}:{agg(s,h)[0]/agg(c,x)[0]:.3f}(n{agg(s,h)[1]})" for h,x in zip(hours,ch)))
    # deletion share storm vs control at the deepest hour under R1 vs R2
    h=hours[3]; x=ch[3]
    for v,name in [("R1","R1"),("R2","R2")]:
        bs=S[base(S)]; bc=C[base(C)]
        ds=1-len(rules(S,v)[rules(S,v).hour_end1==pd.Timestamp(h,tz="UTC")])/len(bs[bs.hour_end1==pd.Timestamp(h,tz="UTC")])
        dc=1-len(rules(C,v)[rules(C,v).hour_end1==pd.Timestamp(x,tz="UTC")])/len(bc[bc.hour_end1==pd.Timestamp(x,tz="UTC")])
        print(f"  {name} deletion share at {h[-5:]}: storm {ds:.3f} control {dc:.3f}")
    # control-day level and median under R2
    c2=rules(C,"R2"); c1=rules(C,"R1")
    print(f"  control all-hours agg speed R1 {c1.dist_m.sum()/c1.dt_s.sum():.3f} R2 {c2.dist_m.sum()/c2.dt_s.sum():.3f}; median leg R2 {c2.speed_mps.median():.3f}")
# is run_no_flip a subset of pre_departure?
L=load("2021-09-01"); print("no_flip & ~pre:", (L.run_no_flip & ~L.pre_departure).sum(), "no_flip:", L.run_no_flip.sum())
