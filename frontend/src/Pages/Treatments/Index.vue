<template>
  <div class="space-y-4">
    <div class="flex justify-between items-center">
      <h2 class="font-semibold text-gray-800">Приёмы</h2>
      <button class="btn-primary">+ Новый приём</button>
    </div>
    <div class="card overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-gray-600 text-xs uppercase">
          <tr>
            <th class="px-6 py-3 text-left">#</th>
            <th class="px-6 py-3 text-left">Пациент</th>
            <th class="px-6 py-3 text-left">Врач</th>
            <th class="px-6 py-3 text-left">Сумма</th>
            <th class="px-6 py-3 text-left">Оплачено</th>
            <th class="px-6 py-3 text-left">Долг</th>
            <th class="px-6 py-3 text-left">Статус</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <tr v-for="t in treatments" :key="t.id" class="hover:bg-gray-50">
            <td class="px-6 py-3 text-gray-500">{{ t.id }}</td>
            <td class="px-6 py-3 font-medium text-gray-800">{{ t.patient_name }}</td>
            <td class="px-6 py-3 text-gray-600">{{ t.doctor_name }}</td>
            <td class="px-6 py-3 text-gray-800">{{ t.total_amount }} сом</td>
            <td class="px-6 py-3 text-green-600">{{ t.paid_amount }} сом</td>
            <td class="px-6 py-3" :class="t.debt > 0 ? 'text-red-600 font-semibold' : 'text-gray-400'">
              {{ t.debt }} сом
            </td>
            <td class="px-6 py-3">
              <span class="text-xs px-2 py-0.5 rounded-full badge-blue">{{ t.status }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { treatmentsApi } from '@/api'

const treatments = ref([])

onMounted(async () => {
  const { data } = await treatmentsApi.list()
  treatments.value = data.results || data
})
</script>
