<template>
  <div class="space-y-6">
    <!-- Stats -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <div v-for="stat in stats" :key="stat.label" class="card p-5">
        <p class="text-xs text-gray-500 uppercase tracking-wide font-medium">{{ stat.label }}</p>
        <p class="mt-2 text-2xl font-bold text-gray-900">{{ stat.value }}</p>
        <p v-if="stat.sub" class="text-xs text-gray-400 mt-1">{{ stat.sub }}</p>
      </div>
    </div>

    <!-- Finance chart area (placeholder) -->
    <div class="card p-6">
      <h2 class="font-semibold text-gray-800 mb-4">Финансовая сводка за месяц</h2>
      <div class="grid grid-cols-3 gap-4 text-center">
        <div>
          <p class="text-2xl font-bold text-green-600">{{ summary.income }} сом</p>
          <p class="text-xs text-gray-500 mt-1">Выручка</p>
        </div>
        <div>
          <p class="text-2xl font-bold text-red-500">{{ summary.expenses }} сом</p>
          <p class="text-xs text-gray-500 mt-1">Расходы</p>
        </div>
        <div>
          <p class="text-2xl font-bold text-primary">{{ summary.net }} сом</p>
          <p class="text-xs text-gray-500 mt-1">Прибыль</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { financeApi } from '@/api'

const stats = ref([
  { label: 'Приёмов сегодня', value: '—' },
  { label: 'Новых пациентов', value: '—' },
  { label: 'Выручка сегодня', value: '—', sub: 'сом' },
  { label: 'Должников', value: '—' },
])

const summary = ref({ income: 0, expenses: 0, net: 0 })

onMounted(async () => {
  try {
    const { data } = await financeApi.summary('month')
    summary.value = data
  } catch (e) {
    // pass
  }
})
</script>
