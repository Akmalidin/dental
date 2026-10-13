/* Рассрочка: окно оформления (график строится сам, суммы можно поправить)
   и блок «Рассрочка» в карточке пациента. Подключается на карточке пациента
   и на странице «Деньги → Рассрочки». */
(function(){
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const cur = () => (typeof CUR_SYM !== 'undefined' && CUR_SYM) || 'сом';
  const money = n => Math.round(n).toLocaleString('ru-RU') + ' ' + cur();
  const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  const ru = s => s.split('-').reverse().join('.');
  function addMonths(isoDate, n){
    const [y, m, d] = isoDate.split('-').map(Number);
    const t = new Date(y, m - 1 + n, 1);
    const last = new Date(t.getFullYear(), t.getMonth() + 1, 0).getDate();
    return iso(new Date(t.getFullYear(), t.getMonth(), Math.min(d, last)));
  }

  function ensureModal(){
    if(document.getElementById('m-inst')) return;
    const div = document.createElement('div');
    div.innerHTML = `
    <div class="modal-backdrop" id="m-inst">
      <div class="modal" style="max-width:560px;">
        <div class="modal-head"><h3 id="instTitle">Оформить рассрочку</h3><button class="modal-close" type="button" onclick="closeModal('m-inst')">✕</button></div>
        <div class="modal-body">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:0 12px;">
            <div class="form-group"><label>Сумма рассрочки</label><input type="number" id="instTotal" min="1" step="1" oninput="instPreview()"></div>
            <div class="form-group"><label>Первый взнос сегодня</label><input type="number" id="instDown" min="0" step="1" value="0" oninput="instPreview()"></div>
            <div class="form-group"><label>Срок, месяцев</label><input type="number" id="instMonths" min="1" max="60" step="1" value="3" oninput="instPreview()"></div>
            <div class="form-group"><label>Первый платёж</label><input type="date" id="instFirst" onchange="instPreview()"></div>
          </div>
          <div class="form-group"><label>Комментарий</label><input type="text" id="instNote" maxlength="300" autocomplete="off" placeholder="Например: имплантация, договор №…"></div>
          <div style="font-size:12px;color:var(--ink-soft);margin:4px 0 6px;">График (суммы и даты можно поправить):</div>
          <div style="max-height:260px;overflow:auto;"><table><thead><tr><th>№</th><th>Дата</th><th class="n">Сумма</th></tr></thead><tbody id="instRows"></tbody></table></div>
          <div id="instSumCheck" style="font-size:12.5px;margin-top:8px;"></div>
          <div style="font-size:12px;color:var(--ink-soft);margin-top:6px;">Оплаты принимаются как обычно в кассе — всё, что пациент заплатит после оформления, само засчитается в график по порядку дат. Пациенту придёт напоминание за день до платежа.</div>
        </div>
        <div class="modal-foot"><button class="btn btn-ghost" type="button" onclick="closeModal('m-inst')">Отмена</button><button class="btn btn-cobalt" type="button" id="instSaveBtn" onclick="instSave()">Оформить</button></div>
      </div>
    </div>`;
    document.body.appendChild(div.firstElementChild);
  }

  let instPatientId = null, instOnDone = null;
  // «Сегодня» — по времени клиники (приходит с сервера), а не по часам
  // компьютера: около полуночи они расходятся, и взнос «сегодня» сразу
  // оказывался бы просроченным.
  let instToday = null;
  const todayIso = () => instToday || iso(new Date());
  window.instOpenCreate = function(patientId, patientName, debt, onDone, today){
    ensureModal();
    instPatientId = patientId; instOnDone = onDone || null;
    if(today) instToday = today;
    document.getElementById('instTitle').textContent = 'Рассрочка: ' + (patientName || '');
    document.getElementById('instTotal').value = debt > 0 ? Math.round(debt) : '';
    document.getElementById('instDown').value = 0;
    document.getElementById('instMonths').value = 3;
    document.getElementById('instNote').value = '';
    document.getElementById('instFirst').value = addMonths(todayIso(), 1);
    instPreview();
    openModal('m-inst');
  };
  window.instPreview = function(){
    const total = Math.max(0, Math.round(+document.getElementById('instTotal').value || 0));
    const down = Math.max(0, Math.round(+document.getElementById('instDown').value || 0));
    const months = Math.max(1, Math.min(60, Math.round(+document.getElementById('instMonths').value || 1)));
    const first = document.getElementById('instFirst').value || addMonths(todayIso(), 1);
    const rows = [];
    if(down > 0) rows.push({due: todayIso(), amount: Math.min(down, total)});
    const rest = total - Math.min(down, total);
    if(rest > 0){
      const part = Math.round(rest / months);
      for(let i = 0; i < months; i++) rows.push({due: addMonths(first, i), amount: i < months - 1 ? part : rest - part * (months - 1)});
    }
    document.getElementById('instRows').innerHTML = rows.map((r, i) => `<tr>
      <td>${i + 1}${i === 0 && down > 0 ? ' <span style="font-size:11px;color:var(--ink-soft);">взнос</span>' : ''}</td>
      <td><input type="date" value="${r.due}" data-k="due" style="width:150px;" onchange="instSumCheck()"></td>
      <td class="n"><input type="number" min="1" step="1" value="${r.amount}" data-k="amount" style="width:120px;text-align:right;" oninput="instSumCheck()"></td></tr>`).join('');
    instSumCheck();
  };
  function readRows(){
    return [...document.querySelectorAll('#instRows tr')].map(tr => ({
      due: tr.querySelector('[data-k=due]').value, amount: Math.round(+tr.querySelector('[data-k=amount]').value || 0),
    }));
  }
  window.instSumCheck = function(){
    const total = Math.round(+document.getElementById('instTotal').value || 0);
    const sum = readRows().reduce((a, r) => a + r.amount, 0);
    const ok = total > 0 && sum === total;
    const el = document.getElementById('instSumCheck');
    el.innerHTML = ok ? `<span style="color:var(--teal);">✓ Итого по графику ${money(sum)}</span>`
      : `<span style="color:var(--coral);">Итого по графику ${money(sum)} — должно быть ${money(total)}</span>`;
    document.getElementById('instSaveBtn').disabled = !ok;
  };
  window.instSave = async function(){
    const fd = new FormData();
    fd.append('patient_id', instPatientId);
    fd.append('total', Math.round(+document.getElementById('instTotal').value || 0));
    fd.append('note', document.getElementById('instNote').value);
    fd.append('rows', JSON.stringify(readRows()));
    const res = await postForm('/new/installments/create/', fd);
    const d = await res.json().catch(() => ({}));
    if(!res.ok || !d.ok){ showToast(d.error || 'Не удалось оформить', 'error'); return; }
    closeModal('m-inst');
    showToast('Рассрочка оформлена', 'success');
    if(instOnDone) instOnDone();
  };
  window.instCancel = async function(planId, onDone){
    if(!confirm('Отменить рассрочку? Платежи пациента останутся, просто график перестанет действовать.')) return;
    const res = await postForm('/new/installments/' + planId + '/cancel/', new FormData());
    const d = await res.json().catch(() => ({}));
    if(!res.ok || !d.ok){ showToast(d.error || 'Не удалось', 'error'); return; }
    showToast('Рассрочка отменена', 'success');
    if(onDone) onDone();
  };

  const ST_COLOR = {paid: 'var(--teal)', partial: '#b45309', overdue: 'var(--coral)', upcoming: 'var(--ink-soft)'};
  window.instItemsTable = function(p){
    return `<table><thead><tr><th>Срок</th><th class="n">Сумма</th><th class="n">Оплачено</th><th>Статус</th></tr></thead><tbody>${
      p.items.map(i => `<tr><td>${esc(i.due)}</td><td class="n mono">${money(i.amount)}</td><td class="n mono">${i.paid ? money(i.paid) : '—'}</td>
        <td style="color:${ST_COLOR[i.status]};font-weight:600;">${esc(i.statusLabel)}</td></tr>`).join('')}</tbody></table>`;
  };

  /* Блок в карточке пациента (вкладка «Финансы») */
  window.instRenderPatientBlock = async function(container, patientId, patientName){
    if(!container) return;
    let d;
    try{
      const r = await fetch('/new/installments/patient/' + patientId + '/', {credentials: 'same-origin'});
      if(!r.ok || !(r.headers.get('content-type') || '').includes('json')) return;   // нет доступа к «Деньгам»
      d = await r.json();
    }catch(e){ return; }
    const reload = () => instRenderPatientBlock(container, patientId, patientName);
    const active = d.plans.find(p => p.status === 'active');
    const head = `<div class="card-head"><h3>Рассрочка</h3>${active ? '' :
      `<button class="btn btn-ghost btn-sm" type="button" id="instCreateBtn">+ Оформить рассрочку</button>`}</div>`;
    let body;
    if(!d.plans.length){
      body = `<div style="padding:12px 18px;font-size:12.5px;color:var(--ink-soft);">Рассрочки нет. ${d.debt > 0 ? 'Долг пациента ' + money(d.debt) + ' — можно разбить на платежи по месяцам.' : ''}</div>`;
    } else {
      body = d.plans.map(p => `<div style="padding:10px 18px;border-top:1px solid var(--mist-line,#e3e5ec);">
        <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:baseline;">
          <div><b>${money(p.total)}</b> · ${esc(p.statusLabel)} · оформлена ${esc(p.created)}${p.note ? ' · ' + esc(p.note) : ''}</div>
          <div style="font-size:12.5px;">оплачено <b style="color:var(--teal);">${money(p.paid)}</b> · осталось <b>${money(p.left)}</b>${p.overdue > 0 ? ` · <b style="color:var(--coral);">просрочено ${money(p.overdue)}</b>` : ''}</div>
        </div>
        ${p.status === 'active' && p.nextDue ? `<div style="font-size:12.5px;margin-top:4px;">Следующий платёж: <b>${esc(p.nextDue)}</b> — ${money(p.nextAmount)}</div>` : ''}
        <div style="overflow-x:auto;margin-top:6px;">${instItemsTable(p)}</div>
        ${p.status === 'active' ? `<div style="text-align:right;margin-top:6px;"><button class="btn btn-ghost btn-sm" type="button" data-cancel="${p.id}">Отменить рассрочку</button></div>` : ''}
      </div>`).join('');
    }
    container.innerHTML = `<div class="card" style="margin-top:14px;">${head}${body}</div>`;
    const btn = container.querySelector('#instCreateBtn');
    if(btn) btn.onclick = () => instOpenCreate(patientId, patientName, d.debt, reload, d.today);
    container.querySelectorAll('[data-cancel]').forEach(b => b.onclick = () => instCancel(+b.dataset.cancel, reload));
  };
})();
