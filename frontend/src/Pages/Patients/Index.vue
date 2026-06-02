<template>
  <div class="space-y-4">
    <!-- Toolbar -->
    <div class="flex items-center gap-3">
      <input v-model="search" type="text" placeholder="Поиск по имени, телефону..."
             class="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
             @input="debouncedSearch">
      <button @click="$router.push('/patients/create')"
              class="bg-primary text-white text-sm px-4 py-2 rounded-lg hover:bg-primary-dark">
        + Новый пациент
      </button>
    </div>

    <!-- Table -->
    <div class="card overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
          <tr>
            <th class="px-6 py-3 text-left">Пациент</th>
            <th class="px-6 py-3 text-left">Телефон</th>
            <th class="px-6 py-3 text-left">Баланс</th>
            <th class="px-6 py-3 text-left">Дата</th>
            <th class="px-6 py-3"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <tr v-for="p in patients" :key="p.id" class="hover:bg-gray-50">
            <td class="px-6 py-3">
              <router-link :to="`/patients/${p.id}`" class="font-medium text-gray-800 hover:text-primary">
                {{ p.full_name }}
              </router-link>
              <span v-if="p.age" class="text-xs text-gray-400 ml-1">{{ p.age }} лет</span>
            </td>
            <td class="px-6 py-3 text-gray-600">{{ p.phone }}</td>
            <td class="px-6 py-3" :class="p.balance < 0 ? 'text-red-600 font-semibold' : 'text-gray-600'">
              {{ p.balance }} сом
            </td>
            <td class="px-6 py-3 text-gray-400 text-xs">{{ formatDate(p.created_at) }}</td>
            <td class="px-6 py-3 text-right">
              <router-link :to="`/patients/${p.id}`" class="text-xs text-primary hover:underline">Подробно</router-link>
            </td>
          </tr>
          <tr v-if="!loading && patients.length === 0">
            <td colspan="5" class="px-6 py-12 text-center text-gray-400">Пациентов не найдено</td>
          </tr>
          <tr v-if="loading">
            <td colspan="5" class="px-6 py-8 text-center text-gray-400">Загрузка...</td>
          </tr>
        </tbody>
      </table>

      <!-- Pagination -->
      <div v-if="total > pageSize" class="px-6 py-3 flex items-center justify-between border-t border-gray-100">
        <span class="text-sm text-gray-500">Всего: {{ total }}</span>
        <div class="flex gap-2">
          <button @click="page--" :disabled="page === 1"
                  class="px-3 py-1.5 text-xs border border-gray-200 rounded-lg disabled:opacity-40">← Пред.</button>
          <button @click="page++" :disabled="page * pageSize >= total"
                  class="px-3 py-1.5 text-xs border border-gray-200 rounded-lg disabled:opacity-40">След. →</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { patientsApi } from '@/api'

const patients = ref([])
const search = ref('')
const loading = ref(false)
const page = ref(1)
const total = ref(0)
const pageSize = 15

let debounceTimer

async function fetchPatients() {
  loading.value = true
  try {
    const { data } = await patientsApi.list({ search: search.value, page: page.value })
    patients.value = data.results || data
    total.value = data.count || data.length
  } finally {
    loading.value = false
  }
}

function debouncedSearch() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => { page.value = 1; fetchPatients() }, 400)
}

function formatDate(dt) {
  if (!dt) return ''
  return new Date(dt).toLocaleDateString('ru-RU')
}

watch(page, fetchPatients)
onMounted(fetchPatients)
</script>
