import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('@/Layouts/AppLayout.vue'),
    children: [
      { path: '', component: () => import('@/Pages/Dashboard/Index.vue'), name: 'dashboard' },
      { path: 'patients', component: () => import('@/Pages/Patients/Index.vue'), name: 'patients' },
      { path: 'patients/:id', component: () => import('@/Pages/Patients/Detail.vue'), name: 'patient-detail' },
      { path: 'appointments', component: () => import('@/Pages/Appointments/Index.vue'), name: 'appointments' },
      { path: 'calendar', component: () => import('@/Pages/Appointments/Calendar.vue'), name: 'calendar' },
      { path: 'treatments', component: () => import('@/Pages/Treatments/Index.vue'), name: 'treatments' },
      { path: 'finance', component: () => import('@/Pages/Finance/Index.vue'), name: 'finance' },
    ],
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
