#!/usr/bin/env python3
"""Проверки безопасности PHP-версии: тест ведёт себя как нападающий, а не как довольный пользователь.

  python3 tools/test_php_security.py

  1 админка закрыта без входа, подделка и просрочка cookie, старый вход «токеном в адресе» не работает
  2 вход: неверный пароль, перебор (блокировка), флаги cookie, отключённая и слабая админка
  3 защита от подделки запросов (CSRF + Origin)
  4 загрузки: чужие типы, имена с путями и переводами строк, размер, лимит частоты, права на файлы
  5 приём заявок: кривые типы вместо 500, SQL-инъекции, XSS в админке, подделка строк в Telegram, приманка, повторы
  6 вебхук Telegram: секрет, мусорные обновления, перебор кода подписки
  7 утечки: секретные адреса, заголовки, токен бота в ответах и ошибках
  8 срок хранения, IP только в виде хеша, права на файлы базы
  9 статические страницы: CSP покрывает все встроенные скрипты; .htaccess; определение IP за прокси
"""
import base64, hashlib, hmac, json, os, re, sqlite3, stat, subprocess, sys, threading, time, uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import php_harness as H  # noqa: E402

T = H.T
check, wait, sent, Mock = T.check, T.wait, T.sent, T.Mock
BOT = 'SECRETBOT-TOKEN-XYZ'
PNG = lambda: b'\x89PNG\r\n\x1a\n' + os.urandom(100)
JSON = {'Content-Type': 'application/json'}


def payload(**custom):
    p = {'schema_version': 1, 'submission_id': str(uuid.uuid4()), 'lead_type': 'project', 'locale': 'ru',
         'customer': {'name': 'Тест', 'phone': '+77001234567', 'preferred_channel': 'whatsapp'}, 'consent': {'project_contact': True}, 'source': {'page': '/test'},
         'project': {'category': 'wardrobe', 'city': 'almaty', 'premise': 'apartment', 'wardrobe_kind': 'niche', 'style_preferences': ['light'],
                     'features': {'door_type': ['swing'], 'storage_priorities': ['drawers']}, 'dimensions_known': False, 'attachment_ids': []}}
    p.update(custom)
    return p


def post_lead(S, p, **headers):
    return S.req('/api/leads', json.dumps(p).encode(), dict(JSON, **headers))


def inline_handlers(html):
    """Атрибуты onclick/onerror/... в настоящих тегах (экранированный текст &lt;img onerror=...&gt; не считается)."""
    found = []
    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            found.extend('%s[%s]' % (tag, k) for k, _ in attrs if k.lower().startswith('on'))
    P().feed(html)
    return found


def php_errors(S):
    path = os.path.join(S.dir, 'php-error.log')
    text = open(path).read() if os.path.exists(path) else ''
    return [l for l in text.splitlines() if re.search(r'Warning|Fatal|Deprecated|Uncaught|Notice|TypeError', l)]


def forge_cookie(admin, bot, exp, name='jq_admin'):
    """Подпись cookie по тем же правилам, что в Auth.php (проверяет и просрочку, и подмену)."""
    key = hmac.new((admin + '|' + bot).encode(), b'session', hashlib.sha256).hexdigest()
    sig = base64.urlsafe_b64encode(hmac.new(key.encode(), ('s|%d' % exp).encode(), hashlib.sha256).digest()).rstrip(b'=').decode()
    return '%s=%d.%s' % (name, exp, sig)


def php_ip(remote, xff='', real='', server=''):
    boot = os.path.join(H.dist(), 'jaqaiym-private', 'src', 'bootstrap.php')
    code = ('require %s; $_SERVER["REMOTE_ADDR"]=$argv[1]; if($argv[2]!=="")$_SERVER["HTTP_X_FORWARDED_FOR"]=$argv[2]; '
            'if($argv[3]!=="")$_SERVER["HTTP_X_REAL_IP"]=$argv[3]; if($argv[4]!=="")$_SERVER["SERVER_ADDR"]=$argv[4]; echo \\Jq\\Http::ip();') % json.dumps(boot)
    return subprocess.run(['php', '-r', code, '--', remote, xff, real, server], capture_output=True, text=True).stdout.strip()


