// Connects Partner's screens to the real When Yah? API (contract in CLAUDE.md).
// Every number shown from here comes from /api/forecast (trained model + the user's typed prices)
// or /api/events (real events with source URLs). Nothing is invented on the client.

// Pickup coordinates for the place list (OpenStreetMap / Nominatim, looked up 10 Oct 2026).
// Used only to find real events within 5 km. When the Google Maps picker sets state.fromLatLon,
// that wins.
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
  quotes: { app: string; price: number }[]
  usual?: number | null
  rain?: boolean
}

function kualaLumpurNowIso(): string {
  // the API reads any timezone as KL time; send an explicit +08:00 timestamp
  const kl = new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 19)
  return `${kl}+08:00`
}

export function requestBody(inp: ModelInput) {
  const pickup = inp.fromLatLon ?? PLACE_LATLON[inp.from] ?? null
  return {
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

export const APP_ID_TO_NAME: Record<string, string> = { grab: "Grab", indrive: "inDrive", gvride: "GV Ride" }
