# CRM Mobile-Responsive Pass — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, with review after each task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the staff CRM (`templates/` — NOT `templates/public/`, already fixed separately) comfortable to use at any screen width, from phone to desktop. Not a redesign — targeted fixes to specific components that currently have zero or incomplete responsive handling.

**Scope note:** `templates/public/*` (patient booking widget, marketing pages) is out of scope — already fixed in a prior pass. This plan covers only the authenticated staff app.

## Audit summary (grounds this plan — see full detail in conversation history / re-run the same audit if this doc goes stale)

- The CRM shell (`templates/base.html` + `static/css/app.css`) already has working responsive infrastructure: sidebar collapses to a drawer below **900px** (the one real breakpoint in the CSS), modals already cap at `96vw`/`90vh` with internal scroll at any size. **Do not touch this — it works.**
- Everything below 900px inherits *some* help from the 900px rule (font shrink, card padding, modal width) but several specific components have **zero** responsive handling of their own:
  1. Dashboard stat-tile row (`.stat` class) — fixed padding/icon/font size, causes visible misalignment between tiles at 2-column phone width (the exact bug in the user's screenshot).
  2. ~48 templates use raw `<table>` with no `overflow-x` wrapper — worst overflow risk on phones, since it can force page-level horizontal scroll against the fixed sidebar.
  3. A handful of pages/modals use fixed multi-column grids (`grid-cols-3`, `grid-cols-4`, or inline `grid-template-columns`) with no responsive Tailwind prefix.
  4. `templates/treatments/visit.html` — a 7-column editable table with per-cell fixed-width inputs; the worst single offender, needs its own treatment rather than a generic table wrapper.
  5. `templates/appointments/calendar.html` (FullCalendar) has no mobile view-switching; `day_grid.html` already has an intentional horizontal-scroll pattern and is lower priority.

## Standards for this pass

- Reuse the existing **900px** breakpoint for any new CRM-wide CSS rule (matches the sidebar/modal system already in `app.css`). Use Tailwind's stock `md:`/`lg:` prefixes (768/1024px) for per-template grid-column fixes, matching how most already-responsive grids in the CRM are written — don't invent new pixel breakpoints.
- Every fix in this plan is additive (new CSS rule, new wrapper div, added Tailwind prefix) — no restructuring of working markup, no visual changes above 900px unless a bug is present there too.
- Manual verification only (screenshot at ~375px, ~768px, ~1280px widths via browser devtools) — this is CSS/markup, not covered by the Django test suite.

---

## Task 1: Table overflow wrapper (global, ~48 templates)

**Files:** every template listed in the audit under "Raw `<table>` usage" (dashboard, appointments, patients, treatments, finance, users, technicians, warehouse, settings, services, medicines, notifications, reports, central — full list in audit).

Wrap each `<table>` (or its existing `.card`/container if that's cleaner per-template) in `<div style="overflow-x:auto">...</div>` so wide tables scroll horizontally within their own panel instead of pushing the page/sidebar layout. Mechanical, low-risk, one wrapper per table. Do NOT touch `treatments/visit.html`'s table here — it's Task 3.

Exclude print-only templates (`card043_print.html`, `schedule_print.html`) — not viewed on-device.

- [ ] Add `overflow-x:auto` wrapper around every non-print `<table>` in the templates listed above.
- [ ] Manual check: open Patients list, Finance payments, Treatments list, Warehouse dashboard at 375px width — tables scroll horizontally within their card, page/sidebar stay fixed.

## Task 2: Dashboard stat-tile responsive fix

**Files:** `static/css/app.css` (`.stat`, `.stat-icon`, `.stat-value` — lines ~188-195), consumed by `templates/dashboard/admin.html`, `dashboard/doctor.html`, `dashboard/superadmin.html`.

Add a rule inside (or near) the existing 900px media query: shrink `.stat` padding, `.stat-icon` size, and `.stat-value` font-size at ≤900px, and fix vertical alignment so tiles with 1-line vs 2-line labels stay visually consistent (e.g. `align-items:flex-start` instead of `center`, or a min-height on the label). Consider a single-column fallback below ~380px if 2-column still feels cramped after the shrink — decide after checking a real device width in Task 2's manual check.

- [ ] Add responsive `.stat`/`.stat-icon`/`.stat-value` rules at ≤900px.
- [ ] Manual check at 375px: all 4 tiles same height, no shifted icon/number blocks.

## Task 3: Fixed-grid offenders — add responsive Tailwind prefixes

**Files (5):**
- `templates/warehouse/transfer_form.html:12` — `grid-cols-3` → `grid-cols-1 md:grid-cols-3`
- `templates/patients/form.html:33,93,122` — same fix, 3 spots
- `templates/treatments/detail.html:52` — `grid-cols-4` → `grid-cols-2 md:grid-cols-4`
- `templates/patients/detail.html:849` (service-picker modal grid) — `grid-cols-3` → `grid-cols-1 sm:grid-cols-2` (modal itself caps at 96vw, so use a tighter breakpoint than page-level grids)
- `templates/settings/documents.html:45` — same pattern, lower priority

- [ ] Apply responsive prefixes to all 5 files above.
- [ ] Manual check: Patients → new patient form, and Patients → open a patient → service-picker modal, at 375px.

## Task 4: `treatments/visit.html` editable table (worst offender, needs its own treatment)

**File:** `templates/treatments/visit.html:298-329` — 7-column table, per-cell fixed-width inputs (100/150/160/110/140px).

This one won't work as a simple overflow wrapper alone (7 columns × ~140px avg ≈ 980px minimum, viable to scroll but cramped to actually edit on a phone). Options to evaluate during implementation (pick based on what reads best once wrapped and tested, don't over-engineer):
- (a) Simplest: same `overflow-x:auto` wrapper as Task 1, accept horizontal scroll for this one editing-heavy table (matches `day_grid.html`'s existing precedent of "intentional horizontal scroll" for complex grids).
- (b) If (a) feels unusable for real data entry on phone: collapse to a stacked card-per-row layout below 900px (each row's 7 fields become a small vertical form instead of a table row) — more work, only do this if (a) genuinely fails the manual check.

- [ ] Wrap the table per option (a) first.
- [ ] Manual check on a real treatment's visit page at 375px: can you still read and edit each field without cross-scrolling constantly? If clearly unusable, implement (b) instead.

## Task 5: Calendar mobile handling (`appointments/calendar.html`)

**File:** `templates/appointments/calendar.html` — FullCalendar 6.1.10, no mobile view-switching, fixed-width `#doctorFilter` select (line 57), no `.fc` responsive CSS.

Lowest priority / highest effort-to-risk ratio in this plan — FullCalendar's default `timeGridWeek` at phone width is unusable regardless of CSS tweaks. Recommend:
- [ ] Add a `windowResize`/initial-view check: force `timeGridDay` (or FullCalendar's built-in `listWeek`) below 900px instead of `timeGridWeek`.
- [ ] Let the toolbar wrap naturally (`flex-wrap` already present) — just fix `#doctorFilter`'s fixed `w-48` to `w-full max-w-[12rem]` so it doesn't force overflow in a wrapped toolbar row.
- [ ] Manual check at 375px: calendar loads a single-day view by default, is usable, toolbar wraps without clipping.
- Note: `day_grid.html` already has a working horizontal-scroll pattern (fixed 200px doctor columns in a `max-height:72vh;overflow:auto` container) — leave it as-is, it's not broken, just not perfectly optimized. Not in scope for this pass unless Task 5's calendar work reveals a shared fix.

## Task 6: Small fixed-width leftovers (batch, low risk)

**Files:** `technicians/kanban.html:14` (260px columns — confirm/add horizontal scroll container around the column row if missing), `appointments/calendar.html:79` context-menu (`min-width:210px`, no edge-clamping — add a simple `Math.min(x, window.innerWidth - 220)` clamp in the positioning JS), and the minor fixed-width inputs noted in the audit (`warehouse/entry_form.html`, `treatments/form.html` table headers, `services/form.html`, `users/branch_form.html`, `users/site_doctors.html`) — spot-check each, fix only if it visibly breaks at 375px (several are small enough to not matter).

- [ ] Kanban board: confirm/add horizontal scroll container.
- [ ] Calendar context menu: clamp position to viewport.
- [ ] Spot-check remaining minor fixed-width inputs at 375px, fix only genuine breakage.

---

## Self-Review Notes

- **Order rationale:** Task 1 (tables) and Task 2 (dashboard) are the highest-visibility, lowest-risk wins — do these first. Task 3/4 are contained to specific known-bad pages. Task 5 (calendar) is the highest-effort, most behaviorally-risky item (changes FullCalendar's default view) — deliberately last so earlier tasks ship even if Task 5 needs more back-and-forth.
- **Out of scope, explicitly:** `templates/public/*` (already handled separately), any visual redesign above the 900px breakpoint, `frontend/` Vue app (not used for this surface).
- **Risk:** all changes are additive CSS/Tailwind-prefix/wrapper-div changes to server-rendered templates with no JS logic changes except Task 5 (view-switch) and Task 6 (context-menu clamp) — low risk of breaking existing desktop behavior, verify each task's manual check before moving to the next.
