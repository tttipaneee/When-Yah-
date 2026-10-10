// Unstyled wiring only — visual design comes from Partner (design/).
import { useState } from 'react'
import { postForecast, type App as AppId, type ForecastResponse } from './api'

const APPS: AppId[] = ['grab', 'indrive', 'gvride']

function localIso(d: Date): string {
  const off = -d.getTimezoneOffset()
  const sign = off >= 0 ? '+' : '-'
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, '0')
  const local = new Date(d.getTime() + off * 60000).toISOString().slice(0, 19)
  return `${local}${sign}${pad(off / 60)}:${pad(off % 60)}`
}

export default function App() {
  const [prices, setPrices] = useState<Record<AppId, string>>({ grab: '', indrive: '', gvride: '' })
  const [usual, setUsual] = useState('')
  const [rain, setRain] = useState(false)
  const [res, setRes] = useState<ForecastResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    try {
      const quotes = APPS.filter((a) => Number(prices[a]) > 0).map((a) => ({ app: a, price_rm: Number(prices[a]) }))
      setRes(await postForecast({
        datetime: localIso(new Date()), rain, pickup: null, quotes,
        usual_price_rm: Number(usual) > 0 ? Number(usual) : null,
      }))
    } catch (x) {
      setErr(String(x))
    }
  }

  return (
    <main>
      <h1>When Yah?</h1>
      <form onSubmit={submit}>
        <fieldset>
          <legend>Masukkan harga yang anda nampak</legend>
          {APPS.map((a) => (
            <label key={a}>
              {a} RM <input type="number" step="0.1" min="0" value={prices[a]}
                onChange={(e) => setPrices({ ...prices, [a]: e.target.value })} />
            </label>
          ))}
        </fieldset>
        <label>harga biasa RM <input type="number" step="0.1" min="0" value={usual}
          onChange={(e) => setUsual(e.target.value)} /></label>
        <label><input type="checkbox" checked={rain} onChange={(e) => setRain(e.target.checked)} /> rain</label>
        <button type="submit">Ramal</button>
      </form>
      {err && <p>{err}</p>}
      {res && <pre>{JSON.stringify(res, null, 2)}</pre>}
    </main>
  )
}
