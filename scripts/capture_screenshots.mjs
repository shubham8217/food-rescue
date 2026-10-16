// Captures the README screenshots with Playwright (headless Chromium).
//
//   npm i -D playwright && npx playwright install chromium     (once, anywhere)
//   node scripts/capture_screenshots.mjs [outDir] [shot1,shot2,...]
//
// Needs the stack to be running. Shots that need an optional service (NiFi, Airflow, Elasticsearch)
// are skipped with a message when that service is not reachable.
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const OUT = process.argv[2] || 'docs/screenshots'
const ONLY = (process.argv[3] || '').split(',').filter(Boolean)
const APP = process.env.APP_URL || 'http://localhost:5173'
const API = process.env.API_URL || 'http://localhost:8000'
fs.mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const reachable = async (url) => { try { return (await fetch(url, { signal: AbortSignal.timeout(4000) })).status < 500 } catch { return false } }
const login = async (email) => {
  const r = await fetch(`${API}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'demo123' }) })
  return r.json()
}
const authed = async (email, token) => {
  const t = token || (await login(email))
  return { t, headers: { Authorization: `Bearer ${t.access_token}`, 'Content-Type': 'application/json' } }
}

const browser = await chromium.launch()
const shots = []
const shot = (name, fn) => shots.push([name, fn])

async function page(width = 1360, height = 900, auth) {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 })
  if (auth) await ctx.addInitScript((a) => localStorage.setItem('foodrescue.auth', JSON.stringify(a)), auth)
  return ctx.newPage()
}
const save = (p, name, full = true) => p.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: full })

shot('01-login', async () => {
  const p = await page(900, 700)
  await p.goto(`${APP}/login`)
  await sleep(500)
  await save(p, '01-login', false)
})

shot('02-donor', async () => {
  const { t, headers } = await authed('donor@foodrescue.demo')
  const expiry = new Date(Date.now() + 5 * 3600e3).toISOString()
  for (const [food, cat, kg] of [['Veg biryani for 60 people', 'cooked_meals', 24], ['Fresh bread loaves', 'bakery', 12]])
    await fetch(`${API}/donations`, { method: 'POST', headers, body: JSON.stringify({ food_type: food, category: cat, quantity_kg: kg, expiry_time: expiry, area: 'Vashi' }) })
  await sleep(3500)
  const p = await page(1360, 900, t)
  await p.goto(`${APP}/donor`)
  await sleep(1500)
  await p.locator('.item-head').first().click().catch(() => {})
  await sleep(800)
  await save(p, '02-donor')
})

shot('03-ngo-matches', async () => {
  const { t } = await authed('ngo@foodrescue.demo')
  const p = await page(1360, 1000, t)
  await p.goto(`${APP}/ngo`)
  await sleep(2000)
  await save(p, '03-ngo-matches')
})

shot('04-ngo-search', async () => {
  if (!(await reachable('http://localhost:9200'))) return console.log('  skipped (Elasticsearch not running)')
  const { t } = await authed('ngo@foodrescue.demo')
  const p = await page(1360, 1000, t)
  await p.goto(`${APP}/ngo`)
  await p.getByLabel('Search', { exact: true }).fill('biryani')
  await p.getByRole('button', { name: 'Search' }).click()
  await sleep(1500)
  await p.evaluate(() => window.scrollTo(0, 0))
  await save(p, '04-ngo-search')
})

shot('05-admin-live-demo', async () => {
  const { t, headers } = await authed('admin@foodrescue.demo')
  const st = await (await fetch(`${API}/demo/status`, { headers })).json()
  if (!st.running) {
    await fetch(`${API}/demo/start`, { method: 'POST', headers, body: JSON.stringify({ speed: 5, start_hour: 13, reset: true }) })
    await sleep(55000)
  }
  const p = await page(1360, 1000, t)
  await p.goto(`${APP}/admin`)
  await sleep(3000)
  await p.locator('.map').scrollIntoViewIfNeeded()
  await p.waitForFunction(() => document.querySelectorAll('img.leaflet-tile-loaded').length >= 4, null, { timeout: 20000 }).catch(() => {})
  await sleep(2500)
  await p.evaluate(() => window.scrollTo(0, 0))
  await save(p, '05-admin-live-demo')
  await p.locator('.map').scrollIntoViewIfNeeded()
  await sleep(500)
  await save(p, '06-map-clusters-and-match-lines', false)
})

shot('07-analytics', async () => {
  const { t, headers } = await authed('admin@foodrescue.demo')
  await fetch(`${API}/forecast/backfill?days=7`, { method: 'POST', headers })
  const p = await page(1360, 1000, t)
  await p.goto(`${APP}/admin/analytics`)
  await sleep(5000)
  await save(p, '07-analytics')
})

shot('08-pipeline-health', async () => {
  const { t } = await authed('admin@foodrescue.demo')
  const p = await page(1360, 900, t)
  await p.goto(`${APP}/admin/pipeline`)
  await sleep(4500)
  await save(p, process.env.PIPELINE_SHOT_NAME || '08-pipeline-health')
})

shot('09-swagger', async () => {
  const p = await page(1360, 900)
  await p.goto(`${API}/docs`)
  await sleep(2500)
  await save(p, '09-swagger-api-docs', false)
})

shot('10-rabbitmq', async () => {
  const p = await page(1360, 800)
  await p.goto('http://localhost:15672/#/queues')
  await p.fill('input[name=username]', 'guest').catch(() => {})
  await p.fill('input[name=password]', 'guest').catch(() => {})
  await p.keyboard.press('Enter').catch(() => {})
  await sleep(4000)
  await p.goto('http://localhost:15672/#/queues')
  await sleep(3000)
  await save(p, '10-rabbitmq-queue', false)
})

shot('11-elasticsearch', async () => {
  if (!(await reachable('http://localhost:9200'))) return console.log('  skipped (Elasticsearch not running)')
  const p = await page(1100, 420)
  await p.goto('http://localhost:9200/_cat/indices?v')
  await save(p, '11-elasticsearch-indices', false)
})

shot('12-airflow', async () => {
  if (!(await reachable('http://localhost:8081/health'))) return console.log('  skipped (Airflow not running)')
  const p = await page(1360, 800)
  await p.goto('http://localhost:8081/login/')
  await p.fill('input[name=username]', 'admin')
  await p.fill('input[name=password]', 'foodrescue123')
  await p.keyboard.press('Enter')
  await sleep(4000)
  await p.goto('http://localhost:8081/home?search=foodrescue')
  await sleep(4000)
  await save(p, '12-airflow-dags', false)
})

shot('13-nifi', async () => {
  if (!(await reachable('http://localhost:8080/nifi-api/flow/about'))) return console.log('  skipped (NiFi not running)')
  const groups = await (await fetch('http://localhost:8080/nifi-api/process-groups/root/process-groups')).json()
  const gid = groups.processGroups?.[0]?.id
  const p = await page(1360, 800)
  await p.goto(`http://localhost:8080/nifi/${gid ? `?processGroupId=${gid}` : ''}`)
  await sleep(9000)
  await p.mouse.click(269, 368)  // collapse the Operate and Navigate panels so the flow is fully visible
  await p.mouse.click(269, 127)
  await sleep(800)
  await save(p, '13-nifi-flow', false)
})

for (const [name, fn] of shots) {
  if (ONLY.length && !ONLY.some((o) => name.startsWith(o))) continue
  process.stdout.write(`${name} ...\n`)
  try { await fn() } catch (e) { console.log('  failed:', e.message.split('\n')[0]) }
}
await browser.close()
console.log('screenshots written to', OUT)
