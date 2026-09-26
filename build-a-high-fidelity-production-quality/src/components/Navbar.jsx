import { Link, useLocation } from 'react-router-dom'
import { Activity, ArrowUpRight, Menu, X } from 'lucide-react'
import { useState } from 'react'
import { roleHome, roleLabel, useAuth } from '../context/AuthContext'
import ProfileMenu from './ProfileMenu'
export default function Navbar(){
 const [open,setOpen]=useState(false);const {user,loading}=useAuth();const location=useLocation()
 const workspaceLink=user?[[roleLabel[user.role]||'Workspace',roleHome[user.role]||'/']]:[['Inventory','/inventory']]
 const links=[['Home','/'],...workspaceLink,...(user?.role==='retail_chemist'?[['POS','/pos'],['Sales','/sales'],['Medicine requests','/pharmacy/orders']]:[]),...(user?.role==='patient'?[['My orders','/my-orders']]:[]),...(['retail_chemist','clinic_phc'].includes(user?.role)?[['P2P Transfers','/transfers'],['Analytics','/analytics']]:user?.role==='charity_ngo'?[['Analytics','/analytics']]:[])]
 return <header className="navbar"><div className="nav-inner wrap"><Link to="/" className="brand"><span className="brand-mark"><Activity size={19}/><i/></span><span>pharm<span>sync</span></span></Link><button className="menu-toggle" onClick={()=>setOpen(!open)} aria-label="Toggle navigation">{open?<X/>:<Menu/>}</button><nav className={open?'nav-links open':'nav-links'}>{links.map(([label,path])=><Link key={path} onClick={()=>setOpen(false)} className={location.pathname===path?'nav-active':''} to={path}>{label}</Link>)}</nav><div className="nav-actions">{user&&!loading?<ProfileMenu/>:<><span className="network"><i/> Network online</span><Link className="nav-login" to="/login">Portal login <ArrowUpRight size={15}/></Link></>}</div></div></header>
}
