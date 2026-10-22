// Общие функции сайта: переводы, аналитика, маска телефона, окно быстрой заявки («Написать нам», «Нужна помощь?»).
// window.JQ_LANG, window.JQ_CONFIG и window.I18N подставляет сервер (см. {{boot}} в шаблонах).
(function () {
  document.documentElement.classList.add('js');
  const CFG = window.JQ_CONFIG || {};
  const JQ = (window.JQ = window.JQ || {});
  JQ.lang = window.JQ_LANG || 'ru';

  // перевод строки по ключу; {n}, {v}… подставляются из vars
  JQ.t = function (key, vars) {
    let s = (window.I18N || {})[key];
    if (s == null) s = key;
    return vars ? String(s).replace(/\{(\w+)\}/g, (m, n) => (vars[n] != null ? vars[n] : m)) : s;
  };
  const t = JQ.t;

  // переключатель языка сохраняет параметры и якорь текущей страницы
  document.querySelectorAll('[data-lang-switch]').forEach(a => { a.href = a.getAttribute('href').split(/[?#]/)[0] + location.search + location.hash; });

  // ---- аналитика: только события и безопасные параметры, без персональных данных ----
  JQ.track = function (name, props) {
    try {
      (window.dataLayer = window.dataLayer || []).push(Object.assign({ event: name }, props || {}));
      if (window.JQ_DEBUG) console.debug('[track]', name, props || {});
    } catch (_) {}
  };

  JQ.uuid = () =>
    (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
      : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3 | 8)).toString(16); });

  // телефон Казахстана: маска +7 (XXX) XXX-XX-XX
  JQ.maskPhone = function (v) {
    let d = String(v).replace(/\D/g, '');
    if (d[0] === '8') d = '7' + d.slice(1);
    if (d && d[0] !== '7') d = '7' + d;
    d = d.slice(0, 11);
    const p = d.slice(1);
    let out = d ? '+7' : '';
    if (p.length) out += ' (' + p.slice(0, 3);
    if (p.length >= 3) out += ')';
    if (p.length > 3) out += ' ' + p.slice(3, 6);
    if (p.length > 6) out += '-' + p.slice(6, 8);
    if (p.length > 8) out += '-' + p.slice(8, 10);
    return out;
  };
  JQ.phoneValid = v => { const d = String(v).replace(/\D/g, ''); return d.length === 11 && d[0] === '7'; };

  // адреса: JQ.url — API сервера заявок, JQ.asset — файлы сайта (с учётом префикса на статическом хостинге)
  JQ.url = p => (CFG.api || '') + p;
  JQ.asset = p => (CFG.root || '') + p;
  JQ.postJSON = async function (url, body) {
    if (CFG.demo) return { ok: false, status: 0, data: { message: t('demo.submit') } }; // сервер заявок не подключён
    const r = await fetch(JQ.url(url), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    let data = {}; try { data = await r.json(); } catch (_) {}
    return { ok: r.ok, status: r.status, data };
  };

  // откуда пришёл человек: добавляется к заявке автоматически
  JQ.sourceInfo = function () {
    const q = new URLSearchParams(location.search), utm = {};
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'].forEach(k => { if (q.get(k)) utm[k] = q.get(k); });
    let page = q.get('from') || '';
    if (!page && document.referrer) { try { const u = new URL(document.referrer); if (u.origin === location.origin) page = u.pathname + u.hash; else page = u.hostname; } catch (_) {} }
    return { page: page || location.pathname, project_id: q.get('project_id') || null, utm };
  };

  // ---- окно быстрой заявки ----
  const TYPES = ['question', 'measure', 'discuss'];
  const TYPE_LABEL = { question: { ru: 'Задать вопрос', kk: 'Сұрақ қою' }, measure: { ru: 'Заказать замер', kk: 'Өлшеуге тапсырыс беру' }, discuss: { ru: 'Обсудить проект', kk: 'Жобаны талқылау' } };
  const wa = CFG.whatsapp ? `https://wa.me/${CFG.whatsapp}` : '#';
  let modal, lastFocus, ctx = '';

  function build() {
    modal = document.createElement('div');
    modal.className = 'qm'; modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-modal', 'true'); modal.setAttribute('aria-labelledby', 'qm-t');
    modal.innerHTML = `
      <div class="qm-box">
        <button class="qm-x" type="button" aria-label="${t('qm.close')}">×</button>
        <form id="qf" novalidate>
          <h3 id="qm-t">${t('qm.title')}</h3>
          <p class="sub">${t('qm.sub')}</p>
          <div class="field" data-f="type"><span>${t('qm.help')}</span>
            <div class="pills">${TYPES.map(k => `<label class="pill"><input type="radio" name="request_type" value="${k}"${k === 'discuss' ? ' checked' : ''}><span>${TYPE_LABEL[k][JQ.lang] || TYPE_LABEL[k].ru}</span></label>`).join('')}</div>
          </div>
          <label class="field"><span>${t('qm.name')} <i>— ${t('qm.optional')}</i></span><input class="inp" name="name" autocomplete="name"></label>
          <label class="field" data-f="phone"><span>${t('qm.phone')}</span><input class="inp" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="+7 (___) ___-__-__"><div class="msg">${t('qm.phone.err')}</div></label>
          <div class="field"><span>${t('qm.channel')}</span>
            <div class="pills"><label class="pill"><input type="radio" name="channel" value="whatsapp" checked><span>WhatsApp</span></label><label class="pill"><input type="radio" name="channel" value="call"><span>${JQ.lang === 'kk' ? 'Қоңырау' : 'Звонок'}</span></label></div>
          </div>
          <label class="field"><span>${t('qm.message')} <i>— ${t('qm.optional')}</i></span><textarea class="inp" name="message" rows="2" maxlength="1000"></textarea></label>
          <input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
          <label class="check" data-f="consent"><input type="checkbox" name="consent"><span>${t('qm.consent')} <a href="${CFG.policyUrl || '#'}" target="_blank" rel="noopener">${t('foot.policy')}</a></span></label>
          <div class="msg" data-m="consent">${t('qm.consent.err')}</div>
          <div class="alert" id="qerr"></div>
          <button class="btn" type="submit" style="width:100%;margin-top:14px">${t('qm.submit')}</button>
          <p class="sub" style="margin:16px 0 0;text-align:center">${t('qm.or')} <a class="link" href="${wa}" target="_blank" rel="noopener">WhatsApp</a></p>
        </form>
        <div class="okbox" id="qok" hidden><div class="big">✓</div><h3>${t('qm.ok.h')}</h3><p class="sub" id="qokn"></p><button class="btn ghost sm" type="button" data-close>${t('qm.close')}</button></div>
      </div>`;
    document.body.appendChild(modal);
    const form = modal.querySelector('#qf'), phone = form.phone;
    phone.addEventListener('input', () => { phone.value = JQ.maskPhone(phone.value); phone.closest('.field').classList.remove('err'); });
    modal.addEventListener('click', e => { if (e.target === modal || e.target.closest('.qm-x') || e.target.closest('[data-close]')) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal.classList.contains('on')) close(); });
    let sid = JQ.uuid();
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const err = modal.querySelector('#qerr'); err.classList.remove('on');
      let bad = false;
      if (!JQ.phoneValid(phone.value)) { phone.closest('.field').classList.add('err'); bad = true; }
      const cm = modal.querySelector('[data-m=consent]'); cm.classList.toggle('on', !form.consent.checked); if (!form.consent.checked) bad = true;
      if (bad) { (modal.querySelector('.err .inp') || form.consent).focus(); return; }
      const btn = form.querySelector('[type=submit]'); btn.disabled = true; btn.textContent = t('qm.sending');
      const payload = {
        schema_version: 1, submission_id: sid, lead_type: 'quick', locale: JQ.lang, hp: form.website.value,
        source: JQ.sourceInfo(),
        customer: { name: form.name.value.trim() || null, phone: form.phone.value, preferred_channel: form.channel.value },
        quick: { request_type: form.request_type.value, message: form.message.value.trim() || null, context: ctx || null },
        consent: { project_contact: true, policy_version: CFG.policyVersion || '' },
      };
      try {
        const r = await JQ.postJSON('/api/leads', payload);
        if (r.ok) {
          JQ.track('quick_contact_submitted', { type: payload.quick.request_type });
          form.hidden = true; modal.querySelector('#qokn').textContent = t('qm.ok.p', { n: r.data.lead_id || '—' });
          modal.querySelector('#qok').hidden = false; sid = JQ.uuid(); form.reset(); form.request_type.value = 'discuss';
        } else if (r.status === 422 && r.data.errors) {
          if (r.data.errors['customer.phone']) phone.closest('.field').classList.add('err');
          err.textContent = t('qm.phone.err'); err.classList.add('on');
        } else { err.textContent = r.data.message || t('qm.err.generic'); err.classList.add('on'); }
      } catch (_) { err.textContent = t('qm.err.net'); err.classList.add('on'); JQ.track('request_failed', { type: 'network', lead: 'quick' }); }
      btn.disabled = false; btn.textContent = t('qm.submit');
    });
  }
  function open(context) {
    if (!modal) build();
    ctx = context || ''; lastFocus = document.activeElement;
    modal.querySelector('#qf').hidden = false; modal.querySelector('#qok').hidden = true;
    modal.classList.add('on'); document.body.style.overflow = 'hidden';
    JQ.track('quick_contact_opened', { from: ctx || location.pathname });
    setTimeout(() => modal.querySelector('[name=phone]').focus(), 50);
  }
  function close() { modal.classList.remove('on'); document.body.style.overflow = ''; if (lastFocus) lastFocus.focus(); }
  JQ.openQuick = open;

  document.addEventListener('click', e => { const el = e.target.closest('[data-quick]'); if (el) { e.preventDefault(); open(el.dataset.quick); } });
  window.JQ_wireFab = function () {
    if (document.querySelector('.fab')) return;
    const b = document.createElement('button'); b.className = 'fab'; b.type = 'button'; b.dataset.quick = 'fab';
    b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.3A8 8 0 1 1 21 12z"/></svg><span>' + t('fab') + '</span>';
    document.body.appendChild(b);
  };
})();
