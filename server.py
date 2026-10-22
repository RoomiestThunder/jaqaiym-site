#!/usr/bin/env python3
"""JAQAIYM: статика + приём заявок (прототип этапа 3 из ТЗ).

Запуск:  python3 server.py [порт]        (по умолчанию 8123)
Переменные окружения (все необязательны):
  ADMIN_TOKEN          токен для /admin (иначе генерируется и хранится в data/admin_token.txt)
  DATA_DIR             папка для базы и файлов (по умолчанию ./data; на хостинге — смонтированный том)
  PORT                 порт (хостинги задают его сами)
  TELEGRAM_BOT_TOKEN   токен бота для уведомлений
  TELEGRAM_CHAT_ID     чат, куда слать заявки
  PUBLIC_BASE_URL      адрес сайта для ссылок в уведомлениях

Без Telegram уведомления пишутся в data/outbox.log (тестовый канал).
Только стандартная библиотека Python.
"""
import http.server, socketserver, json, os, re, sqlite3, secrets, threading, time, uuid
import urllib.parse, urllib.request, sys, html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(ROOT, 'public')
DATA = os.environ.get('DATA_DIR') or os.path.join(ROOT, 'data')   # на хостинге укажите путь к постоянному тому
UPLOADS = os.path.join(DATA, 'uploads')
os.makedirs(UPLOADS, exist_ok=True)

SCHEMA = json.load(open(os.path.join(PUBLIC, 'schema.json'), encoding='utf-8'))
from render import LANGS, PAGES, split_lang, render_page as _render

def render_page(fname, lang, route):
    return _render(PUBLIC, fname, lang, route)


# ---------------- вспомогательное ----------------
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

_rate = {}
def rate_ok(ip, bucket, limit, window=600):
    t = time.time(); key = (ip, bucket)
    q = [x for x in _rate.get(key, []) if t - x < window]
    if len(q) >= limit: _rate[key] = q; return False
    q.append(t); _rate[key] = q; return True

def norm_phone(raw):
    d = re.sub(r'\D', '', str(raw or ''))
    if len(d) == 11 and d[0] in '78': d = '7' + d[1:]
    elif len(d) == 10: d = '7' + d
    return '+' + d if len(d) == 11 and d[0] == '7' else None

def sniff(head):
    if head[:3] == b'\xff\xd8\xff': return 'image/jpeg'
    if head[:8] == b'\x89PNG\r\n\x1a\n': return 'image/png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP': return 'image/webp'
    if head[:5] == b'%PDF-': return 'application/pdf'
    return None

def lab(group, key):
    return SCHEMA.get(group, {}).get(key, key)

def make_summary(p):
    """Короткая карточка для команды: без кодов и технических полей."""
    if p['lead_type'] == 'quick':
        q = p.get('quick', {})
        s = 'Быстрая заявка: %s' % lab('quick_type', q.get('request_type'))
        if q.get('message'): s += '; сообщение: %s' % q['message'][:300]
        return s
    pr = p['project']; f = pr.get('features', {}) or {}; parts = [lab('category', pr['category'])]
    if pr.get('premise'): parts.append(lab('premise', pr['premise']).lower())
    parts.append(lab('city', pr.get('city')))
    if pr.get('layout'): parts.append(lab('kitchen_layout', pr['layout']).lower())
    if pr.get('wardrobe_kind'): parts.append(lab('wardrobe_kind', pr['wardrobe_kind']).lower())
    if pr.get('business_scope'): parts.append(lab('business_scope', pr['business_scope']).lower())
    if pr.get('style_preferences'): parts.append('стиль: ' + ', '.join(lab('style', s).lower() for s in pr['style_preferences']))
    if pr['category'] == 'kitchen':
        for k, t in (('upper_cabinets', 'верхние шкафы'), ('island', 'остров'), ('built_in_appliances', 'встроенная техника')):
            v = f.get(k)
            if v == 'yes': parts.append(t)
            elif v == 'no': parts.append('без: ' + t)
    if f.get('door_type'): parts.append('двери: ' + ', '.join(lab('doors', x).lower() for x in f['door_type']))
    if f.get('storage_priorities'): parts.append('важно: ' + ', '.join(lab('storage', x).lower() for x in f['storage_priorities']))
    if f.get('purposes'): parts.append('назначение: ' + ', '.join(lab('purpose', x).lower() for x in f['purposes']))
    if f.get('object_type'): parts.append('объект: ' + f['object_type'])
    if f.get('task'): parts.append('задача: ' + f['task'])
    if f.get('quantity'): parts.append('количество: ' + f['quantity'])
    dm = pr.get('dimensions_mm')
    if pr.get('dimensions_known') and dm:
        names = {'a': 'A', 'b': 'B', 'c': 'C', 'width': 'ширина', 'height': 'высота', 'depth': 'глубина'}
        parts.append('размеры, см: ' + ', '.join('%s %s' % (names.get(k, k), round(v / 10)) for k, v in dm.items() if v))
    else:
        parts.append('размеры неизвестны, нужен замер')
    n = len(pr.get('attachment_ids') or [])
    parts.append('фото/файлы: %d' % n if n else 'файлы не приложены')
    if pr.get('budget_range'): parts.append('бюджет: ' + lab('budget', pr['budget_range']))
    if pr.get('timeframe'): parts.append('срок: ' + lab('timeframe', pr['timeframe']).lower())
    if pr.get('description'): parts.append('примечание: ' + pr['description'][:500])
    return '; '.join(parts)

