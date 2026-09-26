import { useCallback, useEffect, useState } from 'react'
import { Activity, AlertTriangle, BadgePercent, HeartHandshake, Package, RefreshCw, TrendingDown } from 'lucide-react'
import api from '../services/api'

const money = (n) => new Intl.NumberFormat('en-IN', { style:'currency', currency:'INR', maximumFractionDigits:2 }).format(Number(n||0))
const round = (n) => Number(n||0).toFixed(1)

function AlertCard({ tone, label, title, rows, icon: Icon, message, action }) {
  if (!rows.length) return null
  const visible = rows.slice(0, 2)
  return <article className={`intelligence-alert ${tone}`}>
    <div className="intelligence-alert-heading"><span><Icon size={15}/>{label}</span><b>{rows.length}</b></div>
    <h3>{title}</h3>
    <div className="intelligence-alert-items">{visible.map(row => <div className="intelligence-alert-item" key={row.batch_id}>
      <b>{row.medicine_name}</b><small>{row.quantity} units · {row.days_left} days left</small>
      {row.restock_recommended ? <small>Estimated coverage: {round(row.estimated_days_of_stock)} days</small> : <small>Projected remaining: {round(row.projected_remaining)} units</small>}
      {row.discount_percentage > 0 && <small>Current offer: {row.discount_percentage}% off · {money(row.offer_price)}</small>}
    </div>)}</div>
    {rows.length > visible.length && <small className="intelligence-alert-more">+ {rows.length-visible.length} more batches</small>}
    <p>{message}</p><span className="intelligence-alert-action">{action}</span>
  </article>
}

export default function InventoryIntelligence() {
  const [data,setData]=useState(null);const [summary,setSummary]=useState(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('')
  const load=useCallback(async()=>{try{setError('');const [a,b]=await Promise.all([api.get('/inventory/intelligence'),api.get('/inventory/intelligence/summary')]);setData(a.data);setSummary(b.data.summary)}catch(e){setError(e.userMessage||'Unable to load inventory intelligence.')}},[])
  useEffect(()=>{load()},[load])
  const run=async()=>{setBusy(true);setError('');setNotice('');try{const {data:r}=await api.post('/agent/inventory/run');setNotice(`Analysis complete · ${r.processed_batches} batches processed · ${r.restock_alerts} restock alerts.`);await load()}catch(e){setError(e.userMessage||'Unable to run the inventory agent.')}finally{setBusy(false)}}
  const rows=data?.batches||[];const s=summary||{}
  const restock=rows.filter(r=>r.restock_recommended)
  const risk90=rows.filter(r=>r.stock_status==='AT_RISK_90_DAYS')
  const risk60=rows.filter(r=>r.stock_status==='AT_RISK_60_DAYS')
  const charity=rows.filter(r=>r.stock_status==='CHARITY_FALLBACK')
  const actions=(r)=>r.stock_status==='CHARITY_FALLBACK'?'Prepare for free redistribution':r.stock_status==='AT_RISK_60_DAYS'?'Prioritize redistribution':r.stock_status==='AT_RISK_90_DAYS'?'Prepare for redistribution':r.restock_recommended?'Restock recommended':r.stock_status==='EXPIRED'?'Blocked from sale':'Monitor stock'
  return <section className="intelligence-panel">
    <div className="intelligence-head"><div><span className="tiny-label"><Activity size={13}/> INVENTORY INTELLIGENCE AGENT</span><h2>Restock & expiry outlook</h2><p>Deterministic estimates from current stock and trailing 30-day MySQL sales.</p></div><button className="button button-quiet" onClick={run} disabled={busy}><RefreshCw size={14} className={busy?'spinner-icon':''}/>{busy?'Analyzing…':'Run analysis'}</button></div>
    {error&&<div className="module-error" role="alert">{error}</div>}{notice&&<div className="module-notice">{notice}</div>}
    <div className="intelligence-kpis">
      <article><Package/><small>Total stock</small><b>{Number(s.total_stock??0).toLocaleString('en-IN')}</b><span>{s.total_batches??0} active batches</span></article>
      <article className="blue"><TrendingDown/><small>Restock needed</small><b>{s.restock_alerts??'—'}</b></article>
      <article className="amber"><AlertTriangle/><small>Expiry risk</small><b>{s.expiry_risk_batches??'—'}</b></article>
      <article className="cyan"><BadgePercent/><small>Discount active</small><b>{(s.discount_30_percent_count||0)+(s.discount_50_percent_count||0)}</b><span>30%: {s.discount_30_percent_count||0} · 50%: {s.discount_50_percent_count||0}</span></article>
      <article className="red"><HeartHandshake/><small>Charity fallback</small><b>{s.charity_fallback_count??'—'}</b></article>
    </div>
    <div className="intelligence-alerts">
      <AlertCard tone="restock" label="RESTOCK NEEDED" title="Low stock coverage" rows={restock} icon={TrendingDown} message="Stock may run out at the current sales rate." action="Restock recommended"/>
      <AlertCard tone="risk90" label="EXPIRY RISK" title="90-day redistribution window" rows={risk90} icon={AlertTriangle} message="Review these batches and prepare a local offer." action="Prepare for redistribution"/>
      <AlertCard tone="risk60" label="HIGH EXPIRY RISK" title="60-day priority window" rows={risk60} icon={BadgePercent} message="A deeper discount is active based on expiry." action="Prioritize redistribution"/>
      <AlertCard tone="charity" label="CHARITY FALLBACK" title="Free redistribution flagged" rows={charity} icon={HeartHandshake} message="Eligible stock is flagged for later free redistribution through verified organizations." action="Charity fallback required"/>
    </div>
    <div className="intelligence-table-wrap"><table className="intelligence-table"><thead><tr><th>Medicine / batch</th><th>Current stock</th><th>Days left</th><th>Sales velocity</th><th>Projected remaining</th><th>Stock status</th><th>Discount</th><th>Action</th></tr></thead><tbody>
      {rows.length?rows.map(r=><tr key={r.batch_id}><td><b>{r.medicine_name}</b><small>{r.batch_number} · FEFO</small></td><td>{Number(r.quantity).toLocaleString('en-IN')} units</td><td>{r.days_left<0?`${Math.abs(r.days_left)} days expired`:`${r.days_left} days`}</td><td>{round(r.daily_velocity)} / day</td><td>{round(r.projected_remaining)} units</td><td><span className={`intelligence-status ${r.stock_status.toLowerCase()}`}>{r.restock_recommended?'RESTOCK · ':''}{r.stock_status.replaceAll('_',' ')}</span></td><td>{r.discount_percentage>0?<><b>{r.discount_percentage}% off</b><small>{money(r.offer_price)} from {money(r.unit_price_inr)}</small></>:r.stock_status==='CHARITY_FALLBACK'?<b>Free fallback</b>:r.stock_status==='EXPIRED'?<b>Blocked</b>:'—'}</td><td>{actions(r)}</td></tr>):<tr><td colSpan="8" className="empty-row">No medicine batches found.</td></tr>}
    </tbody></table></div>
    <div className="intelligence-foot">Restock alerts trigger at ≤ {data?.restock_days_threshold??15} estimated days of stock. Offers are calculated by days to expiry; charity fallback only flags eligible stock for a later workflow.</div>
  </section>
}
