import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, ArrowDownRight, ArrowLeftRight, Boxes, Building2, CalendarDays, CircleDollarSign, HeartHandshake, Package, RefreshCw, Search, ShieldCheck, ShoppingBag, Sparkles, Truck, Users, Zap } from 'lucide-react'
import Navbar from '../components/Navbar'
import { useAuth } from '../context/AuthContext'
import api from '../services/api'

const number = value => Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 1 })
const rupees = value => `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const day = value => value == null ? '—' : `${number(value)} d`
const statusText = value => String(value || '').replaceAll('_', ' ')
const statusClass = value => String(value || '').toLowerCase().replaceAll('_', '-')

function Metric({ label, value, detail, Icon, tone = '' }) {
  return <article className={`step8-metric ${tone}`}><span className="step8-metric-icon"><Icon size={17}/></span><small>{label}</small><b>{value == null ? '—' : number(value)}</b><em>{detail}</em></article>
}

function Empty({ children = 'No data available for this view.' }) { return <div className="step8-empty">{children}</div> }

function Table({ columns, rows, empty }) {
  if (!rows?.length) return <Empty>{empty || 'No data available for this view.'}</Empty>
  return <div className="step8-table-wrap"><table className="step8-table"><thead><tr>{columns.map(col => <th key={col.key}>{col.label}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={row.batch_id || row.transfer_id || row.order_id || row.medicine_id || `${i}`}>
    {columns.map(col => <td key={col.key}>{col.render ? col.render(row[col.key], row) : row[col.key] ?? '—'}</td>)}
  </tr>)}</tbody></table></div>
}

function HealthChart({ health }) {
  const entries = [
    ['HEALTHY', 'Healthy', '#5fd6a7'], ['AT_RISK_90_DAYS', '30% discount', '#a5d98b'],
    ['AT_RISK_60_DAYS', '50% discount', '#e8bc71'], ['CRITICAL_30_DAYS', 'Charity fallback', '#ed9275'], ['EXPIRED', 'Expired', '#e36b75'],
  ].map(([key, label, color]) => ({ key, label, color, ...(health?.categories?.[key] || {}) }))
  const total = entries.reduce((sum, item) => sum + Number(item.units || 0), 0)
  let cursor = 0
  const stops = entries.map(item => { const start = cursor; cursor += total ? Number(item.units || 0) / total * 100 : 0; return `${item.color} ${start}% ${cursor}%` })
  return <div className="step8-health"><div className="step8-donut" style={{ background: total ? `conic-gradient(${stops.join(',')})` : '#1b2a24' }}><div><b>{number(total)}</b><small>units</small></div></div><div className="step8-legend">{entries.map(row => <div key={row.key}><i style={{ background: row.color }}/><span>{row.label}</span><b>{number(row.units)}</b><small>{number(row.percentage)}%</small></div>)}</div></div>
}

export default function Analytics() {
  const { user } = useAuth()
  const [period, setPeriod] = useState('30d')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [asking, setAsking] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const params = { period }
      if (period === 'custom') { params.start = start; params.end = end }
      const response = await api.get('/analytics/dashboard', { params })
      setData(response.data)
    } catch (e) { setError(e.userMessage || 'Unable to load analytics. Please try again.') }
    finally { setLoading(false) }
  }, [period, start, end])
  useEffect(() => { if (period !== 'custom' || (start && end)) load() }, [load, period, start, end])

  const ask = async event => {
    event.preventDefault(); if (!question.trim()) return
    setAsking(true); setAnswer(null)
    try { const params = { period }; if (period === 'custom') { params.start = start; params.end = end } const response = await api.post('/analytics/query', { question: question.trim() }, { params }); setAnswer(response.data) }
    catch (e) { setAnswer({ error: e.userMessage || 'Unable to answer this analytics question.' }) }
    finally { setAsking(false) }
  }

  const summary = data?.summary || {}
  const cards = useMemo(() => [
    [user?.role === 'charity_ngo' ? 'Fallback batches' : 'Active batches', summary.total_active_batches, user?.role === 'charity_ngo' ? 'Near-expiry fallback snapshot' : 'Current inventory snapshot', Boxes, ''],
    [user?.role === 'charity_ngo' ? 'Fallback units' : 'Available units', summary.total_units, 'After active reservations', Package, 'mint'],
    ['Expiry-risk units', summary.expiry_risk_units, 'Not including expired stock', AlertTriangle, 'amber'],
    ['Active discounts', summary.active_discounts, '30% and 50% eligible batches', CircleDollarSign, 'blue'],
    ['Restock alerts', summary.restock_alerts, `≤ ${data?.restock?.threshold_days ?? '—'} days estimated cover`, ArrowDownRight, 'blue'],
    ['P2P opportunities', summary.redistribution_opportunities, 'Current eligible matches', ArrowLeftRight, 'mint'],
    ['Units redistributed', summary.units_redistributed, `Selected period · ${period}`, Truck, ''],
    ['Active patient orders', summary.active_orders, 'Pending, confirmed, or ready', ShoppingBag, ''],
  ], [summary, data, period, user?.role])

  const expiryRows = data?.expiry_risk?.rows || []
  const restockRows = data?.restock?.rows || []
  const velocityRows = data?.velocity?.rows || []
  const insightData = data?.insights || { fallback: true, insights: [] }

  return <div className="site-shell module-shell"><Navbar/><main className="module-page wrap transfers-page step8-page">
    <header className="step8-heading"><div><span className="eyebrow"><span/> NETWORK INTELLIGENCE · STEP 8</span><h1>PharmSync <em>Analytics</em></h1><p>Explainable inventory, demand, patient order, and redistribution insights from the connected network.</p><div className="step8-scope"><ShieldCheck size={14}/>{user?.organizationName || user?.nodeId || 'Your account'} <i/> MySQL live data <i/> Inventory is a current snapshot</div></div><div className="step8-toolbar"><label><CalendarDays size={15}/><select value={period} onChange={e => setPeriod(e.target.value)} aria-label="Analytics period"><option value="7d">Last 7 days</option><option value="30d">Last 30 days</option><option value="90d">Last 90 days</option><option value="custom">Custom</option></select></label>{period === 'custom' && <><input type="date" value={start} onChange={e => setStart(e.target.value)} aria-label="Start date"/><input type="date" value={end} onChange={e => setEnd(e.target.value)} aria-label="End date"/></>}<button className="button button-quiet" onClick={load} disabled={loading}><RefreshCw size={14} className={loading ? 'spinner-icon' : ''}/> Refresh</button></div></header>
    {error && <div className="module-error" role="alert">{error}<button onClick={load}>Retry</button></div>}
    {loading && !data ? <div className="step8-loading"><span/><span/><span/><span/></div> : <>
      <section className="step8-metrics-grid" aria-label="Executive summary">{cards.map(([label,value,detail,Icon,tone]) => <Metric key={label} label={label} value={value} detail={detail} Icon={Icon} tone={tone}/>)}</section>

      <div className="step8-two-col">
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">CURRENT INVENTORY SNAPSHOT</span><h2><Activity size={17}/>Inventory health</h2></div><span className="step8-count">{number(data?.inventory_health?.batches)} batches</span></div><HealthChart health={data?.inventory_health}/><p className="step8-footnote">Categories and discount stages follow the Step 5 expiry rules. Expired batches are shown separately and are not sellable.</p></section>
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">VERIFIED NETWORK</span><h2><Building2 size={17}/>Network health</h2></div><span className="step8-live"><i/> Live</span></div><div className="step8-network-grid">{[['Connected nodes',data?.network?.verified_nodes,Users],['Pharmacies',data?.network?.pharmacy_nodes,Building2],['Clinics / PHCs',data?.network?.clinic_nodes,ShieldCheck],['Supply nodes',data?.network?.supply_nodes,Package],['Demand nodes',data?.network?.demand_nodes,Activity],['Active shortage units',data?.network?.network_shortage_units,ArrowDownRight]].map(([label,value,Icon])=><div key={label}><Icon size={15}/><span>{label}</span><b>{number(value)}</b></div>)}</div><p className="step8-footnote">Node counts use verified/active network records. Supply and demand reflect current data.</p></section>
      </div>

      <section className="step8-panel step8-wide"><div className="step8-panel-head"><div><span className="tiny-label">BATCH-LEVEL · FEFO ORDER</span><h2><AlertTriangle size={17}/>Expiry risk</h2></div><span className="step8-count">{number(data?.expiry_risk?.count)} batches</span></div><Table empty="No expiry-risk inventory detected." rows={expiryRows} columns={[
        {key:'medicine_name',label:'Medicine'}, {key:'batch_number',label:'Batch'}, {key:'pharmacy_name',label:'Pharmacy'}, {key:'quantity',label:'Available',render:v=>`${number(v)} units`}, {key:'days_left',label:'Days left',render:v=>day(v)}, {key:'projected_remaining',label:'Projected remaining',render:v=>`${number(v)} units`}, {key:'risk_status',label:'Risk',render:v=><span className={`step8-status ${statusClass(v)}`}>{statusText(v)}</span>}, {key:'discount_percentage',label:'Offer',render:(v,row)=>row.stock_status==='CHARITY_FALLBACK'?<span className="step8-status charity-fallback">Charity fallback</span>:v?`${v}%`:'—'}
      ]}/></section>

      <div className="step8-two-col">
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">SELECTED PERIOD · {period.toUpperCase()}</span><h2><CircleDollarSign size={17}/>Sales performance</h2></div><a href="/sales" className="step8-text-link">Open sales →</a></div><div className="step8-sales-summary"><div><small>Sales records</small><b>{number(data?.sales?.records)}</b></div><div><small>Units sold</small><b>{number(data?.sales?.units)}</b></div><div><small>Recorded revenue</small><b>{rupees(data?.sales?.revenue)}</b></div></div><Table rows={data?.sales?.top_medicines || []} empty="No sales recorded in this period." columns={[{key:'medicine_name',label:'Top sold medicines'},{key:'medicine_id',label:'Medicine ID'},{key:'units',label:'Units sold',render:v=>number(v)}]}/></section>
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">ACTUAL RECEIVED / COMPLETED RECORDS</span><h2><Truck size={17}/>Redistribution performance</h2></div><span className="step8-count">{number(data?.redistribution?.units_redistributed)} units</span></div><div className="step8-status-bars">{Object.entries(data?.redistribution?.status_distribution || {}).map(([status,value])=><div key={status}><span>{statusText(status)}</span><div><i style={{width:`${Math.min(100,Number(value||0)/Math.max(1,...Object.values(data?.redistribution?.status_distribution||{}).map(Number))*100)}%`}}/></div><b>{number(value)}</b></div>)}</div><Table rows={data?.redistribution_details?.top_medicines || []} empty="No completed transfer records in this period." columns={[{key:'medicine_name',label:'Top redistributed medicines'},{key:'medicine_id',label:'Medicine ID'},{key:'units',label:'Units',render:v=>number(v)}]}/></section>
      </div>
      <div className="step8-two-col">
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">COMPLETED TRANSFERS</span><h2><Building2 size={17}/>Source & destination nodes</h2></div></div><div className="step8-node-tables"><div><small>Source pharmacies</small><Table rows={data?.redistribution_details?.source_nodes||[]} empty="No source transfer records." columns={[{key:'name',label:'Pharmacy'},{key:'units',label:'Units',render:v=>number(v)}]}/></div><div><small>Destination clinics</small><Table rows={data?.redistribution_details?.destination_nodes||[]} empty="No destination transfer records." columns={[{key:'name',label:'Clinic'},{key:'units',label:'Units',render:v=>number(v)}]}/></div></div></section>
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">CURRENT NETWORK CONDITIONS</span><h2><Activity size={17}/>Demand & surplus</h2></div></div><div className="step8-node-tables"><div><small>Highest reported shortages</small><Table rows={data?.network?.top_demand_medicines||[]} empty="No active shortage records." columns={[{key:'medicine_name',label:'Medicine'},{key:'shortage_units',label:'Shortage',render:v=>number(v)},{key:'clinic_count',label:'Clinics',render:v=>number(v)}]}/></div><div><small>Aggregate potential surplus</small><Table rows={data?.network?.potential_surplus_medicines||[]} empty="No aggregate surplus identified." columns={[{key:'medicine_name',label:'Medicine'},{key:'available_units',label:'Supply',render:v=>number(v)},{key:'potential_surplus_units',label:'Beyond shortages',render:v=>number(v)}]}/><p className="step8-footnote">Aggregate comparison only. A surplus is not a confirmed transfer opportunity; use P2P matching for verified node-level eligibility.</p></div></div></section>
      </div>

      <div className="step8-two-col">
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">TRAILING 30-DAY SALES / 30</span><h2><Zap size={17}/>Stock velocity</h2></div></div><Table rows={velocityRows.slice(0,8)} empty="No inventory batches available." columns={[{key:'medicine_name',label:'Medicine'},{key:'quantity',label:'Stock',render:v=>number(v)},{key:'quantity_30d',label:'30-day sales',render:v=>number(v)},{key:'daily_velocity',label:'Units / day',render:v=>Number(v||0).toFixed(2)},{key:'estimated_days_of_stock',label:'Cover',render:v=>v==null?'No sales':day(v)},{key:'movement_category',label:'Movement',render:v=><span className={`step8-status ${statusClass(v)}`}>{statusText(v)}</span>}]} /></section>
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">CONFIGURED COVERAGE THRESHOLD</span><h2><ArrowDownRight size={17}/>Restock intelligence</h2></div><span className="step8-count">≤ {number(data?.restock?.threshold_days)} days</span></div><Table rows={restockRows.slice(0,8)} empty="No restock alerts detected. Zero-sales items do not trigger restock alerts." columns={[{key:'medicine_name',label:'Medicine'},{key:'pharmacy_name',label:'Pharmacy'},{key:'quantity',label:'Stock',render:v=>number(v)},{key:'daily_velocity',label:'Units / day',render:v=>Number(v||0).toFixed(2)},{key:'estimated_days_of_stock',label:'Estimated cover',render:v=>day(v)},{key:'restock_recommended',label:'Status',render:()=> <span className="step8-status restock">Recommended</span>}]} /></section>
      </div>

      <div className="step8-two-col">
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">CURRENT ELIGIBLE STOCK</span><h2><CircleDollarSign size={17}/>Discount inventory</h2></div></div><div className="step8-discount-cards">{[['30% offer',data?.discounts?.discount_30,'mint'],['50% offer',data?.discounts?.discount_50,'amber']].map(([label,item,tone])=><article className={`step8-discount ${tone}`} key={label}><small>{label}</small><b>{number(item?.units)} <i>units</i></b><span>{number(item?.batches)} batches</span><div>List {rupees(item?.original_value)} <i>→</i> Offer {rupees(item?.discounted_value)}</div></article>)}<article className="step8-discount coral"><small>Charity fallback</small><b>{number(data?.discounts?.charity_fallback?.units)} <i>units</i></b><span>{number(data?.discounts?.charity_fallback?.batches)} batches</span><div>Flagged for later review · not an automatic donation</div></article></div></section>
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">SELECTED PERIOD · {period.toUpperCase()}</span><h2><ArrowLeftRight size={17}/>Redistribution</h2></div><a href="/transfers" className="step8-text-link">Open transfers →</a></div><div className="step8-transfer-kpis">{[['Suggested',data?.redistribution?.opportunities],['Pending',data?.redistribution?.pending],['In transit',data?.redistribution?.in_transit],['Completed',data?.redistribution?.completed],['Units moved',data?.redistribution?.units_redistributed]].map(([label,value])=><div key={label}><b>{number(value)}</b><small>{label}</small></div>)}</div><p className="step8-footnote">Suggested matches are separate from actual completed transfers. Units moved count received/completed transfer records only.</p></section>
      </div>

      <div className="step8-two-col">
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">SELECTED PERIOD · {period.toUpperCase()}</span><h2><ShoppingBag size={17}/>Patient marketplace</h2></div><a href="/pharmacy/orders" className="step8-text-link">View requests →</a></div><div className="step8-order-grid">{[['Total orders',data?.orders?.total],['Pending',data?.orders?.pending],['Confirmed',data?.orders?.confirmed],['Ready for pickup',data?.orders?.ready_for_pickup],['Completed',data?.orders?.completed],['Cancelled',data?.orders?.cancelled]].map(([label,value])=><div key={label}><small>{label}</small><b>{number(value)}</b></div>)}</div><p className="step8-footnote">Orders are scoped to your pharmacy account; patient names and identifiers are not shown. Completed discounted sales: {number(data?.orders?.discounted_order_units)} units across {number(data?.orders?.discounted_order_count)} requests.</p><div className="step8-node-tables"><div><small>Most requested medicines</small><Table rows={data?.orders?.top_medicines||[]} empty="No patient medicine requests in this period." columns={[{key:'medicine_name',label:'Medicine'},{key:'requests',label:'Requests',render:v=>number(v)},{key:'units',label:'Units',render:v=>number(v)}]}/></div><div><small>Discounted medicine requests</small><Table rows={data?.orders?.discounted_medicines||[]} empty="No discounted medicine requests in this period." columns={[{key:'medicine_name',label:'Medicine'},{key:'requests',label:'Requests',render:v=>number(v)},{key:'units',label:'Units',render:v=>number(v)}]}/></div></div></section>
        <section className="step8-panel"><div className="step8-panel-head"><div><span className="tiny-label">EVIDENCE-BASED IMPACT</span><h2><HeartHandshake size={17}/>Waste-risk & rescue</h2></div></div><div className="step8-impact-list">{[['Expiry-risk units',data?.impact?.expiry_risk_units,'Identified at risk; not yet rescued'],['Discounted units',Number(data?.impact?.discount_30_units||0)+Number(data?.impact?.discount_50_units||0),'Currently eligible inventory'],['Redistributed units',data?.impact?.redistributed_units,'Actual completed transfers'],['Completed discounted sales',data?.impact?.completed_discounted_sales_units,'Completed patient order quantity'],['Charity fallback units',data?.impact?.charity_fallback_units,'Flagged; no donation implied'],['Actually donated units',data?.impact?.actual_donated_units,'Completed donation records']].map(([label,value,detail])=><div key={label}><span>{label}<small>{detail}</small></span><b>{number(value)}</b></div>)}</div></section>
      </div>

      <section className="step8-panel step8-ai-panel"><div className="step8-panel-head"><div><span className="tiny-label">EXPLAINABLE DECISION SUPPORT</span><h2><Sparkles size={18}/>AI Network Intelligence</h2></div><span className={insightData.fallback?'step8-fallback':'step8-live'}>{insightData.fallback?'Deterministic insights':`${insightData.provider} insights`}</span></div>{insightData.fallback&&<p className="step8-ai-note">AI insights temporarily unavailable. Showing deterministic network summary.</p>}<div className="step8-insights">{(insightData.insights||[]).length ? insightData.insights.map((item,i)=><article key={`${item.type}-${i}`}><span className="step8-insight-kind">{item.type}</span><div><b>Observation</b><p>{item.observation}</p><b>Why it matters</b><p>{item.why_it_matters}</p><b>Recommended action</b><p>{item.recommended_action}</p></div></article>) : <Empty>No current insights available.</Empty>}</div></section>

      <section className="step8-panel step8-ask-panel"><div className="step8-panel-head"><div><span className="tiny-label">CONTROLLED INTENT · PREDEFINED QUERIES</span><h2><Search size={17}/>Ask PharmSync</h2></div></div><form className="step8-ask-form" onSubmit={ask}><input value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Ask about expiry risk, restock, transfers, orders, demand, or charity fallback…" maxLength={500}/><button className="button button-green" disabled={asking||!question.trim()}>{asking?<RefreshCw size={14} className="spinner-icon"/>:<Search size={14}/>} Ask</button></form><div className="step8-suggestions">{['Which medicines are at highest expiry risk?','Which pharmacies need restocking?','How many units were redistributed?','Show current charity fallback inventory.'].map(text=><button key={text} onClick={()=>setQuestion(text)}>{text}</button>)}</div>{answer&&(answer.error?<div className="module-error">{answer.error}</div>:<div className="step8-answer"><b>{answer.title}</b><p>{answer.answer}</p><pre>{JSON.stringify(answer.result,null,2)}</pre></div>)}</section>
      <footer className="step8-disclaimer"><ShieldCheck size={14}/>Analytics are read-only. AI explains supplied metrics and cannot change stock, orders, prices, transfers, or donations. Activity uses {data?.scope?.period_start} to {data?.scope?.period_end}; inventory is current-state data.</footer>
    </>}
  </main></div>
}
