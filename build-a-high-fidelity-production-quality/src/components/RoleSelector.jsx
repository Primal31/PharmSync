import { Building2, HeartHandshake, Store, UserRound } from 'lucide-react'
const roles = [
  { value: 'patient', label: 'Patient / User', icon: UserRound, hint: 'Find eligible discounted medicine' },
  { value: 'retail_chemist', label: 'Retail chemist', icon: Store, hint: 'Pharmacy or medical store' },
  { value: 'clinic_phc', label: 'Clinic / PHC', icon: Building2, hint: 'Clinic or health centre' },
  { value: 'charity_ngo', label: 'Charity / NGO', icon: HeartHandshake, hint: 'Verified charitable care' },
]
export default function RoleSelector({ value, onChange }) {
  return <div className="role-selector">{roles.map(({ value: role, label, icon: Icon, hint }) => <button type="button" key={role} className={`role-option ${value === role ? 'selected' : ''}`} onClick={() => onChange(role)} aria-pressed={value === role}><Icon size={17}/><span><b>{label}</b><small>{hint}</small></span><i/></button>)}</div>
}
