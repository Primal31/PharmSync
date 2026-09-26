import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import api from '../services/api'
const AuthContext = createContext(null)
export const roleHome = { retail_chemist: '/inventory', clinic_phc: '/clinic', charity_ngo: '/charity', patient: '/medicines' }
export const roleLabel = { retail_chemist: 'Retail Chemist', clinic_phc: 'Clinic / PHC', charity_ngo: 'Charity / NGO', patient: 'Patient' }
const savedToken = () => window.localStorage.getItem('pharmsync_token') || window.sessionStorage.getItem('pharmsync_token')
export function AuthProvider({ children }) {
 const [user,setUser]=useState(null);const [token,setToken]=useState(savedToken);const [loading,setLoading]=useState(true)
 useEffect(()=>{let mounted=true;const restore=async()=>{if(!token){if(mounted)setLoading(false);return}try{const {data}=await api.get('/auth/me');if(mounted)setUser(data.user)}catch{window.localStorage.removeItem('pharmsync_token');window.sessionStorage.removeItem('pharmsync_token');if(mounted){setToken(null);setUser(null)}}finally{if(mounted)setLoading(false)}};restore();return()=>{mounted=false}},[token])
 const login=useCallback(async(credentials,remember=true)=>{const {data}=await api.post('/auth/login',credentials);window.localStorage.removeItem('pharmsync_token');window.sessionStorage.removeItem('pharmsync_token');(remember?window.localStorage:window.sessionStorage).setItem('pharmsync_token',data.token);setToken(data.token);setUser(data.user);return data.user},[])
 const register=useCallback(async(details)=>(await api.post('/auth/register',details)).data,[])
 const logout=useCallback(()=>{window.localStorage.removeItem('pharmsync_token');window.sessionStorage.removeItem('pharmsync_token');setToken(null);setUser(null)},[])
 const value=useMemo(()=>({user,token,isAuthenticated:Boolean(user&&token),login,register,logout,loading}),[user,token,login,register,logout,loading])
 return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
export function useAuth(){const context=useContext(AuthContext);if(!context)throw new Error('useAuth must be used inside AuthProvider');return context}
