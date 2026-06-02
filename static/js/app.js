// AKM SOFT CLINIC — Alpine.js global components

// ── Toast notifications ────────────────────────────────────────────────────
function toastSystem() {
  return {
    toasts: [],
    add(msg, type = 'success') {
      const id = Date.now();
      this.toasts.push({ id, msg, type });
      setTimeout(() => this.remove(id), 4000);
    },
    remove(id) { this.toasts = this.toasts.filter(t => t.id !== id); },
    success(msg) { this.add(msg, 'success'); },
    error(msg)   { this.add(msg, 'error'); },
    info(msg)    { this.add(msg, 'info'); },
  };
}
window._toast = null;
document.addEventListener('alpine:initialized', () => {
  window._toast = Alpine.$data(document.querySelector('[x-data*="toastSystem"]'));
});
function toast(msg, type = 'success') {
  const el = document.querySelector('[x-data*="toastSystem"]');
  if (el) Alpine.$data(el).add(msg, type);
}

// ── CSRF helper ────────────────────────────────────────────────────────────
function getCsrf() {
  return document.cookie.split(';').map(c => c.trim())
    .find(c => c.startsWith('csrftoken='))?.split('=')[1] || '';
}

// ── AJAX fetch helper ──────────────────────────────────────────────────────
async function api(url, method = 'GET', data = null) {
  const opts = {
    method,
    headers: { 'X-CSRFToken': getCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
  };
  if (data instanceof FormData) {
    opts.body = data;
  } else if (data) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(data);
  }
  const res = await fetch(url, opts);
  return res;
}

// ── Modal helper ───────────────────────────────────────────────────────────
function modal(id) {
  document.getElementById(id)?.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}
function closeModal(id) {
  document.getElementById(id)?.classList.add('hidden');
  document.body.style.overflow = '';
}

// ── Shell: sidebar collapse + theme ────────────────────────────────────────
function shell() {
  return {
    collapsed: localStorage.getItem('sidebar_collapsed') === 'true',
    dark: localStorage.getItem('theme') === 'dark',
    init() {
      this.$watch('collapsed', v => localStorage.setItem('sidebar_collapsed', v));
    },
    setTheme(isDark) {
      this.dark = isDark;
      localStorage.setItem('theme', isDark ? 'dark' : 'light');
      document.documentElement.classList.toggle('dark', isDark);
      window.dispatchEvent(new CustomEvent('themechange', { detail: { dark: isDark } }));
    },
  };
}
function sidebarApp() { return shell(); }  // back-compat

// ── Personal sidebar hiding (per user, localStorage) ────────────────────────
function applyHiddenModules() {
  let hidden = [];
  try { hidden = JSON.parse(localStorage.getItem('hidden_modules') || '[]'); } catch(e) {}
  document.querySelectorAll('.nav-item[data-mod]').forEach(el => {
    el.style.display = hidden.includes(el.dataset.mod) ? 'none' : '';
  });
}
document.addEventListener('DOMContentLoaded', applyHiddenModules);
window.applyHiddenModules = applyHiddenModules;

// ── Searchable selects (Tom Select) ─────────────────────────────────────────
function initTomSelects(root) {
  if (typeof TomSelect === 'undefined') return;
  const scope = root || document;
  // multi-select searchable (e.g. appointment services)
  scope.querySelectorAll('select.searchable-multi').forEach(sel => {
    if (sel.tomselect || sel.classList.contains('no-tom')) return;
    new TomSelect(sel, { plugins: ['remove_button'], placeholder: 'Выберите...', maxOptions: 1000 });
  });
  scope.querySelectorAll('select.searchable, select[data-search]').forEach(sel => {
    if (sel.tomselect) return;                         // already initialized
    if (sel.classList.contains('no-tom')) return;       // explicit opt-out
    if (sel.multiple) return;                            // skip multi for now
    if (sel.hasAttribute('x-model')) return;            // skip Alpine-bound
    new TomSelect(sel, {
      create: false,
      allowEmptyOption: true,
      maxOptions: 1000,
      placeholder: sel.options[0] ? sel.options[0].text : 'Выберите...',
      onChange() { sel.dispatchEvent(new Event('change', { bubbles: true })); },
    });
  });
}
window.initTomSelects = initTomSelects;
document.addEventListener('DOMContentLoaded', () => initTomSelects());

// ── Chart theme helper ──────────────────────────────────────────────────────
function chartColors() {
  const dark = document.documentElement.classList.contains('dark');
  return {
    text: dark ? '#A5A3C0' : '#6B7280',
    grid: dark ? 'rgba(255,255,255,.06)' : 'rgba(0,0,0,.05)',
    dark,
  };
}

// ── Patient form (modal) ───────────────────────────────────────────────────
function patientForm() {
  return {
    loading: false,
    async submit(e) {
      e.preventDefault();
      this.loading = true;
      try {
        const fd = new FormData(e.target);
        const res = await api(e.target.action, 'POST', fd);
        if (res.ok || res.redirected) {
          toast('Пациент добавлен');
          closeModal('patientModal');
          setTimeout(() => location.reload(), 600);
        } else {
          const text = await res.text();
          toast('Ошибка при сохранении', 'error');
        }
      } catch(err) {
        toast('Ошибка сети', 'error');
      } finally {
        this.loading = false;
      }
    }
  };
}

// ── Treatment form ─────────────────────────────────────────────────────────
function treatmentForm() {
  return {
    cures: [{ service: '', tooth: '', qty: 1, price: '' }],
    total: 0,
    addCure() { this.cures.push({ service: '', tooth: '', qty: 1, price: '' }); },
    removeCure(i) { if (this.cures.length > 1) this.cures.splice(i, 1); this.calcTotal(); },
    calcTotal() {
      this.total = this.cures.reduce((s, c) => s + (parseFloat(c.price) || 0) * (parseInt(c.qty) || 1), 0);
    }
  };
}

// ── Appointment modal ──────────────────────────────────────────────────────
function appointmentForm() {
  return {
    loading: false,
    async submit(e) {
      e.preventDefault();
      this.loading = true;
      try {
        const fd = new FormData(e.target);
        const res = await api(e.target.action, 'POST', fd);
        if (res.ok || res.redirected) {
          toast('Запись добавлена');
          closeModal('appointmentModal');
          setTimeout(() => location.reload(), 600);
        } else {
          toast('Ошибка при сохранении', 'error');
        }
      } finally { this.loading = false; }
    }
  };
}

// ── Payment modal ──────────────────────────────────────────────────────────
function paymentForm() {
  return {
    loading: false,
    async submit(e) {
      e.preventDefault();
      this.loading = true;
      try {
        const fd = new FormData(e.target);
        const res = await api(e.target.action, 'POST', fd);
        if (res.ok || res.redirected) {
          toast('Платёж записан');
          closeModal('paymentModal');
          setTimeout(() => location.reload(), 600);
        } else {
          toast('Ошибка', 'error');
        }
      } finally { this.loading = false; }
    }
  };
}

// ── Search with debounce ───────────────────────────────────────────────────
function searchInput(url) {
  return {
    query: new URLSearchParams(location.search).get('q') || '',
    timer: null,
    run() {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => {
        const u = new URL(url, location.origin);
        if (this.query) u.searchParams.set('q', this.query);
        else u.searchParams.delete('q');
        location.href = u.toString();
      }, 450);
    }
  };
}