def section_admin_closed(A):
    print('1. админка закрыта без входа')
    A.lead()
    seen = {'GET /api/admin/leads': A.req('/api/admin/leads')[0], 'GET /api/files/<id>': A.req('/api/files/' + 'a' * 32)[0],
            'GET /api/admin/leads?token=<пароль>': A.req('/api/admin/leads?token=' + H.ADMIN)[0]}
    for label, st in seen.items():
        check(st == 403, '%s без входа = 403' % label)
    for path in ('/api/admin/leads/1/status', '/api/admin/leads/1/resend', '/api/admin/subscribers/1/remove', '/api/admin/webhook/set', '/admin/logout'):
        check(A.req(path, b'{}', JSON)[0] == 403, 'POST %s без входа = 403' % path)
    for url in ('/admin', '/admin?token=' + H.ADMIN):
        st, _, body = A.raw('GET', url)
        check(st == 200 and 'Пароль' in body.decode() and 'Заявки (' not in body.decode() and '+77001234567' not in body.decode(), 'страница %s показывает только форму входа' % url.split('?')[0])
    now = int(time.time())
    good = forge_cookie(H.ADMIN, BOT, now + 600)
    check(A.raw('GET', '/api/admin/leads', headers={'Cookie': good})[0] == 200, 'cookie, подписанная по правилам приложения, принимается (проверка самого теста)')
    for label, cookie in (('просроченная', forge_cookie(H.ADMIN, BOT, now - 5)), ('с подменённой датой', good.replace('=%d' % (now + 600), '=%d' % (now + 99999), 1)),
                          ('чужой подписью', forge_cookie('another-admin-password-xyz', BOT, now + 600)), ('мусорная', 'jq_admin=abc'), ('пустая', 'jq_admin=')):
        check(A.raw('GET', '/api/admin/leads', headers={'Cookie': cookie})[0] == 403, 'cookie %s отвергается' % label)


def section_login(A, B, C, D):
    print('2. вход')
    st, cookie, header = A.login('wrong-password')
    check(st == 401 and not cookie, 'неверный пароль: 401 и cookie не выдаётся')
    st, cookie, header = A.login()
    low = header.lower()
    check(st == 303 and cookie and 'httponly' in low and 'samesite=lax' in low and 'secure' not in low, 'cookie: HttpOnly, SameSite=Lax (по http без Secure)')
    check(A.raw('GET', '/admin/login?password=' + H.ADMIN)[0] == 404, 'пароль в адресе (GET) не принимается')
    st, _, _ = A.raw('POST', '/admin/login', 'password=' + H.ADMIN, {'Content-Type': 'application/x-www-form-urlencoded', 'Origin': 'https://evil.example'})
    check(st == 403, 'вход с чужим Origin отклонён')
    st, cookie, header = D.login()
    low = header.lower()
    check(st == 303 and header.startswith('__Host-jq_admin=') and 'secure' in low and 'httponly' in low and 'path=/' in low and 'domain' not in low, 'на https: имя __Host-, Secure, HttpOnly, Path=/, без Domain')
    codes = [B.login('wrong-%d' % i)[0] for i in range(8)]
    check(codes == [401] * 8, 'первые 8 неверных попыток получают 401')
    check(B.login('wrong-9')[0] == 429, '9-я попытка блокируется (429)')
    check(B.login()[0] == 429, 'во время блокировки не пускает даже с верным паролем')
    st, _, body = C.raw('GET', '/admin')
    check(st == 503 and 'отключена' in body.decode(), 'слабый пароль (короче 16): админка отключена, 503')
    check(C.login('short')[0] == 503 and C.req('/api/admin/leads')[0] == 403, 'и войти нельзя даже с этим паролем')


