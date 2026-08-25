/* Freshness: the age of every SOURCE, and the five states one may be rendered in.
 *
 * frontend 01 D2. `age = <origin Date> - <Last-Modified>`, both taken from the response the
 * page already made. Rejected alternative: an `as_of_utc` in every payload - it breaks
 * test_export.py's byte-identity invariant and notify 05's re-export requirement, and it
 * dates the WRITE, not the newest input, so a nightly rebuild over week-old Gold would
 * paint FRESH. Both headers come from the ORIGIN, so a browser clock running an hour behind
 * cannot clamp an age to 0, and a CDN serving a cached copy returns the ORIGINAL
 * Last-Modified, which errs stale - the safe direction.
 *
 * A missing file is NOT an empty one: a 404 records a reason and never an age, because an
 * absent payload and an empty FeatureCollection must not both paint an empty map under a
 * fresh clock.
 */
import { L, on, shut } from "./layers.js";
import { liveMeta } from "./live.js";

export const ages = {};    // "<layer id>/<source key>" -> age in seconds, or null
export const whys = {};    // "<layer id>/<source key>" -> why there is no age

export async function grab(lyrId, s) {
  const key = lyrId + "/" + s.k;
  delete whys[key];
  ages[key] = null;
  try {
    const res = await fetch(s.url, { cache: "no-store" });
    if (!res.ok) {
      whys[key] = res.status === 404 ? "not published on this host" : `HTTP ${res.status}`;
      return null;
    }
    const d = Date.parse(res.headers.get("Date")), m = Date.parse(res.headers.get("Last-Modified"));
    if (Number.isNaN(d) || Number.isNaN(m)) whys[key] = "no age from the response headers";
    else ages[key] = Math.max(0, (d - m) / 1000);
    return await res.json();
  } catch (err) {
    whys[key] = "fetch failed";
    return null;
  }
}

export async function load(lyrId) {
  const lyr = L(lyrId);
  const bodies = [];
  for (const s of lyr.srcs) bodies.push(await grab(lyrId, s));
  if (lyr.draw) lyr.draw(bodies);
  return bodies;
}

export function forget(lyrId) {
  L(lyrId).srcs.forEach(s => { delete ages[lyrId + "/" + s.k]; delete whys[lyrId + "/" + s.k]; });
}

export const fmtAge = (s) => s === null || s === undefined ? "age unknown"
  : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min`
  : s < 172800 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d`;

/* FRESH / STALE(+reason) / OFF / GATED / AGE - the whole vocabulary, one row per SOURCE.
 * Freshness is NOT verdict: flood 15's tier states (INSUFFICIENT_DATA, HOLES, the winter
 * gate, a version-skew refusal) are the flood layer's own rendered vocabulary and stay
 * flood 15's. `ERROR` is not a state either - it is a reason string on a STALE row.
 * The order of these five branches is the contract:
 *   GATED  the layer's gate side is shut: dark, explained, never absent
 *   OFF    nothing is being fetched, so there is nothing to be fresh about
 *   STALE  we have no age at all (missing file, missing headers) - stale, never fresh
 *   AGE    age known, no budget frozen anywhere in the repo -> report it, judge nothing
 *   FRESH / STALE  compared against the frozen budget
 */
export function srcState(lyr, s) {
  const key = lyr.id + "/" + s.k;
  let age = ages[key];
  if (typeof age === "number" && s.inner && liveMeta && typeof liveMeta[s.inner] === "number")
    age += liveMeta[s.inner];       // the live pair's composite: file age + DATA age
  if (shut(lyr)) return { s: "GATED", why: "the MTA redistribution terms are not verified" };
  if (!on[lyr.id]) return { s: "OFF", why: "nothing is being fetched" };
  if (age === null || age === undefined)
    return { s: "STALE", why: whys[key] || "no age from the response headers" };
  if (s.budget === null) return { s: "AGE", why: "no budget frozen for this source", age };
  return age <= s.budget ? { s: "FRESH", age }
                         : { s: "STALE", why: `over the ${s.budget} s budget`, age };
}

// a layer is only as fresh as its worst source
export const worst = (lyr) => {
  const seen = lyr.srcs.map(s => srcState(lyr, s).s);
  return ["GATED", "STALE", "OFF", "AGE", "FRESH"].find(k => seen.includes(k));
};
