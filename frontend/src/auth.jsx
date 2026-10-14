import { createContext, useContext, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { api, loadAuth, saveAuth } from './api.js'

const Ctx = createContext(null)
export const useAuth = () => useContext(Ctx)

export const homeFor = (role) => ({ donor: '/donor', ngo: '/ngo', admin: '/admin' }[role] || '/login')

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(loadAuth())
  const login = async (email, password) => {
    const a = await api('/auth/login', { method: 'POST', body: { email, password } })
    saveAuth(a)
    setAuth(a)
    return a
  }
  const logout = () => {
    saveAuth(null)
    setAuth(null)
  }
  return <Ctx.Provider value={{ auth, login, logout }}>{children}</Ctx.Provider>
}

/** Route guard: must be logged in, and (optionally) have one of `roles`. */
export function Protected({ roles, children }) {
  const { auth } = useAuth()
  if (!auth) return <Navigate to="/login" replace />
  if (roles && !roles.includes(auth.role)) return <Navigate to={homeFor(auth.role)} replace />
  return children
}
