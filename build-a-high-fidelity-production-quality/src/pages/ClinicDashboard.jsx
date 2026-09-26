import { useEffect, useState } from 'react'
import { Activity, ArrowRight, ArrowRightLeft, CircleAlert, Package, RefreshCw, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import Navbar from '../components/Navbar'
import { useAuth } from '../context/AuthContext'
import api from '../services/api'

const n = value => Number(value || 0).toLocaleString('en-IN')
export default function ClinicDashboard() {
  const { user } = useAuth()
  const [demands,setDemands]=useState([]);const [summary,setSummary]=useState({});const [loading,setLoading]=useState(true);const [error,setError]=useState('')
  async function load(){setLoading(true);setError('');try{const [d,s]=await Promise.all([api.get('/transfers/demand'),api.get('/transfers/summary')]);setDemands(d.data.demands||[]);setSummary(s.data.summary||{})}catch(e){setError(e.response?.data?.detail||e.userMessage||'Unable to load clinic demand data.')}finally{setLoading(false)}}
  useEffect(()=>{load()},[])
  const shortage=demands.reduce((sum,d)=>sum+Number(d.shortage_quantity||0),0)
  const critical=demands.filter(d=>['critical','high'].includes(String(d.priority||'').toLowerCase())).length
  return <div className="site-shell module-shell"><Navbar/><main className="module-page wrap transfers-page clinic-dashboard-page">
    <div className="module-heading"><div><span className="eyebrow">CLINIC / PHC PORTAL</span><h1>Clinic demand dashboard</h1><p>Welcome, {user?.organizationName || 'your clinic'}. Review recorded shortages and verified supply opportunities.</p></div><button className="button button-quiet" onClick={load} disabled={loading}><RefreshCw size={14} className={loading?'spinner-icon':''}/> Refresh</button></div>
    {error&&<div className="module-error" role="alert"><CircleAlert size={15}/>{error}</div>}
    <div className="transfer-kpis clinic-kpis">{[['Open demand records',demands.length,Activity],['Units in shortage',shortage,Package],['High priority items',critical,CircleAlert],['Transfer requests',summary.pending_transfers,ArrowRightLeft]].map(([label,value,Icon])=><article key={label}><span><Icon size={16}/></span><small>{label}</small><b>{loading?'—':n(value)}</b></article>)}</div>
    <section className="inventory-panel transfer-panel"><div className="inventory-panel-head"><div><span className="tiny-label">YOUR VERIFIED NODE · MYSQL</span><h2>Demand overview <span>{demands.length}</span></h2></div><span className="transfer-live"><ShieldCheck size={14}/> {user?.organizationName || 'Clinic account'}</span></div>
      {demands.length?<div className="table-scroll"><table className="inventory-table transfer-table"><thead><tr><th>Medicine</th><th>Form</th><th>Current stock</th><th>Daily demand</th><th>Shortage</th><th>Priority</th></tr></thead><tbody>{demands.map(d=><tr key={d.demand_id}><td><b>{d.medicine_name}</b><small>{d.medicine_id} · {d.demand_id}</small></td><td>{d.form}</td><td>{n(d.current_stock)}</td><td>{n(d.daily_demand)} / day</td><td><b>{n(d.shortage_quantity)}</b></td><td><span className={`priority-pill ${['critical','high'].includes(String(d.priority||'').toLowerCase())?'critical':'normal'}`}>{d.priority}</span></td></tr>)}</tbody></table></div>:<div className="transfer-empty">{loading?'Loading clinic demand…':error.toLowerCase().includes('not linked')?'This login is not linked to a clinic node yet. Ask an administrator to associate your account with the correct pharmacy_nodes.node_id.':'No open demand rows are currently recorded for this clinic.'}</div>}
    </section>
    <section className="clinic-next-step"><div className="clinic-next-icon"><ArrowRightLeft size={19}/></div><div><span className="tiny-label">VERIFIED P2P NETWORK</span><h2>Review nearby redistribution opportunities</h2><p>Request a match from an eligible pharmacy. The pharmacy reviews the request before stock moves.</p></div><Link className="button button-green" to="/transfers">Open transfers <ArrowRight size={14}/></Link></section>
  </main></div>
}
