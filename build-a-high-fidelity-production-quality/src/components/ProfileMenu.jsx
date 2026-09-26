import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, LogOut, Building2, Mail, UserRound } from 'lucide-react'
import { roleLabel, useAuth } from '../context/AuthContext'
export default function ProfileMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  if (!user) return null
  const signOut = () => { logout(); navigate('/login', { replace: true }) }
  return <div className="profile-wrap">
    <button className="profile-trigger" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span className="profile-avatar">{user.organizationName?.slice(0,1)?.toUpperCase() || 'P'}</span>
      <span className="profile-trigger-copy"><b>{user.organizationName}</b><small>{roleLabel[user.role]}</small></span><ChevronDown size={14}/>
    </button>
    {open && <><button className="menu-scrim" aria-label="Close profile menu" onClick={() => setOpen(false)}/><div className="profile-popover">
      <div className="profile-popover-head"><b>Account profile</b><span className="role-pill">{roleLabel[user.role]}</span></div>
      <div className="profile-detail"><UserRound size={14}/><span>{user.fullName}</span></div><div className="profile-detail"><Mail size={14}/><span>{user.email}</span></div>{user.organizationName&&<div className="profile-detail"><Building2 size={14}/><span>{user.organizationName}</span></div>}
      <button className="profile-logout" onClick={signOut}><LogOut size={14}/> Sign out</button>
    </div></>}
  </div>
}
