// Connects Partner's screens to the real When Yah? API (contract in CLAUDE.md).
// Every number shown from here comes from /api/forecast (trained model + the user's typed prices)
// or /api/events (real events with source URLs). Nothing is invented on the client.

// Pickup coordinates for the place list (OpenStreetMap / Nominatim, looked up 10 Oct 2026).
// Used to find real events within 5 km and, with the destination, predicted traffic (TomTom, server side).
// When the map picker (Leaflet) sets state.fromLatLon / state.toLatLon, those win.
export const PLACE_LATLON: Record<string, { lat: number; lon: number }> = {
  "KL Sentral": { lat: 3.1325847, lon: 101.6879963 },
  "KLCC": { lat: 3.1573751, lon: 101.7123797 },
  "Pavilion KL": { lat: 3.149154, lon: 101.7129531 },
  "Mid Valley City": { lat: 3.1176552, lon: 101.6773741 },
  "Bangsar": { lat: 3.1294385, lon: 101.6701803 },
  "Axiata Arena": { lat: 3.0537311, lon: 101.6934618 }, // now Unifi Arena
  "Sunway Pyramid": { lat: 3.0724851, lon: 101.60655 },
  "Sri Petaling": { lat: 3.0586081, lon: 101.6916169 },
  "Bandar Tasik Selatan": { lat: 3.0763304, lon: 101.7111343 },
  "Petaling Jaya SS2": { lat: 3.1172168, lon: 101.6155072 },
};

const APP_IDS: Record<string, string> = { Grab: "grab", inDrive: "indrive", "GV Ride": "gvride" };

export interface ModelInput {
  from: string
  fromLatLon?: { lat: number; lon: number } | null
  to?: string
  toLatLon?: { lat: number; lon: number } | null
  quotes: { app: string; price: number }[]
  usual?: number | null
  rain?: boolean
}

// Presenter override: ?at=2026-10-11T22:40 runs the forecast and today's events as if it were that KL time
// (e.g. to show the event exit window before the event); without it, the real clock is used
export function presenterAt(): string | null {
  try {
    const v = new URLSearchParams(window.location.search).get("at")
    return v && /^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(v) ? v : null
  } catch { return null }
}

function kualaLumpurNowIso(): string {
  // the API reads any timezone as KL time; send an explicit +08:00 timestamp
  const at = presenterAt()
  if (at) return `${at}:00+08:00`
  const kl = new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 19)
  return `${kl}+08:00`
}

export function requestBody(inp: ModelInput) {
  const pickup = inp.fromLatLon ?? PLACE_LATLON[inp.from] ?? null
  const dropoff = inp.toLatLon ?? (inp.to ? PLACE_LATLON[inp.to] : null) ?? null
  return {
    dropoff, // with pickup: the API asks TomTom for predicted trip time (traffic) if TOMTOM_API_KEY is set
    datetime: kualaLumpurNowIso(),
    rain: !!inp.rain,
    pickup,
    // "Other app" has no id in the contract: it is left out of the model call
    quotes: inp.quotes.filter((q) => q.price > 0 && APP_IDS[q.app]).map((q) => ({ app: APP_IDS[q.app], price_rm: q.price })),
    usual_price_rm: inp.usual && inp.usual > 0 ? inp.usual : null,
  }
}

let lastKey = ""
let lastResult: Promise<any> | null = null

/** Calls /api/forecast; identical inputs (ignoring the clock) reuse the previous call. */
export function runModel(inp: ModelInput): Promise<any> {
  const body = requestBody(inp)
  const key = JSON.stringify({ ...body, datetime: body.datetime.slice(0, 16) })
  if (key === lastKey && lastResult) return lastResult
  lastKey = key
  lastResult = fetch("/api/forecast", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).then((r) => {
    if (!r.ok) throw new Error(`forecast failed: ${r.status}`)
    return r.json()
  })
  lastResult.catch(() => { lastKey = "" })
  return lastResult
}

/** Claude explains this forecast in plain words (server recomputes the forecast; answers with numbers not in it are rejected). */
export function explainForecast(inp: ModelInput): Promise<{ ai: boolean; text: string | null; reason?: string }> {
  return fetch("/api/explain", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(requestBody(inp)),
  }).then((r) => (r.ok ? r.json() : { ai: false, text: null, reason: `server error ${r.status}` }))
    .catch(() => ({ ai: false, text: null, reason: "API not reachable" }))
}

export const APP_ID_TO_NAME: Record<string, string> = { grab: "Grab", indrive: "inDrive", gvride: "GV Ride" }

export interface RealEvent {
  id: string; name: string; venue: string; lat: number; lon: number
  start: string; end: string | null; source_url: string
}

/** Real events today (KL date) from /api/events — every row has a source_url (data/events/malaysia_events.csv). */
export function fetchEventsToday(): Promise<RealEvent[]> {
  const klDate = presenterAt()?.slice(0, 10) ?? new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 10)
  return fetch(`/api/events?date=${klDate}`).then((r) => (r.ok ? r.json() : []))
}

/** Study cases from /api/case_studies (reports/case_studies.json = numbers of reports/case_studies.md). */
export function fetchCaseStudies(): Promise<any> {
  return fetch("/api/case_studies").then((r) => (r.ok ? r.json() : null)).catch(() => null)
}

/** Proof screen data from /api/metrics (reports/metrics.json, decision.json, experiments, fare_check.json). */
export function fetchMetrics(): Promise<any> {
  return fetch("/api/metrics").then((r) => (r.ok ? r.json() : null)).catch(() => null)
}

/** Great-circle distance in km. */
export function kmBetween(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const R = 6371, rad = Math.PI / 180
  const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

/** "16:00" from an ISO time with offset, shown in KL time. */
export function klTime(iso: string): string {
  const d = new Date(new Date(iso).getTime() + 8 * 3600_000)
  return d.toISOString().slice(11, 16)
}
