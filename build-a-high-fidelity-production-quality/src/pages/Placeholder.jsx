import { Link } from 'react-router-dom'
import Navbar from '../components/Navbar'
import { ArrowLeft, Activity } from 'lucide-react'
export default function Placeholder({title}){return <div className="site-shell"><Navbar/><main className="placeholder-page wrap"><div className="placeholder-card"><span className="placeholder-icon"><Activity/></span><span className="eyebrow">PHARMSYNC PLATFORM</span><h1>{title}</h1><p>Module coming in the next development phase.</p><Link to="/" className="button button-green"><ArrowLeft size={16}/> Back to overview</Link></div></main></div>}
