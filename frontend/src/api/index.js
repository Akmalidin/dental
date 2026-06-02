import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1/',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  },
})

// Attach CSRF token from cookie
api.interceptors.request.use(config => {
  const csrfToken = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='))
  if (csrfToken) {
    config.headers['X-CSRFToken'] = csrfToken.split('=')[1]
  }
  return config
})

api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      window.location.href = '/login/'
    }
    return Promise.reject(error)
  }
)

export const patientsApi = {
  list: (params) => api.get('patients/', { params }),
  get: (id) => api.get(`patients/${id}/`),
  create: (data) => api.post('patients/', data),
  update: (id, data) => api.patch(`patients/${id}/`, data),
  delete: (id) => api.delete(`patients/${id}/`),
}

export const appointmentsApi = {
  list: (params) => api.get('appointments/', { params }),
  calendar: (params) => api.get('appointments/calendar/', { params }),
  create: (data) => api.post('appointments/', data),
  update: (id, data) => api.patch(`appointments/${id}/`, data),
  delete: (id) => api.delete(`appointments/${id}/`),
  availableSlots: (doctor, date) => api.get('appointments/available-slots/', { params: { doctor, date } }),
}

export const treatmentsApi = {
  list: (params) => api.get('treatments/', { params }),
  get: (id) => api.get(`treatments/${id}/`),
  create: (data) => api.post('treatments/', data),
  update: (id, data) => api.patch(`treatments/${id}/`, data),
}

export const financeApi = {
  payments: (params) => api.get('finance/payments/', { params }),
  createPayment: (data) => api.post('finance/payments/', data),
  summary: (period) => api.get('finance/summary/', { params: { period } }),
  debtors: () => api.get('finance/debtors/'),
}

export const notificationsApi = {
  list: () => api.get('notifications/'),
  unreadCount: () => api.get('notifications/unread-count/'),
  markAllRead: () => api.post('notifications/mark-all-read/'),
}

export default api
