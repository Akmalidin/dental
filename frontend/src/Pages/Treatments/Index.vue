<template>
  <div class="space-y-4">
    <div class="flex justify-between items-center">
      <h2 class="font-semibold text-gray-800">{{ t('treatments.title') }}</h2>
      <button class="btn-primary">{{ t('treatments.newTreatment') }}</button>
    </div>
    <div class="card overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-gray-600 text-xs uppercase">
          <tr>
            <th class="px-6 py-3 text-left">#</th>
            <th class="px-6 py-3 text-left">{{ t('common.patient') }}</th>
            <th class="px-6 py-3 text-left">{{ t('common.doctor') }}</th>
            <th class="px-6 py-3 text-left">{{ t('common.amount') }}</th>
            <th class="px-6 py-3 text-left">{{ t('treatments.paid') }}</th>
            <th class="px-6 py-3 text-left">{{ t('treatments.debt') }}</th>
            <th class="px-6 py-3 text-left">{{ t('common.status') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <tr v-for="item in treatments" :key="item.id" class="hover:bg-gray-50">
            <td class="px-6 py-3 text-gray-500">{{ item.id }}</td>
            <td class="px-6 py-3 font-medium text-gray-800">{{ item.patient_name }}</td>
            <td class="px-6 py-3 text-gray-600">{{ item.doctor_name }}</td>
            <td class="px-6 py-3 text-gray-800">{{ item.total_amount }} {{ t('common.currency') }}</td>
            <td class="px-6 py-3 text-green-600">{{ item.paid_amount }} {{ t('common.currency') }}</td>
            <td class="px-6 py-3" :class="item.debt > 0 ? 'text-red-600 font-semibold' : 'text-gray-400'">
              {{ item.debt }} {{ t('common.currency') }}
            </td>
            <td class="px-6 py-3">
              <span class="text-xs px-2 py-0.5 rounded-full badge-blue">{{ item.status }}</span>
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
import { treatmentsApi } from '@/api'

const { t } = useI18n()

const treatments = ref([])

onMounted(async () => {
  const { data } = await treatmentsApi.list()
  treatments.value = data.results || data
})
</script>
