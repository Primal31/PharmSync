import axios from 'axios'
const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:5001/api', headers: { 'Content-Type': 'application/json' }, timeout: 12000 })
api.interceptors.request.use((config) => {
  const token = window.localStorage.getItem('pharmsync_token') || window.sessionStorage.getItem('pharmsync_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
api.interceptors.response.use((response) => response, (error) => {
  error.userMessage = !error.response ? 'Unable to connect to the PharmSync server.' : (error.response.data?.message || 'Unable to complete your request right now.')
  return Promise.reject(error)
})
export default api