def validate(d):
    """Возвращает (ошибки, нормализованный payload)."""
    err = {}
    if not isinstance(d, dict): return {'_': 'Некорректный запрос'}, None
    if d.get('schema_version') != SCHEMA['schema_version']: err['schema_version'] = 'Неподдерживаемая версия формы. Обновите страницу.'
    sid = str(d.get('submission_id') or '')
    if not re.fullmatch(r'[0-9a-fA-F-]{16,64}', sid): err['submission_id'] = 'Некорректный идентификатор заявки'
    lt = d.get('lead_type')
    if lt not in ('project', 'quick'): err['lead_type'] = 'Некорректный тип заявки'
    c = d.get('customer') or {}
    phone = norm_phone(c.get('phone'))
    if not phone: err['customer.phone'] = 'Укажите номер телефона Казахстана, например +7 700 000 00 00'
    if not (d.get('consent') or {}).get('project_contact') is True: err['consent'] = 'Нужно согласие на обработку данных'
    if lt == 'project' and not str(c.get('name') or '').strip(): err['customer.name'] = 'Укажите имя'
    clean = {
        'schema_version': 1, 'submission_id': sid, 'lead_type': lt, 'locale': d.get('locale') if d.get('locale') in LANGS else 'ru',
        'source': {k: (v if isinstance(v, (dict, type(None))) else str(v)[:300]) for k, v in (d.get('source') or {}).items() if k in ('page', 'project_id', 'utm', 'from')},
        'customer': {
            'name': str(c.get('name') or '')[:100] or None, 'phone': phone,
            'preferred_channel': c.get('preferred_channel') if c.get('preferred_channel') in SCHEMA['channel'] else None,
            'preferred_time': str(c.get('preferred_time') or '')[:100] or None,
            'email': str(c.get('email') or '')[:150] or None,
            'company': str(c.get('company') or '')[:150] or None,
            'role': c.get('role') if c.get('role') in SCHEMA['role'] else None},
        'consent': {'project_contact': True, 'policy_version': str((d.get('consent') or {}).get('policy_version') or '')[:40]},
    }
    if clean['customer']['email'] and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', clean['customer']['email']):
        err['customer.email'] = 'Проверьте адрес электронной почты'
    if lt == 'quick':
        q = d.get('quick') or {}
        if q.get('request_type') not in SCHEMA['quick_type']: err['quick.request_type'] = 'Выберите, чем помочь'
        clean['quick'] = {'request_type': q.get('request_type'), 'message': str(q.get('message') or '')[:1000] or None, 'context': str(q.get('context') or '')[:200] or None}
    elif lt == 'project':
        p = d.get('project') or {}
        if p.get('category') not in SCHEMA['category']: err['project.category'] = 'Выберите, что хотите сделать'
        if p.get('city') not in SCHEMA['city']: err['project.city'] = 'Выберите город'
        keep = ['category', 'premise', 'city', 'layout', 'wardrobe_kind', 'business_scope', 'style_preferences', 'style_note',
                'features', 'dimensions_known', 'dimensions_mm', 'budget_range', 'timeframe', 'description', 'attachment_ids']
        pr = {k: p.get(k) for k in keep if k in p}
        for k, g in (('premise', 'premise'), ('layout', 'kitchen_layout'), ('wardrobe_kind', 'wardrobe_kind'),
                     ('business_scope', 'business_scope'), ('budget_range', 'budget'), ('timeframe', 'timeframe')):
            if pr.get(k) is not None and pr[k] not in SCHEMA[g]: err['project.' + k] = 'Недопустимое значение'
        pr['style_preferences'] = [s for s in (pr.get('style_preferences') or []) if s in SCHEMA['style']]
        if pr.get('dimensions_known') and isinstance(pr.get('dimensions_mm'), dict):
            dm = {}
            for k, v in pr['dimensions_mm'].items():
                if v in (None, ''): continue
                try: v = int(v)
                except Exception: err['project.dimensions_mm.' + k] = 'Размер должен быть числом'; continue
                if not 100 <= v <= 30000: err['project.dimensions_mm.' + k] = 'Размер вне допустимых пределов'
                dm[str(k)[:20]] = v
            pr['dimensions_mm'] = dm or None
            pr['dimensions_known'] = bool(dm)
        else:
            pr['dimensions_mm'] = None; pr['dimensions_known'] = False
        pr['description'] = str(pr.get('description') or '')[:2000] or None
        pr['style_note'] = str(pr.get('style_note') or '')[:500] or None
        ids = pr.get('attachment_ids') or []
        if not isinstance(ids, list) or len(ids) > LIM['max_files']: err['project.attachment_ids'] = 'Слишком много файлов'; ids = []
        pr['attachment_ids'] = [str(i) for i in ids]
        f = pr.get('features') if isinstance(pr.get('features'), dict) else {}
        pr['features'] = {str(k)[:40]: (v if isinstance(v, (list, str, int, type(None))) else None) for k, v in f.items()}
        for k in ('object_type', 'task', 'quantity'):
            if isinstance(pr['features'].get(k), str): pr['features'][k] = pr['features'][k][:500].strip() or None
        for k, g in (('door_type', 'doors'), ('storage_priorities', 'storage'), ('purposes', 'purpose')):
            v = pr['features'].get(k)
            if v is not None: pr['features'][k] = [x for x in (v if isinstance(v, list) else []) if x in SCHEMA[g]]
        if p.get('category') in SCHEMA['category']: err.update(required_project_fields(pr, p['category']))
        clean['project'] = pr
    return err, clean

