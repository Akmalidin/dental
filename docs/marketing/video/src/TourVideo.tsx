import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { FontFaces } from "./Fonts";
import { theme } from "./theme";
import { TourShell } from "./TourShell";
import { PageFrame } from "./PageFrame";
import { TourIntro } from "./scenes/TourIntro";
import { TourOutro } from "./scenes/TourOutro";

type TourPage = {
  file: string;
  group: string;
  title: string;
  caption: string;
  panXPct?: number;
};

// Полный обзор системы «от А до Я» — реальные страницы /new/* (см.
// scratchpad/screenshot.js + docs/marketing/video/README.md), без озвучки:
// подписи и подписи-чипы читаются за время показа кадра.
const PAGES: TourPage[] = [
  { file: "dashboard.jpg", group: "Продажи", title: "Дашборд", caption: "Все ключевые показатели клиники — с самого входа", panXPct: -2 },
  { file: "funnel.jpg", group: "Продажи", title: "Заявки · CRM", caption: "Каждое обращение — от первого контакта до записи на приём", panXPct: 2 },
  { file: "schedule.jpg", group: "Клиника", title: "Расписание врачей", caption: "Календарь приёмов по кабинетам — без двойных записей", panXPct: -3 },
  { file: "patients.jpg", group: "Клиника", title: "Пациенты", caption: "Полная база: поиск, история, документы по каждому", panXPct: 2 },
  { file: "patientcard.jpg", group: "Клиника", title: "Карта пациента", caption: "История лечения, баланс и документы — в одной карточке", panXPct: -2 },
  { file: "visits.jpg", group: "Клиника", title: "Визиты", caption: "Текущие и прошлые приёмы — статус каждого визита", panXPct: 2 },
  { file: "treatplans.jpg", group: "Клиника", title: "Планы лечения", caption: "Этапы и услуги плана, согласованные с пациентом", panXPct: -2 },
  { file: "messages.jpg", group: "Клиника", title: "Мессенджеры", caption: "WhatsApp и Telegram — переписка с пациентами в одном окне", panXPct: 3 },
  { file: "cashdesk.jpg", group: "Деньги", title: "Касса", caption: "Приём оплат и кассовые смены — без бумажной сверки", panXPct: -2 },
  { file: "finance.jpg", group: "Деньги", title: "Финансы", caption: "Доходы и расходы клиники — под контролем в реальном времени", panXPct: 2 },
  { file: "warehouse.jpg", group: "Клиника", title: "Склад", caption: "Остатки материалов и минимальные запасы — всегда на виду", panXPct: -2 },
  { file: "lab.jpg", group: "Клиника", title: "Лаборатория", caption: "Заказы техникам и статус изготовления работ", panXPct: 2 },
  { file: "staff.jpg", group: "Управление", title: "Персонал", caption: "Роли, права доступа и филиалы сотрудников", panXPct: -2 },
  { file: "services.jpg", group: "Клиника", title: "Услуги", caption: "Прайс-лист клиники — категории и цены", panXPct: 2 },
  { file: "tasks.jpg", group: "Управление", title: "Задачи", caption: "Внутренние задачи клиники — с приоритетом и исполнителем", panXPct: -2 },
  { file: "reports.jpg", group: "Управление", title: "Отчёты", caption: "Выручка, загрузка врачей и должники — без сведения таблиц", panXPct: 2 },
  { file: "audit.jpg", group: "Управление", title: "Журнал аудита", caption: "Кто и когда менял карточку пациента — видно всегда", panXPct: -2 },
  { file: "settings.jpg", group: "Управление", title: "Настройки", caption: "Все параметры клиники — в одном разделе", panXPct: 2 },
];

const INTRO_FRAMES = 90;
const PAGE_FRAMES = 126;
const OUTRO_FRAMES = 150;

export const TOUR_TOTAL_FRAMES = INTRO_FRAMES + PAGES.length * PAGE_FRAMES + OUTRO_FRAMES;

export const StomTour: React.FC = () => {
  let cursor = 0;
  const introStart = cursor;
  cursor += INTRO_FRAMES;
  const pageStarts = PAGES.map(() => {
    const s = cursor;
    cursor += PAGE_FRAMES;
    return s;
  });
  const outroStart = cursor;

  return (
    <AbsoluteFill style={{ background: theme.bg }}>
      <FontFaces />
      <Audio src={staticFile("audio/tour-music.wav")} volume={0.45} />

      <Sequence from={introStart} durationInFrames={INTRO_FRAMES} name="intro">
        <TourIntro />
      </Sequence>

      {PAGES.map((p, i) => (
        <Sequence key={p.file} from={pageStarts[i]} durationInFrames={PAGE_FRAMES} name={`page-${p.file}`}>
          <TourShell index={i + 1} total={PAGES.length} group={p.group} title={p.title} caption={p.caption}>
            <PageFrame file={p.file} duration={PAGE_FRAMES} width={1280} zoomFrom={1.09} panXPct={p.panXPct ?? 0} />
          </TourShell>
        </Sequence>
      ))}

      <Sequence from={outroStart} durationInFrames={OUTRO_FRAMES} name="outro">
        <TourOutro />
      </Sequence>
    </AbsoluteFill>
  );
};
