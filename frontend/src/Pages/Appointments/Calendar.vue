<template>
  <div class="card p-4">
    <div class="flex items-center justify-between mb-4">
      <h2 class="font-semibold text-gray-800">Расписание</h2>
      <button class="bg-primary text-white text-sm px-4 py-2 rounded-lg hover:bg-primary-dark">
        + Новая запись
      </button>
    </div>
    <FullCalendar :options="calendarOptions" style="height: calc(100vh - 220px)" />
  </div>
</template>

<script setup>
import FullCalendar from '@fullcalendar/vue3'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import ruLocale from '@fullcalendar/core/locales/ru'
import { appointmentsApi } from '@/api'

const calendarOptions = {
  plugins: [dayGridPlugin, timeGridPlugin, interactionPlugin],
  initialView: 'timeGridWeek',
  locale: ruLocale,
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
    if (confirm('Редактировать эту запись?')) {
      window.location.href = `/appointments/${info.event.id}/edit/`
    }
  },
}
</script>
