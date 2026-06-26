<template>
  <div class="space-y-6">
    <div class="grid grid-cols-3 gap-4">
      <div class="card p-5">
        <p class="text-xs text-gray-500 uppercase tracking-wide font-medium">{{ t('finance.incomeMonth') }}</p>
        <p class="mt-2 text-2xl font-bold text-green-600">{{ summary.income }} {{ t('common.currency') }}</p>
      </div>
      <div class="card p-5">
        <p class="text-xs text-gray-500 uppercase tracking-wide font-medium">{{ t('finance.expensesMonth') }}</p>
        <p class="mt-2 text-2xl font-bold text-red-500">{{ summary.expenses }} {{ t('common.currency') }}</p>
      </div>
      <div class="card p-5">
        <p class="text-xs text-gray-500 uppercase tracking-wide font-medium">{{ t('finance.profit') }}</p>
        <p class="mt-2 text-2xl font-bold text-primary">{{ summary.net }} {{ t('common.currency') }}</p>
      </div>
    </div>

    <div class="card overflow-hidden">
      <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <h2 class="font-semibold text-gray-800">{{ t('finance.recentPayments') }}</h2>
      </div>
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-gray-600 text-xs uppercase">
          <tr>
            <th class="px-6 py-3 text-left">{{ t('common.patient') }}</th>
            <th class="px-6 py-3 text-left">{{ t('common.amount') }}</th>
            <th class="px-6 py-3 text-left">{{ t('finance.method') }}</th>
            <th class="px-6 py-3 text-left">{{ t('common.date') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <tr v-for="p in payments" :key="p.id" class="hover:bg-gray-50">
            <td class="px-6 py-3 font-medium text-gray-800">{{ p.patient_name }}</td>
            <td class="px-6 py-3 text-green-600 font-semibold">{{ p.amount }} {{ t('common.currency') }}</td>
            <td class="px-6 py-3 text-gray-600 capitalize">{{ p.method }}</td>
            <td class="px-6 py-3 text-gray-400 text-xs">{{ formatDate(p.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { financeApi } from '@/api'

const { t, locale } = useI18n()

const summary = ref({ income: 0, expenses: 0, net: 0 })
const payments = ref([])

onMounted(async () => {
  const [sumRes, payRes] = await Promise.all([
    financeApi.summary('month'),
    financeApi.payments({ page: 1 }),
  ])
  summary.value = sumRes.data
  payments.value = payRes.data.results || payRes.data
})

function formatDate(dt) {
  return new Date(dt).toLocaleDateString(locale.value === 'ky' ? 'ky-KG' : 'ru-RU')
}
</script>
