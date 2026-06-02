<template>
  <div class="flex h-screen bg-gray-50">
    <!-- Sidebar -->
    <aside class="w-64 bg-gray-900 text-white flex flex-col shrink-0">
      <!-- Logo -->
      <div class="flex items-center gap-3 px-5 py-5 border-b border-gray-700">
        <div class="h-9 w-9 rounded-lg bg-primary flex items-center justify-center font-bold text-sm">AKM</div>
        <div>
          <p class="text-sm font-semibold">AKM SOFT CLINIC</p>
          <p class="text-xs text-gray-400">CRM система</p>
        </div>
      </div>

      <!-- Nav -->
      <nav class="flex-1 overflow-y-auto py-4 px-2 space-y-1 text-sm">
        <router-link v-for="item in navItems" :key="item.to" :to="item.to"
          class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
          active-class="!bg-primary !text-white">
          <component :is="item.icon" class="h-5 w-5 shrink-0" />
          {{ item.label }}
        </router-link>
      </nav>

      <!-- User -->
      <div class="px-4 py-4 border-t border-gray-700">
        <div class="flex items-center gap-3">
          <div class="h-8 w-8 rounded-full bg-primary flex items-center justify-center text-xs font-bold">A</div>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium truncate">Администратор</p>
          </div>
          <button @click="logout" class="text-gray-400 hover:text-white text-xs">Выйти</button>
        </div>
      </div>
    </aside>

    <!-- Main -->
    <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
      <header class="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between shrink-0">
        <h1 class="text-lg font-semibold text-gray-800">{{ currentPageTitle }}</h1>
      </header>
      <main class="flex-1 overflow-y-auto p-6">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const navItems = [
  { to: '/', label: 'Дашборд', icon: 'span' },
  { to: '/patients', label: 'Пациенты', icon: 'span' },
  { to: '/calendar', label: 'Расписание', icon: 'span' },
  { to: '/treatments', label: 'Приёмы', icon: 'span' },
  { to: '/finance', label: 'Финансы', icon: 'span' },
]

const titleMap = {
  dashboard: 'Дашборд',
  patients: 'Пациенты',
  'patient-detail': 'Карточка пациента',
  calendar: 'Расписание',
  appointments: 'Записи',
  treatments: 'Приёмы',
  finance: 'Финансы',
}

const currentPageTitle = computed(() => titleMap[route.name] || 'AKM SOFT CLINIC')

async function logout() {
  try {
    await fetch('/logout/', { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') } })
  } finally {
    window.location.href = '/login/'
  }
}

function getCookie(name) {
  return document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith(name + '='))?.split('=')[1] || ''
}
</script>
