import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Activity, ArrowRight, Eye, EyeOff, ShieldCheck } from 'lucide-react'
import Navbar from '../components/Navbar'
import { useAuth, roleHome } from '../context/AuthContext'
import api from '../services/api'

export default function Login() {
  const { login, user, loading } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ email: '', password: '' })
  const [remember, setRemember] = useState(true)
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  if (loading) return <div className="auth-loading"><span className="spinner"/> Restoring secure session…</div>
  if (user) return <Navigate to={roleHome[user.role] || '/'} replace />
  const update = (event) => setForm({ ...form, [event.target.name]: event.target.value })
  const submit = async (event) => {
    event.preventDefault(); setError(''); setSubmitting(true)
    try {
      const loggedIn = await login(form, remember)
      navigate(roleHome[loggedIn.role] || '/', { replace: true })
    } catch (e) { setError(e.userMessage || 'Unable to sign in.') }
    finally { setSubmitting(false) }
  }
  return <div className="site-shell auth-shell"><Navbar/><main className="auth-page wrap"><section className="auth-aside"><div className="auth-aside-orb"/><div className="auth-aside-content"><span className="eyebrow"><span/> PHARMSYNC NETWORK ACCESS</span><h1>Good medicine<br/>goes <em>further.</em></h1><p>One connected network for pharmacies, clinics and charitable healthcare.</p><div className="auth-assurance"><ShieldCheck size={16}/><span>Verified organizations. Traceable transfers.</span></div></div><div className="auth-aside-foot"><Activity size={16}/> SUPPLY, IN SYNC.</div></section><section className="auth-card-wrap"><div className="auth-card"><div className="auth-card-heading"><span className="auth-icon"><Activity size={19}/></span><span className="eyebrow">YOUR PHARMSYNC PORTAL</span><h2>Welcome back</h2><p>Sign in to your PharmSync portal</p></div><form onSubmit={submit} className="auth-form"><label>Email address<input autoComplete="email" type="email" name="email" value={form.email} onChange={update} placeholder="you@organization.com" required/></label><label>Password<span className="password-field"><input autoComplete="current-password" type={showPassword ? 'text' : 'password'} name="password" value={form.password} onChange={update} placeholder="Enter your password" required/><button type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff size={16}/> : <Eye size={16}/>}</button></span></label><div className="form-options"><label className="check-label"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)}/> Remember me</label><a href="mailto:support@pharmsync.health?subject=Password%20reset">Forgot password?</a></div>{error && <div className="form-error" role="alert">{error}</div>}<button disabled={submitting} className="button button-green auth-submit">{submitting ? 'Signing in…' : 'Sign in'} <ArrowRight size={16}/></button></form><div className="auth-switch">Don’t have an account? <Link to="/register">Create account</Link></div><div className="auth-secure"><ShieldCheck size={13}/> Your connection is protected by encrypted authentication.</div></div><div className="auth-card-foot">© 2026 PharmSync Technologies <span>SECURE PORTAL</span></div></section></main></div>
}