def required_project_fields(pr, cat):
    """Без этих ответов заявка «полупустая»: те же правила проверяет анкета на фронтенде."""
    e, f = {}, pr.get('features') or {}
    def need(key, ok, msg):
        if not ok: e['project.' + key] = msg
    need('premise', pr.get('premise') in SCHEMA['premise'], 'Укажите, где будет стоять мебель')
    need('style_preferences', bool(pr.get('style_preferences')), 'Выберите внешний вид')
    if cat == 'kitchen':
        need('layout', pr.get('layout') in SCHEMA['kitchen_layout'], 'Укажите планировку кухни')
        for k in ('upper_cabinets', 'island', 'built_in_appliances'): need('features.' + k, f.get(k) in SCHEMA['yes_no'], 'Ответьте про ' + k)
    elif cat == 'wardrobe':
        need('wardrobe_kind', pr.get('wardrobe_kind') in SCHEMA['wardrobe_kind'], 'Укажите, какой шкаф нужен')
        need('features.door_type', bool(f.get('door_type')), 'Выберите тип дверей')
        need('features.storage_priorities', bool(f.get('storage_priorities')), 'Выберите, что хранить внутри')
    elif cat == 'other_furniture':
        need('features.purposes', bool(f.get('purposes')), 'Укажите назначение мебели')
    elif cat == 'business':
        need('business_scope', pr.get('business_scope') in SCHEMA['business_scope'], 'Укажите, сколько объектов')
        need('features.object_type', bool(f.get('object_type')), 'Укажите тип объекта')
        need('features.task', bool(f.get('task')), 'Опишите задачу')
        need('features.quantity', bool(f.get('quantity')), 'Укажите количество')
    else:
        need('description', len(str(pr.get('description') or '').strip()) >= 5, 'Опишите, что вы хотите сделать')
    return e

