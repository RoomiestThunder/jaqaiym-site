// Анкета «Рассказать о проекте»: 4 шага, ветки по типу заказа, обязательные поля, черновик, файлы, итоги, отправка.
// Тексты берутся из window.I18N (ru/kk), подписи вариантов ответа — из /schema.json (+ kk-перевод из I18N.schema).
(async function () {
  'use strict';
  const CFG = window.JQ_CONFIG || {}, JQ = window.JQ, t = JQ.t;
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const app = $('#app');

  let S;
  try { S = await (await fetch(JQ.asset('/schema.json'), { cache: 'no-cache' })).json(); }
  catch (_) { app.innerHTML = `<p class="wz-sub">${t('wz.loadfail')}</p>`; return; }
  const KK = (window.I18N && window.I18N.schema) || null;
  const L = {}; // подписи ответов на текущем языке
  Object.keys(S).forEach(g => { L[g] = (JQ.lang === 'kk' && KK && KK[g]) ? Object.assign({}, S[g], KK[g]) : S[g]; });
  const base = CFG.base || '';

  // проекты, с которых можно прийти по кнопке «Хочу похожее»
  const PROJECTS = {
    'kitchen-green': { img: JQ.asset('/img/work/k-1.jpg'), category: 'kitchen' },
    'wardrobe-dressing': { img: JQ.asset('/img/work/w-2.jpg'), category: 'wardrobe' },
    'hallway-niche': { img: JQ.asset('/img/work/h-1.jpg'), category: 'other_furniture' },
    'residential-complex': { img: JQ.asset('/img/work/lobby-1.jpg'), category: 'business' },
  };

  // ---------------- иконки ----------------
  const svg = (b, vb = '0 0 96 72') => `<svg viewBox="${vb}" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${b}</svg>`;
  const Q = svg('<text x="48" y="54" text-anchor="middle" font-size="46" font-family="Playfair Display,serif" fill="currentColor" stroke="none">?</text>');
  const ICON = {
    apartment: svg('<rect x="26" y="8" width="44" height="58" rx="2"/><path d="M36 20h8M52 20h8M36 32h8M52 32h8M36 44h8M52 44h8M42 66V54h12v12"/>'),
    house: svg('<path d="M12 36L48 10l36 26"/><path d="M20 30v36h56V30"/><rect x="40" y="44" width="16" height="22"/>'),
    office: svg('<rect x="22" y="14" width="52" height="52" rx="2"/><path d="M32 26h10M54 26h10M32 38h10M54 38h10M42 66V52h12v14M10 66h76"/>'),
    residential_complex: svg('<rect x="12" y="26" width="20" height="40"/><rect x="38" y="10" width="24" height="56"/><rect x="68" y="30" width="16" height="36"/><path d="M44 22h12M44 34h12M44 46h12M18 36h8M18 48h8M72 40h8M6 66h84"/>'),
    other: svg('<circle cx="26" cy="36" r="4" fill="currentColor"/><circle cx="48" cy="36" r="4" fill="currentColor"/><circle cx="70" cy="36" r="4" fill="currentColor"/>'),
    niche: svg('<path d="M10 6h76v62H10z"/><rect x="20" y="14" width="56" height="54" fill="currentColor" fill-opacity=".12"/><path d="M48 14v54M42 40v8M54 40v8"/>'),
    freestanding: svg('<rect x="18" y="6" width="60" height="56" rx="3"/><path d="M48 6v56M42 32v8M54 32v8M24 62v6M72 62v6"/>'),
    dressing_room: svg('<path d="M8 8h80v58H8z"/><path d="M16 22h30M20 22v10M28 22v14M36 22v10M44 22v14M58 22h22M58 36h22M58 50h22"/>'),
    swing: svg('<rect x="12" y="8" width="35" height="56"/><rect x="49" y="8" width="35" height="56"/><path d="M42 32v10M54 32v10"/><path d="M12 64c16 0 30-14 30-30" stroke-dasharray="3 5" opacity=".55"/>'),
    sliding: svg('<rect x="10" y="8" width="46" height="56"/><rect x="40" y="8" width="46" height="56" fill="currentColor" fill-opacity=".1"/><path d="M58 36h16M68 29l7 7-7 7"/>'),
    open: svg('<rect x="14" y="8" width="68" height="56"/><path d="M14 27h68M14 46h68"/><rect x="22" y="12" width="12" height="11" opacity=".6"/><rect x="48" y="31" width="20" height="11" opacity=".6"/><rect x="26" y="50" width="14" height="10" opacity=".6"/>'),
    image: svg('<rect x="8" y="12" width="80" height="48" rx="4"/><circle cx="30" cy="30" r="6"/><path d="M8 52l22-16 16 12 14-10 28 18"/>'),
    upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>',
  };
  const PLAN = { // схемы кухонь сверху: прямоугольники — столешницы вдоль стен
    straight: [[10, 10, 100, 16]],
    l_shaped: [[10, 10, 100, 16], [10, 26, 16, 48]],
    u_shaped: [[10, 10, 100, 16], [10, 26, 16, 48], [94, 26, 16, 48]],
    parallel: [[10, 10, 100, 16], [10, 58, 100, 16]],
    island: [[10, 10, 100, 16], [34, 44, 52, 18, 1]],
  };
  const LETTERS = {
    straight: [['A', 60, 23]], l_shaped: [['A', 60, 23], ['B', 18, 54]], u_shaped: [['A', 60, 23], ['B', 18, 54], ['C', 102, 54]],
    parallel: [['A', 60, 23], ['B', 60, 71]], island: [['A', 60, 23], ['B', 60, 57]], unknown: [['A', 60, 45]],
  };
  const planSvg = (kind, letters) => {
    if (kind === 'unknown') return letters ? svg('<rect x="10" y="10" width="100" height="16" fill="currentColor"/><text x="60" y="23" text-anchor="middle" font-size="11" font-weight="800" fill="#fffaf0" stroke="none">A</text><path d="M10 40h100M10 52h100" stroke-dasharray="3 5" opacity=".4"/>', '0 0 120 84') : Q;
    const r = PLAN[kind].map(([x, y, w, h, acc]) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="2" fill="${acc ? '#b45c37' : 'currentColor'}" stroke="none"/>`).join('');
    const l = letters ? LETTERS[kind].map(([tx, x, y]) => `<text x="${x}" y="${y}" text-anchor="middle" font-size="11" font-weight="800" fill="#fffaf0" stroke="none">${tx}</text>`).join('') : '';
    return svg(`<rect x="4" y="4" width="112" height="76" rx="3" opacity=".25" stroke-dasharray="2 5"/>${r}${l}`, '0 0 120 84');
  };
  const DIMS = { // поля размеров по планировке кухни: [ключ, ключ перевода]
    straight: [['a', 'd.k.straight.a']],
    l_shaped: [['a', 'd.k.l.a'], ['b', 'd.k.l.b']],
    u_shaped: [['a', 'd.k.u.a'], ['b', 'd.k.u.b'], ['c', 'd.k.u.c']],
    parallel: [['a', 'd.k.par.a'], ['b', 'd.k.par.b']],
    island: [['a', 'd.k.isl.a'], ['b', 'd.k.isl.b']],
    unknown: [['a', 'd.k.unk.a']],
  };
  const swatch = k => k === 'has_example' ? `<span class="sv sv-has_example">${ICON.image}</span>` : k === 'undecided' ? '<span class="sv sv-undecided">?</span>' : `<span class="sv sv-${k}"></span>`;

  // ---------------- состояние и черновик ----------------
  const KEY = 'jq_request_draft', VER = 2, TTL = 7 * 24 * 3600 * 1000;
  const fresh = () => ({ v: VER, savedAt: Date.now(), sid: JQ.uuid(), step: 1, category: null, premise: null, layout: null, wardrobeKind: null, businessScope: null,
    city: null, style: [], styleNote: '', kf: { upper: null, island: null, appliances: null }, doors: [], storage: [], purposes: [],
    bizType: '', bizTask: '', bizQty: '', dimsUnknown: false, dims: {}, files: [], notes: '', budget: null, timeframe: null, projectId: null });
  function load() { try { const d = JSON.parse(localStorage.getItem(KEY)); if (d && d.v === VER && Date.now() - d.savedAt < TTL) return Object.assign(fresh(), d); } catch (_) {} return fresh(); }
  let st = load();
  if (!S.city[st.city]) st.city = null;
  let saveT;
  const save = () => { clearTimeout(saveT); saveT = setTimeout(() => { try { st.savedAt = Date.now(); localStorage.setItem(KEY, JSON.stringify(Object.assign({}, st, { files: st.files.filter(f => f.status === 'ok').map(f => ({ key: f.key, id: f.id, name: f.name, size: f.size, mime: f.mime, status: 'ok' })) }))); } catch (_) {} }, 150); };
  const contact = (() => { try { return JSON.parse(sessionStorage.getItem('jq_contact')) || {}; } catch (_) { return {}; } })();
  const C = Object.assign({ name: '', phone: '', channel: 'whatsapp', time: '', email: '', company: '', role: '' }, contact);
  let consent = false, busy = false, returnTo4 = false, doneNo = null, sendError = '';
  const errs = {}; // id -> текст ошибки; пока ключ есть, блок подсвечивается
  const hasErr = id => Object.prototype.hasOwnProperty.call(errs, id);
  const saveContact = () => { try { sessionStorage.setItem('jq_contact', JSON.stringify(C)); } catch (_) {} };

  const getPath = p => p.split('.').reduce((o, k) => (o == null ? o : o[k]), st);
  const setPath = (p, v) => { const ks = p.split('.'), last = ks.pop(); ks.reduce((a, k) => a[k], st)[last] = v; };

  // параметры из ссылки подставляются, но клиент может изменить
  const src = JQ.sourceInfo(), qs = new URLSearchParams(location.search);
  if (qs.get('category') && S.category[qs.get('category')]) st.category = qs.get('category');
  if (qs.get('project_id') && PROJECTS[qs.get('project_id')]) { st.projectId = qs.get('project_id'); if (!qs.get('category')) st.category = st.category || PROJECTS[st.projectId].category; }
  else if (qs.get('project_id')) st.projectId = String(qs.get('project_id')).slice(0, 60);
  JQ.track('request_opened', { source: src.page, has_project: !!st.projectId });

  // ---------------- помощники отрисовки ----------------
  const opt = (field, val, label, o = {}) => {
    const cur = getPath(field), on = o.multi ? (cur || []).includes(val) : cur === val;
    return `<button type="button" class="opt ${o.cls || ''}" data-f="${field}" data-v="${val}"${o.multi ? ' data-m="1"' : ''}${o.req ? ' data-r="1"' : ''} aria-pressed="${on}">${o.vis ? `<span class="v">${o.vis}</span>` : ''}<span class="t">${esc(label)}</span></button>`;
  };
  const optsFrom = (field, dict, o = {}) => Object.keys(dict).filter(k => !k.startsWith('_')).map(k => opt(field, k, dict[k], Object.assign({}, o, { vis: o.vis ? o.vis(k) : null }))).join('');
  const chip = (field, val, label, o = {}) => { const cur = getPath(field), on = o.multi ? (cur || []).includes(val) : cur === val; return `<button type="button" class="chip" data-f="${field}" data-v="${val}"${o.multi ? ' data-m="1"' : ''}${o.req ? ' data-r="1"' : ''} aria-pressed="${on}">${esc(label)}</button>`; };
  const q = (id, title, hint, body, o = {}) => `<div class="q${hasErr(id) ? ' err' : ''}" id="q-${id}" role="group" aria-labelledby="qh-${id}"><h3 id="qh-${id}">${title}${o.req ? ' <em title="' + esc(t('wz.required')) + '">*</em>' : ''}</h3>${hint ? `<p class="hint">${hint}</p>` : ''}${body}<div class="emsg" role="alert">${esc(errs[id] || '')}</div></div>`;
  const input = (bind, label, o = {}) => `<label class="field${hasErr(bind) ? ' err' : ''}" data-b="${bind}"><span>${label}${o.req ? ' <em class="rq">*</em>' : ''}${o.opt ? ' <i>— ' + t('wz.optional') + '</i>' : ''}</span>${o.area ? `<textarea class="inp" data-bind="${bind}" rows="${o.rows || 3}" maxlength="${o.max || 2000}" placeholder="${esc(o.ph || '')}">${esc(o.val)}</textarea>` : `<input class="inp" data-bind="${bind}" value="${esc(o.val)}" placeholder="${esc(o.ph || '')}" maxlength="${o.max || 150}" autocomplete="off">`}<div class="emsg" role="alert">${esc(errs[bind] || '')}</div></label>`;
  const catImg = n => `<img src="${JQ.asset('/img/work/' + n + '.jpg')}" alt="" loading="lazy">`;
  const catVis = k => ({ kitchen: catImg('k-1'), wardrobe: catImg('w-2'), other_furniture: catImg('h-1'), business: catImg('lobby-1'), other: ICON.other }[k]);
  const fmtSize = b => { const n = b > 1048576 ? (b / 1048576).toFixed(1).replace('.', ',') + ' ' + t('file.mb') : Math.max(1, Math.round(b / 1024)) + ' ' + t('file.kb'); return n; };
  const lblList = (g, arr) => (arr || []).map(k => L[g][k]).join(', ');

  // ---------------- шаги ----------------
  function bannerHtml() {
    const p = st.projectId && PROJECTS[st.projectId]; if (!p) return '';
    return `<div class="banner"><img src="${p.img}" alt=""><div><b>${esc(t('proj.' + st.projectId))}</b><span>${t('banner.p')}</span></div></div>`;
  }

  function step1() {
    let h = `<h1 class="wz-h">${t('s1.h')}</h1><p class="wz-sub">${t('s1.sub')}</p>` + bannerHtml();
    h += q('category', t('q.category'), '', `<div class="opts big">${optsFrom('category', L.category_short, { req: 1, vis: catVis })}</div>`, { req: 1 });
    if (st.category) {
      h += q('premise', t('q.premise'), t('q.premise.hint'), `<div class="opts sm">${optsFrom('premise', L.premise, { req: 1, vis: k => ICON[k] })}</div>`, { req: 1 });
      if (st.category === 'kitchen') h += q('layout', t('q.layout'), t('q.layout.hint'), `<div class="opts sm">${optsFrom('layout', L.kitchen_layout, { req: 1, vis: k => planSvg(k, false) })}</div>`, { req: 1 });
      if (st.category === 'wardrobe') h += q('wardrobeKind', t('q.wardrobeKind'), '', `<div class="opts sm">${optsFrom('wardrobeKind', L.wardrobe_kind, { req: 1, vis: k => k === 'unknown' ? Q : ICON[k] })}</div>`, { req: 1 });
      if (st.category === 'business') h += q('businessScope', t('q.businessScope'), t('q.businessScope.hint'), `<div class="opts">${optsFrom('businessScope', L.business_scope, { req: 1, cls: 'txt' })}</div>`, { req: 1 });
    }
    h += q('city', t('q.city'), t('q.city.hint'), `<div class="chips">${Object.keys(L.city).map(k => chip('city', k, L.city[k], { req: 1 })).join('')}</div>`, { req: 1 });
    return h;
  }

  function step2() {
    const c = st.category;
    let h = `<h1 class="wz-h">${t('s2.h')}</h1><p class="wz-sub">${t('s2.sub')}</p>`;
    h += q('style', t('q.style'), t('hint.multi'), `<div class="opts sm">${optsFrom('style', L.style, { multi: 1, vis: swatch })}</div>`, { req: 1 });
    if (c === 'kitchen') {
      const row = (k, tt) => `<div class="yn${hasErr('kf.' + k) ? ' miss' : ''}"><span>${tt}</span><div class="chips">${Object.keys(L.yes_no).map(v => chip('kf.' + k, v, L.yes_no[v], { req: 1 })).join('')}</div></div>`;
      h += q('kitchen', t('q.kitchen'), t('q.kitchen.hint'), row('upper', t('yn.upper')) + row('island', t('yn.island')) + row('appliances', t('yn.appliances')), { req: 1 });
    }
    if (c === 'wardrobe') {
      h += q('doors', t('q.doors'), t('hint.multi'), `<div class="opts sm">${optsFrom('doors', L.doors, { multi: 1, vis: k => k === 'unknown' ? Q : ICON[k] })}</div>`, { req: 1 });
      h += q('storage', t('q.storage'), t('hint.multi'), `<div class="chips">${Object.keys(L.storage).map(k => chip('storage', k, L.storage[k], { multi: 1 })).join('')}</div>`, { req: 1 });
    }
    if (c === 'other_furniture') h += q('purposes', t('q.purposes'), t('q.purposes.hint'), `<div class="chips">${Object.keys(L.purpose).map(k => chip('purposes', k, L.purpose[k], { multi: 1 })).join('')}</div>`, { req: 1 });
    if (c === 'business') {
      h += q('biz', t('q.biz'), t('q.biz.hint'),
        input('bizType', t('f.bizType'), { val: st.bizType, ph: t('ph.bizType'), req: 1 }) + input('bizTask', t('f.bizTask'), { val: st.bizTask, area: 1, rows: 3, ph: t('ph.bizTask'), req: 1 }), { req: 0 });
    }
    h += `<div class="q">${input('styleNote', t('f.styleNote'), { val: st.styleNote, area: 1, rows: 2, opt: 1, ph: t('ph.styleNote'), max: 500 })}</div>`;
    return h;
  }

  const dimFields = () => st.category === 'kitchen' ? DIMS[st.layout || 'unknown'].map(([k, tk]) => [k, t(tk)]) : [['width', t('d.width')], ['height', t('d.height')], ['depth', t('d.depth')]];
  const hasDims = () => ['kitchen', 'wardrobe', 'other_furniture'].includes(st.category);
  const dimField = (key, label) => { const path = 'dims.' + key; return `<label class="field${hasErr(path) ? ' err' : ''}" data-b="${path}"><span>${label}</span><span class="unit"><input class="inp" data-bind="${path}" value="${esc(st.dims[key])}" inputmode="decimal" placeholder="${esc(t('d.ph'))}" maxlength="6" autocomplete="off"></span><div class="emsg" role="alert">${esc(errs[path] || '')}</div></label>`; };

  function dimsBlock() {
    if (!hasDims()) return '';
    const c = st.category;
    let inner = '';
    if (st.dimsUnknown) inner = `<div class="nodims">${t('d.nodims')}</div>`;
    else if (c === 'kitchen') inner = `<div class="dimsg"><div class="pre">${planSvg(st.layout || 'unknown', true)}</div><div class="dimf">${dimFields().map(([k, l]) => dimField(k, l)).join('')}</div></div>`;
    else inner = `<div class="dimf">${dimFields().map(([k, l]) => dimField(k, l)).join('')}</div>`;
    const hint = t(c === 'kitchen' ? 'q.dims.kitchen' : c === 'wardrobe' ? 'q.dims.wardrobe' : 'q.dims.other');
    return q('dims', t('q.dims'), hint, inner + `<label class="check unknown"><input type="checkbox" data-check="dimsUnknown"${st.dimsUnknown ? ' checked' : ''}><span>${t('d.unknown')}</span></label>`, { req: 1 });
  }

  const filesHtml = () => st.files.map(fileCard).join('');
  function fileCard(f) {
    const bad = f.status === 'error', up = f.status === 'uploading';
    const th = f.url ? `<img src="${f.url}" alt="">` : (f.mime === 'application/pdf' ? 'PDF' : t('file.photo'));
    return `<div class="fl${bad ? ' bad' : ''}" data-k="${f.key}"><div class="th">${th}</div><div class="nm" title="${esc(f.name)}">${esc(f.name)}</div>
      <div class="st">${bad ? esc(f.error || t('e.upload')) : up ? t('file.uploading') : t('file.ready', { size: fmtSize(f.size) })}</div>
      ${up ? `<div class="bar"><i style="width:${f.progress || 0}%"></i></div>` : ''}${bad && f.file ? `<button class="retry" type="button" data-act="retry" data-k="${f.key}">${t('file.retry')}</button>` : ''}
      <button class="rm" type="button" data-act="rmfile" data-k="${f.key}" aria-label="${esc(t('file.rm', { name: f.name }))}">×</button></div>`;
  }

  function step3() {
    const c = st.category;
    let h = `<h1 class="wz-h">${t('s3.h')}</h1><p class="wz-sub">${t('s3.sub')}</p>` + dimsBlock();
    if (c === 'business') h += q('bizQty', t('q.bizqty'), t('q.bizqty.hint'), input('bizQty', t('f.bizQty'), { val: st.bizQty, ph: t('ph.bizQty') }), { req: 1 });
    h += q('files', t(c === 'business' ? 'q.files.biz' : 'q.files'), t('q.files.hint'),
      `<div class="drop" id="drop" tabindex="0" role="button" aria-label="${esc(t('drop.aria'))}">${ICON.upload}<b>${t('drop.title')}</b><span>${t('drop.hint', { mb: S.limits.max_file_mb, n: S.limits.max_files })}</span></div>
       <input type="file" id="fileIn" multiple accept=".jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf" hidden>
       <div class="files" id="files" aria-live="polite">${filesHtml()}</div>`);
    const other = c === 'other';
    h += q('notes', t(other ? 'q.notes.other' : 'q.notes'), t(other ? 'q.notes.other.hint' : 'q.notes.hint'), input('notes', t('f.notes'), { val: st.notes, area: 1, rows: 3, opt: !other, req: other, ph: t('ph.notes') }), { req: 0 });
    h += q('budget', t('q.budget'), t('q.budget.hint'), `<div class="chips">${Object.keys(L.budget).filter(k => !k.startsWith('_')).map(k => chip('budget', k, L.budget[k])).join('')}</div>`);
    h += q('timeframe', t('q.timeframe'), t('q.timeframe.hint'), `<div class="chips">${Object.keys(L.timeframe).map(k => chip('timeframe', k, L.timeframe[k])).join('')}</div>`);
    return h;
  }

  // сводка выбранного
  function summaryRows() {
    const c = st.category, rows = [];
    let what = [L.category[c]];
    if (st.premise) what.push(L.premise[st.premise]);
    let sub = '';
    if (c === 'kitchen' && st.layout) sub = t('sum.layout', { v: L.kitchen_layout[st.layout].toLowerCase() });
    if (c === 'wardrobe' && st.wardrobeKind) sub = L.wardrobe_kind[st.wardrobeKind];
    if (c === 'business' && st.businessScope) sub = L.business_scope[st.businessScope];
    rows.push([t('sum.order'), `${esc(what.join(' · '))}${sub ? `<small>${esc(sub)}</small>` : ''}`, 1]);
    rows.push([t('sum.city'), esc(L.city[st.city] || '—'), 1]);
    const w = [];
    if (st.style.length) w.push(t('sum.style', { v: lblList('style', st.style).toLowerCase() }));
    if (c === 'kitchen') { const f = []; [['upper', 'sum.with.upper'], ['island', 'sum.with.island'], ['appliances', 'sum.with.appliances']].forEach(([k, tk]) => { if (st.kf[k] === 'yes') f.push(t(tk)); else if (st.kf[k] === 'no') f.push(t('sum.without', { v: t(tk) })); }); if (f.length) w.push(f.join(', ')); }
    if (c === 'wardrobe') { if (st.doors.length) w.push(t('sum.doors', { v: lblList('doors', st.doors).toLowerCase() })); if (st.storage.length) w.push(t('sum.storage', { v: lblList('storage', st.storage).toLowerCase() })); }
    if (c === 'other_furniture' && st.purposes.length) w.push(t('sum.purposes', { v: lblList('purpose', st.purposes).toLowerCase() }));
    if (c === 'business') { if (st.bizType) w.push(t('sum.object', { v: st.bizType })); if (st.bizTask) w.push(t('sum.task', { v: st.bizTask })); }
    if (st.styleNote) w.push(t('sum.comment', { v: st.styleNote }));
    rows.push([t('sum.wishes'), w.length ? w.map(esc).join('<br>') : `<span style="color:var(--muted)">${t('sum.undecided')}</span>`, 2]);
    const sp = [], dm = dimsMm();
    if (c === 'business') { if (st.bizQty) sp.push(t('sum.qty', { v: st.bizQty })); }
    else if (hasDims()) sp.push(dm ? t('sum.dims', { v: Object.entries(dm).map(([k, v]) => `${({ a: 'A', b: 'B', c: 'C', width: t('sum.dim.width'), height: t('sum.dim.height'), depth: t('sum.dim.depth') })[k]} ${v / 10}`).join(', ') }) : t('sum.nodims'));
    const okf = st.files.filter(f => f.status === 'ok').length;
    sp.push(okf ? t('sum.files', { n: okf }) : t('sum.nofiles'));
    if (st.notes) sp.push(t('sum.notes', { v: st.notes }));
    if (st.budget) sp.push(t('sum.budget', { v: L.budget[st.budget] }));
    if (st.timeframe) sp.push(t('sum.time', { v: L.timeframe[st.timeframe].toLowerCase() }));
    rows.push([t('sum.space'), sp.map(esc).join('<br>'), 3]);
    return rows;
  }

  function step4() {
    const rows = summaryRows().map(([tt, v, s]) => `<div class="sr"><b>${tt}</b><div>${v}</div><button class="edit" type="button" data-act="edit" data-step="${s}">${t('sum.edit')}</button></div>`).join('');
    const biz = st.category === 'business';
    const fld = (id, label, inner, o = {}) => `<label class="field${o.full ? ' full' : ''}${hasErr(id) ? ' err' : ''}" data-b="${id}"><span>${label}${o.req ? ' <em class="rq">*</em>' : ''}${o.opt ? ' <i>— ' + t('wz.optional') + '</i>' : ''}</span>${inner}<div class="emsg" role="alert">${esc(errs[id] || '')}</div></label>`;
    let h = `<h1 class="wz-h">${t('s4.h')}</h1><p class="wz-sub">${t('s4.sub')}</p><div class="sum">${rows}</div>`;
    h += `<div class="q" id="q-contact"><h3>${t('c.h')}</h3><div class="cform" style="margin-top:16px">
      ${fld('c.name', t('c.name'), `<input class="inp" data-c="name" value="${esc(C.name)}" autocomplete="name" maxlength="100">`, { req: 1 })}
      ${fld('c.phone', t('c.phone'), `<input class="inp" data-c="phone" type="tel" inputmode="tel" autocomplete="tel" value="${esc(C.phone)}" placeholder="+7 (___) ___-__-__" maxlength="18">`, { req: 1 })}
      <div class="field full"><span>${t('c.channel')}</span><div class="pills">${['whatsapp', 'call'].map(k => `<label class="pill"><input type="radio" name="ch" data-c="channel" value="${k}"${C.channel === k ? ' checked' : ''}><span>${L.channel[k]}</span></label>`).join('')}</div></div>
      ${fld('c.time', t('c.time'), `<input class="inp" data-c="time" value="${esc(C.time)}" placeholder="${esc(t('c.time.ph'))}" maxlength="100">`, { opt: 1 })}
      ${fld('c.email', t('c.email'), `<input class="inp" data-c="email" type="email" value="${esc(C.email)}" autocomplete="email" maxlength="150">`, { opt: 1 })}
      ${biz ? `<div class="full biz"><div class="cform"><label class="field"><span>${t('c.company')} <i>— ${t('wz.optional')}</i></span><input class="inp" data-c="company" value="${esc(C.company)}" maxlength="150"></label>
        <label class="field"><span>${t('c.role')} <i>— ${t('wz.optional')}</i></span><select class="inp" data-c="role"><option value="">${t('c.role.none')}</option>${Object.keys(L.role).map(k => `<option value="${k}"${C.role === k ? ' selected' : ''}>${L.role[k]}</option>`).join('')}</select></label></div></div>` : ''}
      </div>
      <input class="hp" id="hp" tabindex="-1" autocomplete="off" aria-hidden="true" name="website">
      <label class="check" id="consentRow"><input type="checkbox" id="consent"${consent ? ' checked' : ''}><span>${t('c.consent')} <a href="${(CFG.policyUrl || '#') + '#consent'}" target="_blank" rel="noopener">${t('c.policy')}</a></span></label>
      <div class="emsg${hasErr('consent') ? ' show' : ''}" id="consentErr" role="alert">${t('c.consent.err')}</div>
    </div>
    <div class="alert${sendError ? ' on' : ''}" id="sendErr" role="alert">${esc(sendError)}</div>`;
    return h;
  }

  function doneScreen() {
    return `<div class="done step-in"><div class="big">✓</div><h1 class="wz-h" style="font-size:clamp(30px,4vw,44px)">${t('done.h')}</h1>
      <div class="no">${t('done.no', { n: esc(doneNo) })}</div>
      <p>${t('done.p1')}</p><p>${t('done.p2')}</p>
      <div class="row"><a class="btn" href="${base}/">${t('done.home')}</a><button class="btn ghost" type="button" data-act="again">${t('done.again')}</button></div></div>`;
  }

  // ---------------- перерисовка ----------------
  const STEPS = [null, step1, step2, step3, step4];
  function render(keepFocus, animate) {
    const nav = $('#nav');
    if (doneNo) { app.innerHTML = doneScreen(); nav.hidden = true; $('#meta').textContent = ''; $$('#prog i').forEach(i => i.classList.add('on')); return; }
    if (st.step > 1 && !st.category) st.step = 1;
    app.innerHTML = `<div class="${animate ? 'step-in' : ''}" id="stepBox">${CFG.demo ? `<div class="alert on" style="margin:0 0 28px">${t('demo.banner')}</div>` : ''}${STEPS[st.step]()}</div>`;
    nav.hidden = false;
    $('#meta').innerHTML = `<span>${t('wz.step', { n: st.step })}</span><span>${t('wz.s' + st.step)}</span>`;
    $$('#prog i').forEach((i, n) => i.classList.toggle('on', n < st.step));
    $('#help').dataset.quick = 'wizard-step-' + st.step;
    const b = $('#back'), nx = $('#next');
    b.hidden = st.step === 1 && !returnTo4; b.textContent = t(returnTo4 ? 'wz.back.sum' : 'wz.back');
    nx.disabled = busy;
    nx.textContent = st.step === 4 ? t(busy ? 'wz.sending' : 'wz.send') : t(returnTo4 ? 'wz.next.sum' : 'wz.next');
    if (keepFocus) { const el = $(keepFocus); if (el) el.focus({ preventScroll: true }); }
    if (st.step === 3) wireFiles();
  }

  function go(n, opts = {}) {
    if (!opts.keepErrs) Object.keys(errs).forEach(k => delete errs[k]);
    st.step = n; save(); render(null, true);
    if (!opts.keepScroll) { window.scrollTo({ top: 0, behavior: 'auto' }); app.focus({ preventScroll: true }); }
    if (opts.keepErrs) scrollToError();
  }
  function scrollToError() { const el = $('.q.err,.field.err,.yn.miss'); if (el) { const r = el.getBoundingClientRect(); window.scrollTo({ top: Math.max(0, window.scrollY + r.top - 150), behavior: 'smooth' }); } }

  // ---------------- обязательные поля ----------------
  function dimNum(v) { const n = parseFloat(String(v == null ? '' : v).replace(',', '.')); return isNaN(n) ? null : n; }
  function check(n) {
    const e = {}, c = st.category;
    if (n === 1) {
      if (!c) e.category = t('e.pick');
      else {
        if (!st.premise) e.premise = t('e.pick');
        if (c === 'kitchen' && !st.layout) e.layout = t('e.pick');
        if (c === 'wardrobe' && !st.wardrobeKind) e.wardrobeKind = t('e.pick');
        if (c === 'business' && !st.businessScope) e.businessScope = t('e.pick');
      }
      if (!st.city) e.city = t('e.pick');
    }
    if (n === 2) {
      if (!st.style.length) e.style = t('e.pickmany');
      if (c === 'kitchen') ['upper', 'island', 'appliances'].forEach(k => { if (!st.kf[k]) { e['kf.' + k] = 1; e.kitchen = t('e.pick'); } });
      if (c === 'wardrobe') { if (!st.doors.length) e.doors = t('e.pickmany'); if (!st.storage.length) e.storage = t('e.pickmany'); }
      if (c === 'other_furniture' && !st.purposes.length) e.purposes = t('e.pickmany');
      if (c === 'business') { if (!st.bizType.trim()) e.bizType = t('e.fill'); if (!st.bizTask.trim()) e.bizTask = t('e.fill'); }
    }
    if (n === 3) {
      if (hasDims() && !st.dimsUnknown) dimFields().forEach(([k]) => {
        const v = st.dims[k], num = dimNum(v);
        if (v == null || String(v).trim() === '') { e['dims.' + k] = t('e.dimreq'); e.dims = t('e.dimreq'); }
        else if (!(num >= 10 && num <= 3000)) { e['dims.' + k] = t('e.dim'); e.dims = t('e.dim'); }
      });
      if (c === 'business' && !st.bizQty.trim()) e.bizQty = t('e.fill');
      if (c === 'other' && st.notes.trim().length < 5) e.notes = t('e.notes');
      if (st.files.some(f => f.status === 'uploading')) e.files = t('e.wait');
      else if (st.files.some(f => f.status === 'error')) e.files = t('e.badfiles');
    }
    if (n === 4) {
      if (!C.name.trim()) e['c.name'] = t('c.name.err');
      if (!JQ.phoneValid(C.phone)) e['c.phone'] = t('c.phone.err');
      if (C.email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(C.email.trim())) e['c.email'] = t('c.email.err');
      if (!consent) e.consent = 1;
    }
    return e;
  }
  // проверяет шаг; при ошибках подсвечивает блоки и прокручивает к первому
  function validate(n) {
    Object.keys(errs).forEach(k => delete errs[k]);
    Object.assign(errs, check(n));
    if (!Object.keys(errs).length) return true;
    const keep = document.activeElement && document.activeElement.id === 'next' ? null : null;
    render(keep); scrollToError();
    return false;
  }

  // ---------------- данные заявки ----------------
  const cm2mm = v => { const n = dimNum(v); return n == null ? null : Math.round(n * 10); };
  function dimsMm() {
    if (st.dimsUnknown || !hasDims()) return null;
    const keys = dimFields().map(x => x[0]), out = {};
    keys.forEach(k => { const v = cm2mm(st.dims[k]); if (v) out[k] = v; });
    return Object.keys(out).length ? out : null;
  }
  function buildPayload() {
    const c = st.category, dm = dimsMm(), features = {};
    const project = { category: c, premise: st.premise, city: st.city,
      style_preferences: st.style, style_note: st.styleNote.trim() || null, dimensions_known: !!dm, dimensions_mm: dm,
      budget_range: st.budget, timeframe: st.timeframe, description: st.notes.trim() || null,
      attachment_ids: st.files.filter(f => f.status === 'ok').map(f => f.id) };
    if (c === 'kitchen') { project.layout = st.layout; Object.assign(features, { upper_cabinets: st.kf.upper, island: st.kf.island, built_in_appliances: st.kf.appliances }); }
    if (c === 'wardrobe') { project.wardrobe_kind = st.wardrobeKind; Object.assign(features, { door_type: st.doors, storage_priorities: st.storage }); }
    if (c === 'other_furniture') Object.assign(features, { purposes: st.purposes });
    if (c === 'business') { project.business_scope = st.businessScope; Object.assign(features, { object_type: st.bizType.trim() || null, task: st.bizTask.trim() || null, quantity: st.bizQty.trim() || null }); }
    project.features = features;
    return {
      schema_version: S.schema_version, submission_id: st.sid, lead_type: 'project', locale: JQ.lang, hp: $('#hp') ? $('#hp').value : '',
      source: { page: src.page, project_id: st.projectId, utm: src.utm },
      customer: { name: C.name.trim() || null, phone: C.phone, preferred_channel: C.channel, preferred_time: C.time.trim() || null, email: C.email.trim() || null, company: C.company.trim() || null, role: C.role || null },
      project, consent: { project_contact: true, policy_version: CFG.policyVersion || '' },
    };
  }

  async function submit() {
    if (busy) return;
    // финальная проверка всего активного маршрута: нельзя отправить заявку с пропущенными обязательными полями
    for (const n of [1, 2, 3]) {
      const e = check(n);
      if (Object.keys(e).length) { returnTo4 = false; Object.keys(errs).forEach(k => delete errs[k]); Object.assign(errs, e); go(n, { keepErrs: true }); return; }
    }
    Object.keys(errs).forEach(k => delete errs[k]); Object.assign(errs, check(4));
    if (Object.keys(errs).length) { render(); scrollToError(); const f = $('.field.err .inp'); if (f) f.focus({ preventScroll: true }); return; }
    busy = true; sendError = ''; render();
    const payload = buildPayload();
    try {
      const r = await JQ.postJSON('/api/leads', payload);
      if (r.ok && r.data && r.data.lead_id != null) {
        doneNo = r.data.lead_id; JQ.track('request_submitted', { type: 'project', category: st.category, files: payload.project.attachment_ids.length, dimensions_known: payload.project.dimensions_known });
        try { localStorage.removeItem(KEY); sessionStorage.removeItem('jq_contact'); } catch (_) {}
        busy = false; render(); window.scrollTo({ top: 0 }); return;
      }
      if (r.status === 422 && r.data.errors) {
        sendError = t('e.validation', { v: Object.values(r.data.errors).join(' ') });
        JQ.track('request_failed', { type: 'validation' });
      } else { sendError = r.data.message || t('e.server'); JQ.track('request_failed', { type: CFG.demo ? 'demo' : 'server_' + r.status }); }
    } catch (_) { sendError = t('e.network'); JQ.track('request_failed', { type: 'network' }); }
    busy = false; render(); const s = $('#sendErr'); if (s) s.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }

  // ---------------- файлы ----------------
  const uploading = {}; let fk = 0;
  function patchFile(f) { const el = $(`.fl[data-k="${f.key}"]`); if (el) el.outerHTML = fileCard(f); }
  function addFiles(list) {
    const Lm = S.limits; let note = null;
    [...list].forEach(file => {
      const ext = (file.name.split('.').pop() || '').toLowerCase();
      const mime = file.type || ({ jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', pdf: 'application/pdf' })[ext] || '';
      const e = { key: 'f' + (++fk) + Date.now(), name: file.name, size: file.size, mime, status: 'uploading', progress: 0, id: null, file, url: null };
      if (st.files.length >= Lm.max_files) { note = t('e.maxfiles', { n: Lm.max_files }); return; }
      if (!Lm.file_types.includes(mime)) { e.status = 'error'; e.error = t('e.type'); e.file = null; }
      else if (file.size > Lm.max_file_mb * 1048576) { e.status = 'error'; e.error = t('e.size', { mb: Lm.max_file_mb }); e.file = null; }
      else if (mime.startsWith('image/')) e.url = URL.createObjectURL(file);
      st.files.push(e);
      if (e.status === 'uploading') { JQ.track('attachment_added', { type: mime }); upload(e); }
    });
    const box = $('#files'); if (box) box.innerHTML = filesHtml();
    const qf = $('#q-files'); if (qf) { qf.classList.remove('err'); delete errs.files; if (note) { errs.files = note; qf.classList.add('err'); $('.emsg', qf).textContent = note; } }
  }
  function upload(e) {
    e.status = 'uploading'; e.progress = 0; e.error = null;
    const x = new XMLHttpRequest(); uploading[e.key] = x;
    if (CFG.demo) { e.status = 'error'; e.error = t('demo.upload'); e.file = null; patchFile(e); return; }
    x.open('POST', JQ.url('/api/attachments')); x.setRequestHeader('X-File-Name', encodeURIComponent(e.name)); x.setRequestHeader('Content-Type', 'application/octet-stream');
    x.upload.onprogress = ev => { if (ev.lengthComputable) { e.progress = Math.round(ev.loaded / ev.total * 100); const b = $(`.fl[data-k="${e.key}"] .bar i`); if (b) b.style.width = e.progress + '%'; } };
    const fail = m => { e.status = 'error'; e.error = m; delete uploading[e.key]; patchFile(e); };
    x.onload = () => {
      let d = {}; try { d = JSON.parse(x.responseText); } catch (_) {}
      if (x.status === 201 && d.id) { e.id = d.id; e.status = 'ok'; e.mime = d.mime || e.mime; delete uploading[e.key]; patchFile(e); save(); }
      else fail(d.message || t('e.upload'));
    };
    x.onerror = () => fail(t('e.offline'));
    x.send(e.file);
    patchFile(e);
  }
  function wireFiles() {
    const drop = $('#drop'), inp = $('#fileIn'); if (!drop) return;
    drop.onclick = () => inp.click();
    drop.onkeydown = ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); inp.click(); } };
    inp.onchange = () => { addFiles(inp.files); inp.value = ''; };
    ['dragenter', 'dragover'].forEach(ty => drop.addEventListener(ty, ev => { ev.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ty => drop.addEventListener(ty, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', ev => addFiles(ev.dataTransfer.files));
  }

  // ---------------- события ----------------
  const clearErrFor = id => { const root = id.split('.')[0]; delete errs[id]; delete errs[root]; if (id === 'kf') delete errs.kitchen; };
  app.addEventListener('click', e => {
    const o = e.target.closest('.opt,.chip');
    if (o) {
      const f = o.dataset.f, v = o.dataset.v;
      if (o.dataset.m) {
        let a = (getPath(f) || []).slice(), i = a.indexOf(v);
        if (i >= 0) a.splice(i, 1); else { a.push(v); if (f === 'style') a = v === 'undecided' ? ['undecided'] : a.filter(x => x !== 'undecided'); }
        setPath(f, a);
      } else {
        const cur = getPath(f); setPath(f, (cur === v && !o.dataset.r) ? null : v);
      }
      clearErrFor(f); if (f.startsWith('kf.')) { delete errs['kf.' + f.slice(3)]; if (!['upper', 'island', 'appliances'].some(k => hasErr('kf.' + k))) delete errs.kitchen; }
      save(); render(`[data-f="${f}"][data-v="${v}"]`);
      return;
    }
    const a = e.target.closest('[data-act]'); if (!a) return;
    const act = a.dataset.act;
    if (act === 'edit') { returnTo4 = true; go(+a.dataset.step); }
    if (act === 'rmfile') {
      const i = st.files.findIndex(f => f.key === a.dataset.k), f = st.files[i]; if (!f) return;
      if (uploading[f.key]) { uploading[f.key].abort(); delete uploading[f.key]; }
      if (f.url) URL.revokeObjectURL(f.url); st.files.splice(i, 1); save();
      const el = $(`.fl[data-k="${f.key}"]`); if (el) el.remove(); delete errs.files; const qf = $('#q-files'); if (qf) qf.classList.remove('err');
    }
    if (act === 'retry') { const f = st.files.find(x => x.key === a.dataset.k); if (f && f.file) upload(f); }
    if (act === 'again') { doneNo = null; st = fresh(); consent = false; returnTo4 = false; render(null, true); window.scrollTo({ top: 0 }); }
  });
  app.addEventListener('input', e => {
    const tg = e.target;
    if (tg.dataset.bind) {
      if (tg.dataset.bind.startsWith('dims.')) tg.value = tg.value.replace(/[^\d.,]/g, '');
      setPath(tg.dataset.bind, tg.value);
      delete errs[tg.dataset.bind]; if (tg.dataset.bind.startsWith('dims.')) delete errs.dims;
      const fl = tg.closest('.field'); if (fl) fl.classList.remove('err'); const qq = tg.closest('.q'); if (qq && !qq.querySelector('.field.err')) qq.classList.remove('err');
      save();
    } else if (tg.dataset.c) {
      if (tg.dataset.c === 'phone') tg.value = JQ.maskPhone(tg.value);
      C[tg.dataset.c] = tg.value; saveContact(); delete errs['c.' + tg.dataset.c]; const fl = tg.closest('.field'); if (fl) fl.classList.remove('err');
    } else if (tg.id === 'consent') { consent = tg.checked; delete errs.consent; $('#consentErr').classList.remove('show'); }
    else if (tg.dataset.check === 'dimsUnknown') { st.dimsUnknown = tg.checked; Object.keys(errs).filter(k => k.startsWith('dims')).forEach(k => delete errs[k]); save(); render('[data-check="dimsUnknown"]'); }
  });
  app.addEventListener('change', e => { const tg = e.target; if (tg.dataset.c && (tg.type === 'radio' || tg.tagName === 'SELECT')) { C[tg.dataset.c] = tg.value; saveContact(); } });

  $('#next').addEventListener('click', () => {
    if (st.step === 4) return submit();
    if (!validate(st.step)) return;
    JQ.track('step_completed', { step: st.step, category: st.category });
    if (returnTo4) { returnTo4 = false; return go(4); }
    go(st.step + 1);
  });
  $('#back').addEventListener('click', () => { if (returnTo4) { returnTo4 = false; return go(4); } if (st.step > 1) go(st.step - 1); });

  // превью сохранённых файлов после перезагрузки недоступны, но их id и названия остаются
  st.files = st.files.filter(f => f.status === 'ok');
  render();
})();
