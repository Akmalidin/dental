<template>
  <div class="space-y-4">
    <div class="flex justify-between items-center">
      <h2 class="font-semibold text-gray-800">Записи на приём</h2>
      <button class="btn-primary">+ Новая запись</button>
    </div>
    <div class="card overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
          <tr>
            <th class="px-6 py-3 text-left">Пациент</th>
            <th class="px-6 py-3 text-left">Врач</th>
            <th class="px-6 py-3 text-left">Дата/время</th>
            <th class="px-6 py-3 text-left">Услуга</th>
            <th class="px-6 py-3 text-left">Статус</th>
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
import { appointmentsApi } from '@/api'

const appointments = ref([])

onMounted(async () => {
  const { data } = await appointmentsApi.list({ ordering: '-start_at' })
  appointments.value = data.results || data
})

function formatDT(dt) {
  return new Date(dt).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const STATUS_MAP = {
  scheduled: ['Записан', 'badge-yellow'],
  confirmed: ['Подтверждён', 'badge-blue'],
  arrived: ['Пришёл', 'badge-blue'],
  in_progress: ['Принимается', 'badge-blue'],
  completed: ['Завершён', 'badge-green'],
  no_show: ['Не пришёл', 'badge-red'],
  cancelled: ['Отменён', 'badge-gray'],
}
function statusLabel(s) { return STATUS_MAP[s]?.[0] || s }
function statusClass(s) { return STATUS_MAP[s]?.[1] || 'badge-gray' }
</script>