def create_lead(clean):
    with db_lock:
        row = db.execute('SELECT id FROM leads WHERE submission_id=?', (clean['submission_id'],)).fetchone()
        if row: return row['id'], True
        ids = (clean.get('project') or {}).get('attachment_ids') or []
        for a in ids:
            r = db.execute('SELECT lead_id FROM attachments WHERE id=?', (a,)).fetchone()
            if not r or r['lead_id'] is not None: raise ValueError('Файл не найден или уже прикреплён: повторите загрузку')
        summary = make_summary(clean)
        cur = db.execute('INSERT INTO leads(submission_id,lead_type,status,created_at,payload,summary,phone) VALUES(?,?,?,?,?,?,?)',
                         (clean['submission_id'], clean['lead_type'], 'new', now(), json.dumps(clean, ensure_ascii=False), summary, clean['customer']['phone']))
        lid = cur.lastrowid
        for a in ids: db.execute('UPDATE attachments SET lead_id=? WHERE id=?', (lid, a))
        db.commit()
        return lid, False

# ---------------- уведомления ----------------
def notify(lead_id):
    with db_lock:
        r = db.execute('SELECT * FROM leads WHERE id=?', (lead_id,)).fetchone()
    if not r or r['notified']: return
    p = json.loads(r['payload']); c = p['customer']
    head = 'Новая заявка №%d (%s)' % (r['id'], 'быстрая' if r['lead_type'] == 'quick' else 'проект')
    text = '%s\n%s\n\nКонтакт: %s %s (%s)\nИсточник: %s\nКарточка: %s/admin?token=%s#lead-%d' % (
        head, r['summary'], c.get('name') or '—', c['phone'], lab('channel', c.get('preferred_channel')) if c.get('preferred_channel') else 'способ не указан',
        (p.get('source') or {}).get('page') or '—', BASE_URL, ADMIN_TOKEN, r['id'])
    bot, chat = os.environ.get('TELEGRAM_BOT_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
    ok, error = False, None
    try:
        if bot and chat:
            req = urllib.request.Request('https://api.telegram.org/bot%s/sendMessage' % bot,
                                         data=json.dumps({'chat_id': chat, 'text': text}).encode(), headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=10).read(); ok = True
        else:
            with open(os.path.join(DATA, 'outbox.log'), 'a', encoding='utf-8') as f:
                f.write('--- %s ---\n%s\n\n' % (now(), text))
            ok = True
    except Exception as e:
        error = str(e)[:300]
    with db_lock:
        db.execute('UPDATE leads SET notified=?, notify_attempts=notify_attempts+1, notify_error=? WHERE id=?', (1 if ok else 0, error, lead_id))
        db.commit()

def retry_loop():
    while True:
        time.sleep(60)
        with db_lock:
            ids = [r['id'] for r in db.execute('SELECT id FROM leads WHERE notified=0 AND notify_attempts<20')]
        for i in ids: notify(i)
threading.Thread(target=retry_loop, daemon=True).start()

# ---------------- HTTP ----------------
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=PUBLIC, **k)
    def log_message(self, fmt, *a): sys.stderr.write('%s %s\n' % (self.address_string(), fmt % a))
    def ip(self): return self.headers.get('X-Forwarded-For', self.client_address[0]).split(',')[0].strip()
    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff'); self.send_header('Referrer-Policy', 'same-origin')
        if self.path.startswith('/api') or self.path.startswith('/admin'): self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def send_json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)

    def authed(self, q): return secrets.compare_digest(q.get('token', [''])[0], ADMIN_TOKEN)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path); q = urllib.parse.parse_qs(u.query)
        lang, route = split_lang(u.path)
        if route in PAGES and not u.path.startswith('/api'):
            body = render_page(PAGES[route], lang, route)
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache'); self.end_headers(); self.wfile.write(body); return
        if lang == 'kk' and not u.path.startswith('/api') and u.path != '/admin':
            self.path = route + (('?' + u.query) if u.query else '')
        if u.path == '/api/health': return self.send_json(200, {'ok': True})
        if u.path == '/admin': return self.admin_page(q)
        if u.path == '/api/admin/leads':
            if not self.authed(q): return self.send_json(403, {'error': 'forbidden'})
            return self.send_json(200, {'leads': self.rows()})
        m = re.fullmatch(r'/api/files/([0-9a-f]{32})', u.path)
        if m:
            if not self.authed(q): return self.send_json(403, {'error': 'forbidden'})
            with db_lock: r = db.execute('SELECT * FROM attachments WHERE id=?', (m.group(1),)).fetchone()
            if not r: return self.send_json(404, {'error': 'not_found'})
            data = open(r['path'], 'rb').read()
            self.send_response(200); self.send_header('Content-Type', r['mime'])
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Disposition', "inline; filename*=UTF-8''" + urllib.parse.quote(r['filename'] or 'file'))
            self.end_headers(); self.wfile.write(data); return
        if u.path.startswith('/api/'): return self.send_json(404, {'error': 'not_found'})
        return super().do_GET()

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path); q = urllib.parse.parse_qs(u.query)
        try: n = int(self.headers.get('Content-Length') or 0)
        except ValueError: n = 0
        if u.path == '/api/attachments': return self.upload(n)
        if u.path == '/api/leads': return self.leads(n)
        m = re.fullmatch(r'/api/admin/leads/(\d+)/status', u.path)
        if m:
            if not self.authed(q): return self.send_json(403, {'error': 'forbidden'})
            st = (json.loads(self.rfile.read(min(n, 1000)) or b'{}')).get('status')
            if st not in SCHEMA['status']: return self.send_json(422, {'error': 'bad_status'})
            with db_lock: db.execute('UPDATE leads SET status=? WHERE id=?', (st, int(m.group(1)))); db.commit()
            return self.send_json(200, {'ok': True})
        self.send_json(404, {'error': 'not_found'})

    def leads(self, n):
        if n <= 0 or n > MAX_JSON: return self.send_json(413, {'error': 'too_large'})
        if not rate_ok(self.ip(), 'lead', 12): return self.send_json(429, {'error': 'rate_limited', 'message': 'Слишком много попыток. Попробуйте позже.'})
        try: d = json.loads(self.rfile.read(n))
        except Exception: return self.send_json(400, {'error': 'bad_json'})
        if isinstance(d, dict) and str(d.get('hp') or '').strip():      # антиспам-приманка: тихо отбрасываем
            return self.send_json(201, {'ok': True, 'lead_id': 0})
        err, clean = validate(d)
        if err: return self.send_json(422, {'error': 'validation', 'errors': err})
        try: lid, dup = create_lead(clean)
        except ValueError as e: return self.send_json(422, {'error': 'validation', 'errors': {'project.attachment_ids': str(e)}})
        except Exception as e:
            sys.stderr.write('LEAD SAVE ERROR %r\n' % e); return self.send_json(500, {'error': 'save_failed'})
        if not dup: threading.Thread(target=notify, args=(lid,), daemon=True).start()
        self.send_json(200 if dup else 201, {'ok': True, 'lead_id': lid, 'duplicate': dup})

    def upload(self, n):
        if n <= 0: return self.send_json(400, {'error': 'empty'})
        if n > MAX_FILE: return self.send_json(413, {'error': 'too_large', 'message': 'Файл больше %d МБ' % LIM['max_file_mb']})
        if not rate_ok(self.ip(), 'upload', 40): return self.send_json(429, {'error': 'rate_limited', 'message': 'Слишком много загрузок. Попробуйте позже.'})
        body = self.rfile.read(n)
        mime = sniff(body[:16])
        if mime not in LIM['file_types']: return self.send_json(415, {'error': 'bad_type', 'message': 'Допустимы JPG, PNG, WebP и PDF'})
        fid = uuid.uuid4().hex
        name = urllib.parse.unquote(self.headers.get('X-File-Name') or 'file')[:120]
        path = os.path.join(UPLOADS, fid)
        open(path, 'wb').write(body)
        with db_lock:
            db.execute('INSERT INTO attachments(id,filename,mime,size,path,created_at) VALUES(?,?,?,?,?,?)', (fid, name, mime, n, path, now())); db.commit()
        self.send_json(201, {'id': fid, 'name': name, 'size': n, 'mime': mime})

    def rows(self):
        with db_lock:
            leads = [dict(r) for r in db.execute('SELECT * FROM leads ORDER BY id DESC LIMIT 500')]
            att = [dict(r) for r in db.execute('SELECT id,filename,mime,size,lead_id FROM attachments WHERE lead_id IS NOT NULL')]
        for l in leads:
            l['payload'] = json.loads(l['payload']); l['files'] = [a for a in att if a['lead_id'] == l['id']]
        return leads

    def admin_page(self, q):
        if not self.authed(q):
            b = '<meta charset=utf-8><body style="font:16px sans-serif;padding:40px">Нужен токен: /admin?token=...</body>'.encode()
            self.send_response(403); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b); return
        tok = urllib.parse.quote(ADMIN_TOKEN); cards = []
        for l in self.rows():
            c = l['payload']['customer']; src = l['payload'].get('source') or {}
            files = ''.join('<a href="/api/files/%s?token=%s" target="_blank">%s</a>' % (f['id'], tok, html.escape(f['filename'] or 'файл')) for f in l['files']) or '<i>файлов нет</i>'
            opts = ''.join('<option value="%s"%s>%s</option>' % (k, ' selected' if k == l['status'] else '', v) for k, v in SCHEMA['status'].items())
            cards.append('''<article id="lead-%d"><header><b>№%d</b> <span class="t">%s</span><span class="tag">%s</span>
<select onchange="fetch('/api/admin/leads/%d/status?token=%s',{method:'POST',body:JSON.stringify({status:this.value})})">%s</select></header>
<p class="s">%s</p><p><b>%s</b> · <a href="tel:%s">%s</a> · %s%s</p><p class="f">%s</p><p class="m">Источник: %s %s · уведомление: %s</p></article>''' % (
                l['id'], l['id'], l['created_at'].replace('T', ' ')[:16], 'быстрая' if l['lead_type'] == 'quick' else 'проект', l['id'], tok, opts,
                html.escape(l['summary']), html.escape(c.get('name') or '—'), c['phone'], c['phone'],
                html.escape(lab('channel', c.get('preferred_channel')) if c.get('preferred_channel') else 'способ не указан'),
                (' · удобно: ' + html.escape(c['preferred_time'])) if c.get('preferred_time') else '', files,
                html.escape(str(src.get('page') or '—')), html.escape(str(src.get('project_id') or '')),
                'доставлено' if l['notified'] else 'НЕ доставлено (%s)' % html.escape(l['notify_error'] or 'ожидает')))
        page = '''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Заявки JAQAIYM</title>
<style>body{font:15px/1.5 system-ui,sans-serif;background:#f5efe3;color:#2e1a10;margin:0;padding:24px;max-width:860px;margin:auto}
h1{font-size:22px}article{background:#fff;border-radius:14px;padding:18px 20px;margin:14px 0;box-shadow:0 1px 0 #0001}article:target{outline:2px solid #b65c37}
header{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.t{color:#8a7a6c}.tag{background:#eadfce;border-radius:99px;padding:2px 10px;font-size:12px}select{margin-left:auto;padding:6px}
.s{font-size:16px}.f a{display:inline-block;margin:0 10px 6px 0;background:#f5efe3;padding:4px 10px;border-radius:8px;color:#2e1a10}.m{color:#8a7a6c;font-size:13px}</style>
<h1>Заявки (%d)</h1>%s''' % (len(cards), ''.join(cards) or '<p>Заявок пока нет.</p>')
        b = page.encode(); self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)

class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True

if __name__ == '__main__':
    print('JAQAIYM: http://localhost:%d   админка: http://localhost:%d/admin?token=%s' % (PORT, PORT, ADMIN_TOKEN), flush=True)
    S(('', PORT), H).serve_forever()
