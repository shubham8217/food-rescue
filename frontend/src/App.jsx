import { Navigate, Route, Routes } from 'react-router-dom'
import { Protected, homeFor, useAuth } from './auth.jsx'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import Donor from './pages/Donor.jsx'
import Ngo from './pages/Ngo.jsx'
import Admin from './pages/Admin.jsx'

export default function App() {
  const { auth } = useAuth()
  const guarded = (roles, el) => (
    <Protected roles={roles}>
      <Layout>{el}</Layout>
    </Protected>
  )
  return (
    <Routes>
      <Route path="/login" element={auth ? <Navigate to={homeFor(auth.role)} replace /> : <Login />} />
      <Route path="/donor" element={guarded(['donor'], <Donor />)} />
      <Route path="/ngo" element={guarded(['ngo'], <Ngo />)} />
      <Route path="/admin" element={guarded(['admin'], <Admin />)} />
      <Route path="*" element={<Navigate to={auth ? homeFor(auth.role) : '/login'} replace />} />
    </Routes>
  )
}
