<template>
  <div class="space-y-4">
    <div class="flex justify-between items-center">
      <h2 class="font-semibold text-gray-800">{{ t('appointments.title') }}</h2>
      <button class="btn-primary">{{ t('appointments.newAppointment') }}</button>
    </div>
    <div class="card overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
          <tr>
            <th class="px-6 py-3 text-left">{{ t('common.patient') }}</th>
            <th class="px-6 py-3 text-left">{{ t('common.doctor') }}</th>
            <th class="px-6 py-3 text-left">{{ t('appointments.dateTime') }}</th>
            <th class="px-6 py-3 text-left">{{ t('appointments.service') }}</th>
            <th class="px-6 py-3 text-left">{{ t('common.status') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <tr v-for="a in appointments" :key="a.id" class="hover:bg-gray-50">
            <td class="px-6 py-3 font-medium text-gray-800">{{ a.patient_name || '—' }}</td>
            <td class="px-6 py-3 text-gray-600">{{ a.doctor_name }}</td>
            <td class="px-6 py-3 text-gray-600">{{ formatDT(a.start_at) }}</td>
            <td class="px-6 py-3 text-gray-600">{{ a.service_name || '—' }}</td>
            <td class="px-6 py-3">
              <span :class="statusClass(a.status)" class="text-xs px-2 py-0.5 rounded-full">
                {{ statusLabel(a.status) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { appointmentsApi } from '@/api'

const { t, locale } = useI18n()

const appointments = ref([])

onMounted(async () => {
  const { data } = await appointmentsApi.list({ ordering: '-start_at' })
  appointments.value = data.results || data
})

function formatDT(dt) {
  return new Date(dt).toLocaleString(locale.value === 'ky' ? 'ky-KG' : 'ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const STATUS_CLASS = {
  scheduled: 'badge-yellow',
  confirmed: 'badge-blue',
  arrived: 'badge-blue',
  in_progress: 'badge-blue',
  completed: 'badge-green',
  no_show: 'badge-red',
  cancelled: 'badge-gray',
}
function statusLabel(s) { return t(`appointments.status.${s}`, s) }
function statusClass(s) { return STATUS_CLASS[s] || 'badge-gray' }
</script>
