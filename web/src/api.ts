// Types mirror the API contract in CLAUDE.md.
export type App = 'grab' | 'indrive' | 'gvride'
export interface Quote { app: App; price_rm: number }
export interface ForecastRequest {
  datetime: string
  rain: boolean
  pickup: { lat: number; lon: number } | null
  quotes: Quote[]
  usual_price_rm: number | null
}
export interface HorizonPoint {
  minutes: number; pct_change: number; pct_low: number; pct_high: number; p_drop10: number
  expected_rm: Record<string, number>
}
export interface WaitOdds {
  minutes: number; p_save10: number; typical_p_save10: number; pct_low: number; pct_high: number
  rm_range: Record<string, [number, number]>
}
export interface ForecastEvent {
  name: string; source_url: string
  learned_effect: { pct: number; window: string } | null
}
export interface ForecastResponse {
  datetime: string
  horizon: HorizonPoint[]
  wait_odds: WaitOdds
  decision: 'book_now' | 'wait'
  best_time: string
  wait_minutes: number
  expected_saving_rm: Record<string, number>
  risk_if_wait_rm: Record<string, number>
  apps_ranked_now: string[]
  apps_ranked_best_time: string[]
  events: ForecastEvent[]
  reasons: string[]
  model_version: string
  evidence: Record<string, string>
}
export interface EventItem {
  id: string; name: string; venue: string; lat: number; lon: number
  start: string; end: string | null; source_url: string
}

export async function postForecast(body: ForecastRequest): Promise<ForecastResponse> {
  const r = await fetch('/api/forecast', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`forecast failed: ${r.status}`)
  return r.json()
}

export async function getEvents(date: string): Promise<EventItem[]> {
  const r = await fetch(`/api/events?date=${date}`)
  if (!r.ok) throw new Error(`events failed: ${r.status}`)
  return r.json()
}