def section_csrf(A):
    print('3. подделка запросов (CSRF)')
    lid = A.lead()
    cookie, csrf = A.session()
    path = '/api/admin/leads/%d/status' % lid
    body = {'status': 'contacted'}
    check(A.admin_post(path, cookie, None, body)[0] == 403, 'без CSRF-токена: 403')
    check(A.admin_post(path, cookie, 'f' * 64, body)[0] == 403, 'с чужим CSRF-токеном: 403')
    check(A.admin_post(path, cookie, csrf, body, Origin='https://evil.example')[0] == 403, 'верный токен, но чужой Origin: 403')
    check(A.admin_post(path, cookie, csrf, body, Origin='https://roomiestthunder.github.io')[0] == 403, 'Origin из списка CORS для админки не годится: 403')
    check(A.sql('SELECT status FROM leads WHERE id=?', lid)[0]['status'] == 'new', 'при отказах статус не изменился')
    check(A.admin_post(path, cookie, csrf, body)[0] == 200 and A.sql('SELECT status FROM leads WHERE id=?', lid)[0]['status'] == 'contacted', 'с верным токеном статус меняется')
    check(A.admin_post(path, cookie, csrf, {'status': "x'; DROP TABLE leads;--"})[0] == 422, 'недопустимый статус: 422')
    check(A.admin_post(path, cookie, csrf, {'status': ['won']})[0] == 422, 'статус не строкой: 422')
    return cookie, csrf


