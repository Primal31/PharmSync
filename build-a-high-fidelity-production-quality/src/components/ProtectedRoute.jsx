import { Navigate } from 'react-router-dom'
import { useAuth, roleHome } from '../context/AuthContext'
export default function ProtectedRoute({ allow, children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="auth-loading"><span className="spinner"/> Restoring secure session…</div>
  if (!user) return <Navigate to="/login" replace />
  if (allow && !(Array.isArray(allow) ? allow.includes(user.role) : user.role === allow)) return <Navigate to={roleHome[user.role] || '/'} replace />
  return children
}
