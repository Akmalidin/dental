import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { FontFaces } from "./Fonts";
import { theme } from "./theme";
import { TourShell } from "./TourShell";
import { PageFrame } from "./PageFrame";
import { CursorPoint } from "./AnimatedCursor";
import { TourIntro } from "./scenes/TourIntro";
import { TourOutro } from "./scenes/TourOutro";

type TourPage = {
  file: string;
  group: string;
  title: string;
  caption: string;
  panXPct?: number;
  cursor: CursorPoint[]; // 1–2 точки, курсор «доезжает и кликает» по каждой по очереди
};

// Полный обзор системы «от А до Я» — реальные страницы /new/* (см.
// scratchpad/screenshot.js + docs/marketing/video/README.md), без озвучки:
// подписи и подписи-чипы читаются за время показа кадра. cursor — координаты
// в % от области скриншота (0–100), подобраны по реальным кадрам интерфейса
// (кнопка/карточка/строка списка), чтобы клики выглядели осмысленно, а не
// произвольно посреди пустого места.
const PAGES: TourPage[] = [
  { file: "dashboard.jpg", group: "Продажи", title: "Дашборд", caption: "Все ключевые показатели клиники — с самого входа", panXPct: -2, cursor: [{ x: 30, y: 32 }, { x: 91, y: 16 }] },
  { file: "funnel.jpg", group: "Продажи", title: "Заявки · CRM", caption: "Каждое обращение — от первого контакта до записи на приём", panXPct: 2, cursor: [{ x: 26, y: 33 }, { x: 90, y: 17 }] },
  { file: "schedule.jpg", group: "Клиника", title: "Расписание врачей", caption: "Календарь приёмов по кабинетам — без двойных записей", panXPct: -3, cursor: [{ x: 33, y: 30 }, { x: 95, y: 4 }] },
  { file: "patients.jpg", group: "Клиника", title: "Пациенты", caption: "Полная база: поиск, история, документы по каждому", panXPct: 2, cursor: [{ x: 24, y: 30 }, { x: 91, y: 17 }] },
  { file: "patientcard.jpg", group: "Клиника", title: "Карта пациента", caption: "История лечения, баланс и документы — в одной карточке", panXPct: -2, cursor: [{ x: 23, y: 17 }, { x: 94, y: 10 }] },
  { file: "visits.jpg", group: "Клиника", title: "Визиты", caption: "Текущие и прошлые приёмы — статус каждого визита", panXPct: 2, cursor: [{ x: 27, y: 31 }, { x: 90, y: 17 }] },
  { file: "treatplans.jpg", group: "Клиника", title: "Планы лечения", caption: "Этапы и услуги плана, согласованные с пациентом", panXPct: -2, cursor: [{ x: 25, y: 29 }, { x: 90, y: 17 }] },
  { file: "messages.jpg", group: "Клиника", title: "Мессенджеры", caption: "WhatsApp и Telegram — переписка с пациентами в одном окне", panXPct: 3, cursor: [{ x: 22, y: 28 }, { x: 60, y: 33 }] },
  { file: "cashdesk.jpg", group: "Деньги", title: "Касса", caption: "Приём оплат и кассовые смены — без бумажной сверки", panXPct: -2, cursor: [{ x: 26, y: 32 }, { x: 91, y: 17 }] },
  { file: "finance.jpg", group: "Деньги", title: "Финансы", caption: "Доходы и расходы клиники — под контролем в реальном времени", panXPct: 2, cursor: [{ x: 28, y: 30 }, { x: 90, y: 17 }] },
  { file: "warehouse.jpg", group: "Клиника", title: "Склад", caption: "Остатки материалов и минимальные запасы — всегда на виду", panXPct: -2, cursor: [{ x: 25, y: 31 }, { x: 91, y: 17 }] },
  { file: "lab.jpg", group: "Клиника", title: "Лаборатория", caption: "Заказы техникам и статус изготовления работ", panXPct: 2, cursor: [{ x: 27, y: 30 }, { x: 90, y: 17 }] },
  { file: "staff.jpg", group: "Управление", title: "Персонал", caption: "Роли, права доступа и филиалы сотрудников", panXPct: -2, cursor: [{ x: 26, y: 31 }, { x: 90, y: 17 }] },
  { file: "services.jpg", group: "Клиника", title: "Услуги", caption: "Прайс-лист клиники — категории и цены", panXPct: 2, cursor: [{ x: 24, y: 30 }, { x: 90, y: 17 }] },
  { file: "tasks.jpg", group: "Управление", title: "Задачи", caption: "Внутренние задачи клиники — с приоритетом и исполнителем", panXPct: -2, cursor: [{ x: 25, y: 30 }, { x: 90, y: 17 }] },
  { file: "reports.jpg", group: "Управление", title: "Отчёты", caption: "Выручка, загрузка врачей и должники — без сведения таблиц", panXPct: 2, cursor: [{ x: 32, y: 35 }, { x: 68, y: 30 }] },
  { file: "audit.jpg", group: "Управление", title: "Журнал аудита", caption: "Кто и когда менял карточку пациента — видно всегда", panXPct: -2, cursor: [{ x: 92, y: 4 }, { x: 20, y: 19 }] },
  { file: "settings.jpg", group: "Управление", title: "Настройки", caption: "Все параметры клиники — в одном разделе", panXPct: 2, cursor: [{ x: 27, y: 30 }, { x: 90, y: 17 }] },
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
            <PageFrame file={p.file} duration={PAGE_FRAMES} width={1280} zoomFrom={1.09} panXPct={p.panXPct ?? 0} cursorPoints={p.cursor} />
          </TourShell>
        </Sequence>
      ))}

      <Sequence from={outroStart} durationInFrames={OUTRO_FRAMES} name="outro">
        <TourOutro />
      </Sequence>
    </AbsoluteFill>
  );
};