def section_uploads(A, B):
    print('4. загрузки')
    for label, body in (('HTML с <script>', b'<html><script>alert(1)</script></html>'), ('PHP-код', b'<?php system($_GET[0]); ?>'),
                        ('SVG со скриптом', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'), ('исполняемый файл', b'MZ\x90\x00' + os.urandom(50)),
                        ('GIF', b'GIF89a' + os.urandom(50))):
        check(A.upload('evil.png', body)[0] == 415, '%s под видом png отклонён (415)' % label)
    check(A.req('/api/attachments', b'', {'X-File-Name': 'a.png'})[0] in (400, 411), 'пустое тело отклонено')
    st, d = A.upload('..%2F..%2Fetc%2Fpasswd.png', PNG())
    check(st == 201 and '/' not in d['name'] and '\\' not in d['name'], 'имя с ../ очищено от слэшей: %r' % d.get('name'))
    check(sorted(os.listdir(os.path.join(A.dir, 'uploads')))[-1:] and all(re.fullmatch(r'[0-9a-f]{32}', n) for n in os.listdir(os.path.join(A.dir, 'uploads'))), 'на диске файлы лежат под случайными именами, без имён клиента')
    st, d = A.upload('a%0d%0aX-Evil: 1%00.png', PNG())
    check(st == 201 and not re.search(r'[\r\n\x00]', d['name']), 'имя с переводом строки и нулём очищено')
    st, d = A.upload('я' * 5000, PNG())
    check(st == 201 and len(d['name']) <= 120, 'длинное имя обрезано до 120')
    big = b'\x89PNG\r\n\x1a\n' + os.urandom(10 * 1024 * 1024)
    try:
        st = A.upload('big.png', big)[0]
    except Exception:
        st = 'разрыв соединения'
    check(st in (413, 'разрыв соединения'), 'файл больше 10 МБ отклонён (%s)' % st)
    upl = os.path.join(A.dir, 'uploads')
    names = [n for n in os.listdir(upl) if not n.endswith('.part')]
    check(all(stat.S_IMODE(os.stat(os.path.join(upl, n)).st_mode) == 0o600 for n in names), 'файлы на диске доступны только владельцу (0600)')
    check(stat.S_IMODE(os.stat(upl).st_mode) == 0o700 and stat.S_IMODE(os.stat(os.path.join(A.dir, 'leads.db')).st_mode) == 0o600, 'папка загрузок 0700, база 0600')
    check(not [n for n in os.listdir(upl) if n.endswith('.part')], 'недокачанных временных файлов нет')
    codes = [B.upload('p.png', PNG())[0] for _ in range(41)]
    check(codes[:40] == [201] * 40 and codes[40] == 429, 'лимит загрузок: 40 проходят, 41-я = 429')
    check(B.req('/api/attachments', PNG(), {'Origin': 'https://evil.example'})[0] == 403, 'загрузка с чужого Origin отклонена')


def section_leads(A, F, B):
    print('5. приём заявок')
    base = payload()
    cases = []
    def m(label, fn):
        import copy
        c = copy.deepcopy(base); fn(c); cases.append((label, c))
    m('customer строкой', lambda c: c.update(customer='x')); m('customer списком', lambda c: c.update(customer=[1, 2]))
    m('project списком', lambda c: c.update(project=[1])); m('project строкой', lambda c: c.update(project='x'))
    m('features списком словарей', lambda c: c['project'].update(features=[{'a': 1}]))
    m('features вложенные', lambda c: c['project'].update(features={'door_type': [[1], [{'a': 1}]], 'storage_priorities': {'a': 1}, 'x': {'y': {'z': 1}}}))
    m('style словарём', lambda c: c['project'].update(style_preferences={'light': 1})); m('style мусором', lambda c: c['project'].update(style_preferences=[['light'], {'a': 1}, None, 5]))
    m('attachment_ids словарём', lambda c: c['project'].update(attachment_ids={'a': 'b'})); m('attachment_ids путь', lambda c: c['project'].update(attachment_ids=['../../etc/passwd']))
    m('attachment_ids чужой', lambda c: c['project'].update(attachment_ids=['0' * 32]))
    m('размеры мусором', lambda c: c['project'].update(dimensions_known=True, dimensions_mm={'a': 'abc', 'b': [1], 'c': {'d': 1}, 'width': 1e30}))
    m('размер-гигант', lambda c: c['project'].update(dimensions_known=True, dimensions_mm={'a': 10 ** 30}))
    m('premise списком', lambda c: c['project'].update(premise=['apartment'])); m('phone списком', lambda c: c['customer'].update(phone=['+77001234567']))
    m('phone 100 КБ', lambda c: c['customer'].update(phone='9' * 100000)); m('name словарём', lambda c: c['customer'].update(name={'a': 1}))
    m('consent строкой', lambda c: c.update(consent='yes')); m('source списком', lambda c: c.update(source=['x']))
    m('source глубокий', lambda c: c.update(source={'utm': {'a': {'b': {'c': 1}}}, 'page': ['x']})); m('locale словарём', lambda c: c.update(locale={'a': 1}))
    m('lead_type списком', lambda c: c.update(lead_type=['project'])); m('schema_version строкой', lambda c: c.update(schema_version='1'))
    m('submission_id списком', lambda c: c.update(submission_id=['x'])); m('quick строкой', lambda c: c.update(lead_type='quick', quick='x'))
    m('hp списком', lambda c: c.update(hp=['x'])); m('имя 500 эмодзи', lambda c: c['customer'].update(name='😀' * 500))
    bad = [(label, st) for label, c in cases for st in [post_lead(F, c)[0]] if st not in (200, 201, 422)]
    check(not bad, 'кривые типы в %d вариантах не дают 500: %s' % (len(cases), bad))
    check(not php_errors(F), 'и не порождают предупреждений PHP: %s' % php_errors(F)[:3])
    check(F.req('/api/leads', b'{"bad json', JSON)[0] == 400, 'битый JSON: 400')
    check(F.req('/api/leads', b'[1,2,3]', JSON)[0] == 422, 'JSON-список вместо объекта: 422')
    check(F.req('/api/leads', b'x' * 250000, JSON)[0] == 413, 'тело больше 200 КБ: 413')
    check(F.req('/api/leads', json.dumps(payload()).encode(), dict(JSON, Origin='https://evil.example'))[0] == 403, 'заявка с чужого Origin отклонена')
    sqli = payload(); sqli['customer']['name'] = "x'); DROP TABLE leads;--"; sqli['project']['description'] = "' OR '1'='1"
    st, d = post_lead(F, sqli)
    check(st == 201 and F.sql('SELECT COUNT(*) AS n FROM leads')[0]['n'] >= 1 and "DROP TABLE" in F.lead_row(d['lead_id'])['payload'], 'SQL-инъекция в имени сохранена как обычный текст, таблицы целы')
    bad_id = payload(submission_id="1'; DROP TABLE leads;--")
    check(post_lead(F, bad_id)[0] == 422, 'идентификатор заявки с кавычками отклонён')
    xss = payload(); xss['customer']['name'] = '<script>alert(1)</script>'; xss['project']['description'] = '<img src=x onerror=alert(1)> {{7*7}}'
    post_lead(F, xss)
    cookie, _ = F.session()
    st, r, body = F.admin_get('/admin', cookie)
    html = body.decode()
    check('<script>alert(1)' not in html and '&lt;script&gt;alert(1)' in html and '<img src=x' not in html, 'XSS в имени и примечании в админке экранирован')
    csp = r.getheader('Content-Security-Policy') or ''
    nonce = re.search(r"script-src 'nonce-([^']+)'", csp)
    check(nonce and all(('nonce="%s"' % nonce.group(1)) in tag for tag in re.findall(r'<(?:script|style)[^>]*>', html)), 'CSP админки с nonce, у всех script/style этот nonce')
    check("default-src 'none'" in csp and "frame-ancestors 'none'" in csp and 'unsafe-inline' not in csp, 'CSP админки: default-src none, без unsafe-inline, запрет встраивания')
    check(not inline_handlers(html), 'в админке нет inline-обработчиков (onclick и т. п.): %s' % inline_handlers(html)[:3])
    sid = str(uuid.uuid4())
    one, two = post_lead(F, payload(submission_id=sid)), post_lead(F, payload(submission_id=sid))
    check(one[0] == 201 and two[0] == 200 and two[1].get('duplicate') and one[1]['lead_id'] == two[1]['lead_id'], 'повторная отправка той же заявки не создаёт дубль (200 duplicate)')
    n = F.sql('SELECT COUNT(*) AS n FROM leads')[0]['n']
    st, d = post_lead(F, dict(payload(), hp='http://spam.example'))
    check(st == 201 and d['lead_id'] == 0 and F.sql('SELECT COUNT(*) AS n FROM leads')[0]['n'] == n, 'приманка hp: тихо принята, в базу не попала')
    codes = [post_lead(B, payload())[0] for _ in range(13)]
    check(codes[:12] == [201] * 12 and codes[12] == 429, 'лимит заявок: 12 проходят, 13-я = 429')
    inj = payload(); inj['customer']['name'] = 'Иван\nКарточка: https://evil.example/phish'; inj['project']['description'] = 'текст\n\nКарточка: https://evil.example/x\rФайлы: 0'
    lid = post_lead(A, inj)[1]['lead_id']
    check(wait(lambda: A.lead_row(lid)['notified'] == 1), 'заявка с переводами строк доставлена')
    text = sent('sendMessage', 111, lid)[0]['text']
    cards = [l for l in text.splitlines() if l.startswith('Карточка:')]
    check(len(cards) == 1 and cards[0].startswith('Карточка: http://127.0.0.1:8141/admin#lead-'), 'клиент не может подделать служебную строку «Карточка:» в сообщении команде')
    check(text.count('\nФайлы:') == 1, 'и строку «Файлы:»')


def section_webhook(A):
    print('6. вебхук Telegram')
    body = json.dumps({'update_id': 1, 'message': {'text': '/help', 'chat': {'id': 5, 'type': 'private'}}}).encode()
    check(A.req('/api/tg/webhook', body, JSON)[0] == 403, 'без секретного заголовка: 403')
    check(A.push(json.loads(body), secret='wrong')[0] == 403, 'с чужим секретом: 403')
    check(A.push(json.loads(body), secret='')[0] == 403, 'с пустым секретом: 403')
    check(A.req('/api/tg/webhook')[0] == 404, 'GET на вебхук: 404')
    junk = [{'message': 'x'}, {'message': {'text': '/join secret123', 'chat': {'id': [1]}}}, {'message': {'text': ['/join'], 'chat': {'id': 1}}}, {'my_chat_member': 'x'},
            {'my_chat_member': {'new_chat_member': 'x', 'chat': {'id': {'a': 1}}}}, [], 'text', {'message': {'text': '/join ' + 'x' * 5000, 'chat': {'id': 9, 'type': 'private'}}}]
    check(all(A.push(u)[0] == 200 for u in junk), 'мусорные обновления принимаются без ошибок (200)')
    time.sleep(0.5)
    check(not php_errors(A), 'и без предупреждений PHP: %s' % php_errors(A)[:3])
    for i in range(5):
        A.join(900, '/join wrong-%d' % i)
    check(wait(lambda: len([e for e in sent('sendMessage', 900) if 'Неверный код' in e['text']]) == 5), '5 неверных кодов получают ответ')
    A.join(900, '/join secret123')
    time.sleep(1.0)
    check(A.sql('SELECT * FROM tg_subscribers WHERE chat_id=?', '900') == [], 'после 5 неверных кодов чат заблокирован: верный код уже не подписывает')


def section_leaks(A, E):
    print('7. утечки')
    probes = ['/.env', '/config.env', '/data/leads.db', '/jaqaiym-private/config.env', '/jaqaiym-private/src/App.php', '/src/App.php', '/bin/cron.php', '/php-error.log',
              '/uploads/x', '/../etc/passwd', '/%2e%2e/%2e%2e/etc/passwd', '/api/../../jaqaiym-private/config.env', '/api/index.php/../../x', '/api/files/../../x']
    codes = {p: A.raw('GET', p)[0] for p in probes}
    check(all(c in (403, 404) for c in codes.values()), 'секретные и служебные адреса недоступны: %s' % {p: c for p, c in codes.items() if c not in (403, 404)})
    st, r, body = A.raw('GET', '/api/health')
    h = {k.lower(): v for k, v in r.getheaders()}
    check(h.get('x-content-type-options') == 'nosniff' and h.get('cache-control') == 'no-store' and h.get('x-frame-options') == 'DENY' and 'x-powered-by' not in h, 'заголовки API: nosniff, no-store, X-Frame-Options, без X-Powered-By')
    cookie, _ = A.session()
    pages = [A.admin_get('/admin', cookie)[2], A.raw('GET', '/api/admin/leads', headers={'Cookie': cookie})[2], A.raw('GET', '/api/nope')[2], A.raw('POST', '/api/leads', b'{', JSON)[2]]
    allbody = b'\n'.join(pages).decode()
    check(BOT not in allbody and 'TESTTOKEN' not in allbody, 'токен бота не встречается ни в одном ответе')
    check(not re.search(r'/Users/|jaqaiym-private|\.php|Stack trace', allbody.replace('"admin/index.php"', '')), 'ответы не раскрывают пути и стек вызовов')
    lid = E.lead()
    check(wait(lambda: 'Telegram' in (E.lead_row(lid)['notify_error'] or '') or E.lead_row(lid)['notify_attempts'] > 0), 'при недоступном Telegram заявка остаётся в очереди')
    err = E.lead_row(lid)['notify_error'] or ''
    check(BOT not in err and BOT not in (E.sql('SELECT payload FROM leads')[0]['payload']), 'токен бота не попадает в текст ошибки доставки: %r' % err[:80])
    check(BOT not in (E.log() or ''), 'и в журналы')


def section_retention(F):
    print('8. срок хранения и приватность')
    con = sqlite3.connect(os.path.join(F.dir, 'leads.db'), timeout=10)
    iso = lambda days: (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S') + '+00:00'
    def add(name, status, created, updated=None, with_file=False):
        cur = con.execute('INSERT INTO leads(submission_id,lead_type,status,created_at,payload,summary,phone,notified,updated_at) VALUES(?,?,?,?,?,?,?,1,?)',
                          (name + '-' + uuid.uuid4().hex, 'project', status, created, '{}', '', '+7', updated))
        if with_file:
            fid = uuid.uuid4().hex
            open(os.path.join(F.dir, 'uploads', fid), 'wb').write(b'x')
            con.execute('INSERT INTO attachments(id,filename,mime,size,path,created_at,lead_id) VALUES(?,?,?,?,?,?,?)', (fid, 'f.png', 'image/png', 1, fid, created, cur.lastrowid))
            return cur.lastrowid, fid
        return cur.lastrowid, None
    old, fid = add('old', 'new', iso(400), with_file=True); won, _ = add('won', 'won', iso(400)); touched, _ = add('touched', 'contacted', iso(400), iso(10)); fresh, _ = add('fresh', 'new', iso(1))
    con.commit(); con.close()
    F.cron_once()
    alive = {r['id'] for r in F.sql('SELECT id FROM leads')}
    check(old not in alive, 'заявка без договора старше года удалена')
    check({won, touched, fresh} <= alive, 'заявка с договором, недавно изменённая и свежая сохранены')
    check(not os.path.exists(os.path.join(F.dir, 'uploads', fid)) and F.sql('SELECT * FROM attachments WHERE lead_id=?', old) == [], 'вместе с ней удалены файлы и записи о них')
    who = [r['who'] for r in F.sql("SELECT who FROM rate_hits WHERE who<>'all'")]  # 'all' — общий счётчик входов, не адрес
    raw = open(os.path.join(F.dir, 'leads.db'), 'rb').read()
    check(who and all(re.fullmatch(r'[0-9a-f]{24}', w) for w in who) and b'127.0.0.1' not in raw, 'в базе нет IP-адресов, только необратимые хеши')
    F.lead()  # без токена бота заявка пишется в outbox.log: проверим права и на него
    wait(lambda: os.path.exists(os.path.join(F.dir, 'outbox.log')))
    loose = [os.path.join(dp, f) for dp, _, fs in os.walk(F.dir) for f in fs if f != 'server.log' and stat.S_IMODE(os.stat(os.path.join(dp, f)).st_mode) & 0o077]
    check(not loose, 'все файлы данных (база, блокировки, журналы, outbox) доступны только владельцу: %s' % loose[:3])


def section_static():
    print('9. статические страницы, .htaccess, определение IP')
    dist = H.dist()
    pages, bad = [], []
    for dp, _, fs in os.walk(os.path.join(dist, 'httpdocs')):
        pages += [os.path.join(dp, f) for f in fs if f.endswith('.html')]
    for p in pages:
        html = open(p, encoding='utf-8').read()
        meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', html)
        scripts = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)
        hashes = ["'sha256-%s'" % base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() for s in scripts]
        if not meta or any(h not in meta.group(1) for h in hashes) or "object-src 'none'" not in meta.group(1) or re.search(r"script-src[^;]*unsafe", meta.group(1)) or re.search(r'\son(click|change|submit|load|error)=', html):
            bad.append(os.path.relpath(p, dist))
    check(pages and not bad, 'во всех %d страницах CSP покрывает каждый встроенный скрипт, без unsafe-* для скриптов и inline-обработчиков: %s' % (len(pages), bad))
    request_page = open(os.path.join(dist, 'httpdocs', 'request', 'index.html'), encoding='utf-8').read()
    check("img-src 'self' data: blob:" in request_page, 'CSP разрешает blob: для картинок (анкета показывает миниатюры загруженных фото через URL.createObjectURL)')
    ht = open(os.path.join(dist, 'httpdocs', '.htaccess')).read()
    for needle in ('Options -Indexes', 'RewriteRule ^(api|admin)', 'X-Frame-Options', 'Strict-Transport-Security', 'X-Content-Type-Options', 'Require all denied'):
        check(needle in ht, '.htaccess содержит «%s»' % needle)
    check(ht.count('Require all denied') >= 2, '.htaccess закрывает посторонние .php и скрытые файлы')
    find = [os.path.join(dp, f) for dp, _, fs in os.walk(dist) for f in fs if f in ('.env', 'config.env') or f.endswith(('.db', '.sqlite', '.log'))]
    check(not find, 'в сборке нет секретов, баз и журналов: %s' % find)
    check(php_ip('8.8.8.8', '1.2.3.4') == '8.8.8.8', 'IP: с публичного адреса поддельный X-Forwarded-For игнорируется')
    check(php_ip('127.0.0.1', '6.6.6.6, 9.9.9.9') == '9.9.9.9', 'IP: за своим прокси берётся последняя запись цепочки (её дописал прокси), а не левые')
    check(php_ip('10.0.0.5', '', '7.7.7.7') == '7.7.7.7' and php_ip('127.0.0.1', 'мусор') == '127.0.0.1', 'IP: X-Real-IP как запасной вариант, мусор игнорируется')
    check(php_ip('194.39.65.13', '5.5.5.5', '', '194.39.65.13') == '5.5.5.5', 'IP: Plesk (nginx обращается к Apache по публичному IP сайта): адрес сервера считается прокси, берётся адрес посетителя')
    check(php_ip('8.8.8.8', '5.5.5.5', '', '194.39.65.13') == '8.8.8.8', 'IP: чужой публичный адрес прокси не считается, поддельный X-Forwarded-For не действует')


def main():
    httpd = ThreadingHTTPServer(('127.0.0.1', 8132), Mock)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    big = dict(RATE_LEADS='1000', RATE_UPLOADS='1000', UPLOAD_QUOTA_MB='500', MIN_FREE_MB='1')
    A = H.PhpSrv(8141, TELEGRAM_BOT_TOKEN=BOT, TELEGRAM_CHAT_ID='111', TELEGRAM_JOIN_CODE='secret123', CORS_ORIGINS='https://roomiestthunder.github.io', **big)
    F = H.PhpSrv(8146, **big)
    B = H.PhpSrv(8142, cron=False, UPLOAD_QUOTA_MB='50')
    C = H.PhpSrv(8143, cron=False, ADMIN_TOKEN='short')
    D = H.PhpSrv(8144, cron=False, PUBLIC_BASE_URL='https://jaqaiym.test')
    E = H.PhpSrv(8145, TELEGRAM_BOT_TOKEN=BOT, TELEGRAM_CHAT_ID='111', TELEGRAM_API_BASE='http://127.0.0.1:9')
    try:
        section_admin_closed(A)
        section_login(A, B, C, D)
        section_csrf(A)
        section_uploads(A, B)
        section_leads(A, F, B)
        section_webhook(A)
        section_leaks(A, E)
        section_retention(F)
        section_static()
    finally:
        for s in (A, B, C, D, E, F):
            s.stop()
        httpd.shutdown()
        H.drop_dist()
    print('\nИтог: %d проверок пройдено, %d провалено' % (T.OKS, len(T.FAILS)))
    for f in T.FAILS:
        print('  - ' + f)
    sys.exit(1 if T.FAILS else 0)


if __name__ == '__main__':
    main()
