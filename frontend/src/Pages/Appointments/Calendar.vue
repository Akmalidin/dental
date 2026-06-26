<template>
  <div class="card p-4">
    <div class="flex items-center justify-between mb-4">
      <h2 class="font-semibold text-gray-800">{{ t('appointments.calendarTitle') }}</h2>
      <button class="bg-primary text-white text-sm px-4 py-2 rounded-lg hover:bg-primary-dark">
        {{ t('appointments.newAppointment') }}
      </button>
    </div>
    <FullCalendar :options="calendarOptions" style="height: calc(100vh - 220px)" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import FullCalendar from '@fullcalendar/vue3'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import ruLocale from '@fullcalendar/core/locales/ru'
import { appointmentsApi } from '@/api'

const { t, locale } = useI18n()

const kyLocale = {
  code: 'ky',
  week: { dow: 1, doy: 7 },
  buttonText: { prev: 'Мурунку', next: 'Кийинки', today: 'Бүгүн', month: 'Ай', week: 'Жума', day: 'Күн', list: 'Тизме' },
  weekText: 'Жм',
  allDayText: 'Бүт күн',
  moreLinkText: 'дагы',
  noEventsText: 'Көрсөтүлгөн окуялар жок',
}

const calendarOptions = computed(() => ({
  plugins: [dayGridPlugin, timeGridPlugin, interactionPlugin],
  initialView: 'timeGridWeek',
  locale: locale.value === 'ky' ? kyLocale : ruLocale,
  headerToolbar: {
    left: 'prev,next today',
    center: 'title',
    right: 'dayGridMonth,timeGridWeek,timeGridDay',
  },
  slotMinTime: '08:00:00',
  slotMaxTime: '20:00:00',
  allDaySlot: false,
  nowIndicator: true,
  events: async (info, successCb, failureCb) => {
    try {
      const { data } = await appointmentsApi.calendar({
        start: info.startStr,
        end: info.endStr,
      })
      successCb(data)
    } catch {
      failureCb()
    }
  },
  eventClick: (info) => {
    if (confirm(t('appointments.confirmEdit'))) {
      window.location.href = `/appointments/${info.event.id}/edit/`
    }
  },
}))
</script>
