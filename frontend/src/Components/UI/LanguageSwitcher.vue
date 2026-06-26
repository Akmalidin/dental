<template>
  <div class="flex items-center gap-1 text-xs">
    <button v-for="opt in options" :key="opt.code" @click="select(opt.code)"
            class="px-2 py-1 rounded-md transition-colors"
            :class="locale === opt.code ? 'bg-primary text-white' : 'text-gray-400 hover:text-white'">
      {{ opt.label }}
    </button>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { setLocale } from '@/i18n'

const { locale } = useI18n()

const options = [
  { code: 'ru', label: 'РУС' },
  { code: 'ky', label: 'КЫР' },
]

function select(code) {
  setLocale(code)
}
</script>
