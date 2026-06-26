<template>
  <div class="flex h-screen bg-gray-50">
    <!-- Sidebar -->
    <aside class="w-64 bg-gray-900 text-white flex flex-col shrink-0">
      <!-- Logo -->
      <div class="flex items-center gap-3 px-5 py-5 border-b border-gray-700">
        <div class="h-9 w-9 rounded-lg bg-primary flex items-center justify-center font-bold text-sm">AKM</div>
        <div>
          <p class="text-sm font-semibold">{{ t('nav.appName') }}</p>
          <p class="text-xs text-gray-400">{{ t('nav.appSubtitle') }}</p>
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
      <div class="px-4 py-4 border-t border-gray-700 space-y-3">
        <LanguageSwitcher />
        <div class="flex items-center gap-3">
          <div class="h-8 w-8 rounded-full bg-primary flex items-center justify-center text-xs font-bold">A</div>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium truncate">{{ t('nav.administrator') }}</p>
          </div>
          <button @click="logout" class="text-gray-400 hover:text-white text-xs">{{ t('nav.logout') }}</button>
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
import { useI18n } from 'vue-i18n'
import LanguageSwitcher from '@/Components/UI/LanguageSwitcher.vue'

const route = useRoute()
const { t } = useI18n()

const navItems = computed(() => [
  { to: '/', label: t('nav.dashboard'), icon: 'span' },
  { to: '/patients', label: t('nav.patients'), icon: 'span' },
  { to: '/calendar', label: t('nav.calendar'), icon: 'span' },
  { to: '/treatments', label: t('nav.treatments'), icon: 'span' },
  { to: '/finance', label: t('nav.finance'), icon: 'span' },
])

const titleMap = computed(() => ({
  dashboard: t('nav.dashboard'),
  patients: t('nav.patients'),
  'patient-detail': t('nav.patientDetail'),
  calendar: t('nav.calendar'),
  appointments: t('nav.appointments'),
  treatments: t('nav.treatments'),
  finance: t('nav.finance'),
}))

const currentPageTitle = computed(() => titleMap.value[route.name] || t('nav.appName'))

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
