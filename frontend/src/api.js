const BASE = '/api'
const KEY = 'foodrescue.auth'

export const loadAuth = () => {
  try { return JSON.parse(localStorage.getItem(KEY)) } catch { return null }
}
export const saveAuth = (a) => (a ? localStorage.setItem(KEY, JSON.stringify(a)) : localStorage.removeItem(KEY))

export async function api(path, { method = 'GET', body } = {}) {
  const auth = loadAuth()
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(auth ? { Authorization: `Bearer ${auth.access_token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 && auth) {
    saveAuth(null)
    window.location.href = '/login'
    throw new Error('Session expired')
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const d = data?.detail
    throw new Error(typeof d === 'string' ? d : Array.isArray(d) ? d.map((e) => e.msg).join('; ') : `Request failed (${res.status})`)
  }
  return data
}

export const wsUrl = (token) => {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${BASE}/ws/live?token=${encodeURIComponent(token)}`
}
