// Требует playwright-core (npm install playwright-core) и headless Chromium.
// CHROMIUM_PATH — путь к бинарнику (напр. Playwright browser cache); если не
// задан, используется системный chromium из PATH.
const { chromium } = require("playwright-core");
const path = require("path");

const OUT_DIR = path.join(__dirname, "screens-raw");
const BASE = process.env.DEMO_BASE_URL || "http://127.0.0.1:8000";

const PAGES = [
  { name: "dashboard", url: "/new/", wait: 1200 },
  { name: "funnel", url: "/new/funnel/", wait: 900 },
  { name: "schedule", url: "/new/schedule/", wait: 900 },
  { name: "patients", url: "/new/patients/", wait: 900 },
  { name: "patientcard", url: "/new/patients/1/", wait: 900 },
  { name: "visits", url: "/new/visits/", wait: 900 },
  { name: "treatplans", url: "/new/treatplans/", wait: 900 },
  { name: "messages", url: "/new/messages/", wait: 900 },
  { name: "cashdesk", url: "/new/cashdesk/", wait: 900 },
  { name: "finance", url: "/new/finance/", wait: 900 },
  { name: "warehouse", url: "/new/warehouse/", wait: 900 },
  { name: "lab", url: "/new/lab/", wait: 900 },
  { name: "staff", url: "/new/staff/", wait: 900 },
  { name: "services", url: "/new/services/", wait: 900 },
  { name: "tasks", url: "/new/tasks/", wait: 900 },
  { name: "reports", url: "/new/reports/", wait: 1200 },
  { name: "audit", url: "/new/audit/", wait: 900 },
  { name: "settings", url: "/new/settings/", wait: 900 },
];

(async () => {
  const fs = require("fs");
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--headless=new"],
  });
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });
  const page = await context.newPage();

  // логин
  await page.goto(`${BASE}/login/`, { waitUntil: "networkidle" });
  await page.fill('input[name="login"]', "demo_director");
  await page.fill('input[name="password"]', "demo12345");
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle" }),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
  console.log("logged in, url =", page.url());

  for (const p of PAGES) {
    await page.goto(`${BASE}${p.url}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(p.wait);
    const outPath = path.join(OUT_DIR, `${p.name}.png`);
    await page.screenshot({ path: outPath });
    console.log("saved", outPath);
  }

  await browser.close();
})().catch((e) => {
  console.error("SCRIPT_ERROR", e);
  process.exit(1);
});
