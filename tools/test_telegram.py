#!/usr/bin/env python3
"""Автотест доставки заявок в Telegram на подставном Telegram API (настоящий токен не нужен).

  python3 tools/test_telegram.py

Запускает mock-Telegram и копии server.py с временной папкой данных и проверяет:
  A  текст + альбом фото + PDF доходят, файлы удаляются с диска, выдача удалённого файла = 410
  B  подписчики через /join КОД: неверный код отклонён, рассылка всем, при сбое у одного нет дублей, файлы удаляются после последнего
  C  заблокировавший бота подписчик отключается и не мешает остальным
  D  Telegram не принял альбом как фото: уходит файлами
  E  загрузка без заявки удаляется через ORPHAN_HOURS; квота диска (507)
  F  нет получателей: заявка ждёт, после /join доставляется
  G  без токена бота: outbox.log, файлы не удаляются сразу
"""
import email, email.policy, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, threading, time, urllib.error, urllib.parse, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import contract

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS, OKS = [], 0


def check(cond, label):
    global OKS
    if cond:
        OKS += 1; print('  ok   ' + label)
    else:
        FAILS.append(label); print('  FAIL ' + label)


# ---------------- подставной Telegram ----------------
class Mock(BaseHTTPRequestHandler):
    log, fail, updates, lock, n = [], {}, [], threading.Lock(), [0]
    webhook = {}                                              # то, что передали в setWebhook

    def log_message(self, *a): pass

    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        method = self.path.split('/')[-1]
        ctype = self.headers.get('Content-Type', '')
        fields, files = {}, []
        if ctype.startswith('multipart/'):
            msg = email.message_from_bytes(b'Content-Type: ' + ctype.encode() + b'\r\n\r\n' + body, policy=email.policy.HTTP)
            for part in msg.iter_parts():
                nm, fn, data = part.get_param('name', header='content-disposition'), part.get_filename(), part.get_payload(decode=True)
                if fn is not None: files.append((nm, fn, len(data)))
                else: fields[nm] = data.decode()
        elif body:
            fields = json.loads(body)
        if method == 'getUpdates':
            time.sleep(0.2)
            with self.lock:                                   # как настоящий Telegram: обновление живёт, пока его не подтвердят offset-ом
                off = fields.get('offset')
                if off is not None:
                    Mock.updates = [u for u in Mock.updates if u['update_id'] >= int(off)]
                ups = Mock.updates[:]
            return self.reply(200, {'ok': True, 'result': ups})
        if method == 'getMe': return self.reply(200, {'ok': True, 'result': {'username': 'jq_test_bot'}})
        if method == 'deleteWebhook': return self.reply(200, {'ok': True, 'result': True})
        if method == 'setWebhook':
            Mock.webhook = fields; return self.reply(200, {'ok': True, 'result': True})
        if method == 'getWebhookInfo':
            return self.reply(200, {'ok': True, 'result': {'url': Mock.webhook.get('url', ''), 'pending_update_count': 0}})
        chat = str(fields.get('chat_id'))
        caption = fields.get('caption') or fields.get('text') or ''
        if method == 'sendMediaGroup':
            media = json.loads(fields['media']); caption = media[0].get('caption', '')
        m = re.search(r'№(\d+)', caption)
        entry = {'method': method, 'chat': chat, 'lead': int(m.group(1)) if m else None, 'files': files, 'text': fields.get('text', ''), 'caption': caption}
        with self.lock:
            rules = Mock.fail.get((method, chat)) or Mock.fail.get((method, '*'))
            if rules:
                code, desc, ra = rules.pop(0)
                if not rules: Mock.fail.pop((method, chat), None); Mock.fail.pop((method, '*'), None)
                entry['failed'] = code; Mock.log.append(entry)
                return self.reply(code, {'ok': False, 'error_code': code, 'description': desc, 'parameters': {'retry_after': ra} if ra else {}})
            Mock.log.append(entry); Mock.n[0] += 1
        self.reply(200, {'ok': True, 'result': {'message_id': Mock.n[0]}})


def sent(method=None, chat=None, lead=None):
    with Mock.lock:
        return [e for e in Mock.log if 'failed' not in e and (method is None or e['method'] == method) and (chat is None or e['chat'] == str(chat)) and (lead is None or e['lead'] == lead)]


# ---------------- сервер под тестом ----------------
class Srv:
    def __init__(self, port, **env):
        self.port, self.dir = port, tempfile.mkdtemp(prefix='jq-test-')
        e = dict(os.environ, DATA_DIR=self.dir, ADMIN_TOKEN='admintest', TELEGRAM_API_BASE='http://127.0.0.1:8132', TG_RETRY_BASE_SECONDS='1', TG_RETRY_TICK_SECONDS='0.5',
                 CLEANUP_TICK_SECONDS='1', JQ_NO_DOTENV='1', ORPHAN_HOURS='0.0008', TG_POLL_TIMEOUT='1', MIN_FREE_MB='1', UPLOAD_QUOTA_MB='0.2')
        for k in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_JOIN_CODE'): e.pop(k, None)
        e.update({k: v for k, v in env.items() if v is not None})
        self.p = subprocess.Popen([sys.executable, os.path.join(ROOT, 'server.py'), str(port)], env=e, stdout=subprocess.DEVNULL, stderr=open(os.path.join(self.dir, 'err.log'), 'w'))
        for _ in range(50):
            try: urllib.request.urlopen('http://127.0.0.1:%d/api/health' % port, timeout=1); break
            except Exception: time.sleep(0.1)

    def req(self, path, data=None, headers=None):
        r = urllib.request.Request('http://127.0.0.1:%d%s' % (self.port, path), data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=10) as x: return x.status, json.loads(x.read() or b'{}')
        except urllib.error.HTTPError as ex:
            try: return ex.code, json.loads(ex.read() or b'{}')
            except Exception: return ex.code, {}

    def upload(self, name, data):
        return self.req('/api/attachments', data, {'X-File-Name': urllib.parse.quote(name)})

    def lead(self, atts=()):
        p = {'schema_version': 1, 'submission_id': str(uuid.uuid4()), 'lead_type': 'project', 'locale': 'ru', 'customer': {'name': 'Тест', 'phone': '+77001234567', 'preferred_channel': 'whatsapp'},
             'consent': {'project_contact': True}, 'source': {'page': '/test'},
             'project': {'category': 'wardrobe', 'city': 'almaty', 'premise': 'apartment', 'wardrobe_kind': 'niche', 'style_preferences': ['light'],
                         'features': {'door_type': ['swing'], 'storage_priorities': ['drawers']}, 'dimensions_known': False, 'attachment_ids': list(atts)}}
        st, d = self.req('/api/leads', json.dumps(p).encode(), {'Content-Type': 'application/json'})
        assert st in (200, 201), (st, d)
        return d['lead_id']

    def sql(self, q, *a):
        c = sqlite3.connect(os.path.join(self.dir, 'leads.db'), timeout=5); c.row_factory = sqlite3.Row
        try: return [dict(r) for r in c.execute(q, a)]
        finally: c.close()

    def lead_row(self, lid): return self.sql('SELECT * FROM leads WHERE id=?', lid)[0]
    def disk(self): return sorted(os.listdir(os.path.join(self.dir, 'uploads')))
    def stop(self): self.p.terminate(); self.p.wait(5); shutil.rmtree(self.dir, ignore_errors=True)


def wait(cond, timeout=15, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cond(): return True
        except Exception: pass
        time.sleep(step)
    return False


PNG, JPG, PDF = (lambda: b'\x89PNG\r\n\x1a\n' + os.urandom(20000)), (lambda: b'\xff\xd8\xff\xe0' + os.urandom(20000)), (lambda: b'%PDF-1.4\n' + os.urandom(20000))


UPD = [1000]


def join(chat_id, text, kind='private', title=None):
    with Mock.lock:
        UPD[0] += 1
        Mock.updates.append({'update_id': UPD[0], 'message': {'text': text, 'chat': {'id': chat_id, 'type': kind, 'title': title, 'first_name': 'Айгүл'}}})


def main():
    httpd = ThreadingHTTPServer(('127.0.0.1', 8132), Mock)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    S = Srv(8133, TELEGRAM_BOT_TOKEN='TESTTOKEN', TELEGRAM_CHAT_ID='111', TELEGRAM_JOIN_CODE='secret123')
    try:
        print('A. текст + альбом + PDF, файлы удаляются')
        ids = [S.upload('a.png', PNG())[1]['id'], S.upload('b.png', PNG())[1]['id'], S.upload('c.jpg', JPG())[1]['id'], S.upload('план.pdf', PDF())[1]['id']]
        check(len(S.disk()) == 4, 'до отправки на диске 4 файла')
        lid = S.lead(ids)
        check(wait(lambda: S.lead_row(lid)['notified'] == 1), 'заявка помечена доставленной')
        check(len(sent('sendMessage', 111, lid)) == 1 and 'Файлы: 4' in sent('sendMessage', 111, lid)[0]['text'], 'одно текстовое сообщение, в нём указано число файлов')
        g = sent('sendMediaGroup', 111, lid)
        check(len(g) == 1 and len(g[0]['files']) == 3, 'фото ушли одним альбомом (3 шт.)')
        d = sent('sendDocument', 111, lid)
        check(len(d) == 1 and d[0]['files'][0][1] == 'план.pdf', 'PDF ушёл документом с исходным именем')
        check(S.disk() == [], 'после отправки на диске файлов нет')
        check(S.lead_row(lid)['notified_via'] == 'telegram', 'способ доставки: telegram')
        check(S.req('/api/files/%s?token=admintest' % ids[0])[0] == 410, 'удалённый файл отдаётся как 410')
        check(all(r['deleted_at'] for r in S.sql('SELECT deleted_at FROM attachments')), 'в базе файлы помечены удалёнными')
        st, page = 200, urllib.request.urlopen('http://127.0.0.1:8133/admin?token=admintest').read().decode()
        check('отправлен в Telegram и удалён с сервера' in page and 'доставлено в Telegram' in page and 'jq_test_bot' in page, 'админка показывает доставку, удалённые файлы и бота')

        print('A2. CORS: страница с github.io может слать заявки')
        def opt(origin):
            r = urllib.request.Request('http://127.0.0.1:8133/api/leads', method='OPTIONS', headers={'Origin': origin, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
            with urllib.request.urlopen(r, timeout=5) as x: return x.status, x.headers
        st, h = opt('https://roomiestthunder.github.io')
        check(st == 204 and h.get('Access-Control-Allow-Origin') == 'https://roomiestthunder.github.io' and 'Content-Type' in h.get('Access-Control-Allow-Headers', ''), 'предзапрос с github.io разрешён')
        check('Access-Control-Allow-Origin' not in opt('https://evil.example')[1], 'чужой адрес не получает разрешения')

        print('B. подписчики и частичный сбой')
        join(222, '/join@jq_test_bot secret123'); join(-1003, '/join secret123', 'supergroup', 'Команда'); join(444, '/join wrong')
        check(wait(lambda: len(S.sql('SELECT * FROM tg_subscribers WHERE active=1')) == 2), 'по верному коду подписались личный чат и группа')
        check(any('Неверный код' in e['text'] for e in sent('sendMessage', 444)), 'неверный код отклонён, подписки нет')
        Mock.fail[('sendMediaGroup', '222')] = [(429, 'Too Many Requests: retry after 1', 1)]
        ids = [S.upload('x.png', PNG())[1]['id'], S.upload('y.png', PNG())[1]['id']]
        lid = S.lead(ids)
        check(wait(lambda: S.lead_row(lid)['notified'] == 1, 25), 'после сбоя у одного получателя заявка доставлена повтором')
        for ch in ('111', '222', '-1003'):
            check(len(sent('sendMessage', ch, lid)) == 1, 'чат %s получил текст ровно один раз' % ch)
            check(len(sent('sendMediaGroup', ch, lid)) == 1, 'чат %s получил альбом ровно один раз' % ch)
        check(S.disk() == [], 'файлы удалены только после доставки всем')

        print('C. заблокировавший бота подписчик')
        join(555, '/join secret123')
        check(wait(lambda: len(S.sql('SELECT * FROM tg_subscribers WHERE active=1')) == 3), 'ещё один подписчик')
        Mock.fail[('sendMessage', '555')] = [(403, 'Forbidden: bot was blocked by the user', 0)]
        ids = [S.upload('z.png', PNG())[1]['id']]
        lid = S.lead(ids)
        check(wait(lambda: S.lead_row(lid)['notified'] == 1), 'заявка доставлена остальным')
        check(S.sql('SELECT active FROM tg_subscribers WHERE chat_id=?', '555')[0]['active'] == 0, 'недоступный подписчик отключён')
        check(S.disk() == [], 'файлы удалены')

        print('D. альбом не принят как фото')
        Mock.fail[('sendMediaGroup', '111')] = [(400, 'Bad Request: PHOTO_INVALID_DIMENSIONS', 0)]
        ids = [S.upload('big1.png', PNG())[1]['id'], S.upload('big2.png', PNG())[1]['id']]
        lid = S.lead(ids)
        check(wait(lambda: S.lead_row(lid)['notified'] == 1), 'заявка доставлена')
        check(len(sent('sendDocument', 111, lid)) == 2, 'в чат 111 изображения ушли файлами (запасной путь)')
        check(S.disk() == [], 'файлы удалены')

        print('E. очистка и квота')
        orphan = S.upload('orphan.jpg', JPG())[1]['id']
        check(orphan in S.disk(), 'загрузка без заявки лежит на диске')
        check(wait(lambda: orphan not in S.disk(), 15), 'через ORPHAN_HOURS загрузка без заявки удалена')
        big = b'\xff\xd8\xff\xe0' + os.urandom(150000)
        check(S.upload('big.jpg', big)[0] == 201, 'файл в пределах квоты принят')
        st, d = S.upload('big2.jpg', big)
        check(st == 507 and d.get('error') == 'storage_full', 'сверх квоты отказ 507 storage_full')
        check(wait(lambda: S.disk() == [], 15), 'после очистки место освободилось')
        check(S.upload('again.jpg', JPG())[0] == 201, 'загрузка снова принимается')

        print('F. отписка')
        join(222, '/leave')
        check(wait(lambda: S.sql('SELECT active FROM tg_subscribers WHERE chat_id=?', '222')[0]['active'] == 0), '/leave отключает подписку')
    finally:
        S.stop()

    print('G. нет получателей: заявка ждёт подписчика')
    S2 = Srv(8134, TELEGRAM_BOT_TOKEN='TESTTOKEN', TELEGRAM_JOIN_CODE='secret123')
    try:
        ids = [S2.upload('w.png', PNG())[1]['id']]
        lid = S2.lead(ids)
        check(wait(lambda: 'Нет получателей' in (S2.lead_row(lid)['notify_error'] or '')), 'без получателей заявка ждёт, причина видна')
        check(S2.disk() == ids, 'файл пока лежит на диске')
        join(777, '/start secret123')
        ok = wait(lambda: S2.lead_row(lid)['notified'] == 1, 20)
        check(ok, 'после подписки заявка доставлена')
        if not ok:
            print('   отладка:', {k: S2.lead_row(lid)[k] for k in ('notified', 'notify_attempts', 'notify_error', 'next_attempt_at', 'tg_targets')},
                  S2.sql('SELECT chat_id, active FROM tg_subscribers'), [(e['method'], e['chat'], e.get('failed')) for e in Mock.log[-6:]], 'updates в очереди:', len(Mock.updates), '\n   err.log:', open(os.path.join(S2.dir, 'err.log')).read()[-600:])
        check(len(sent('sendPhoto', 777, lid)) == 1, 'одно фото ушло методом sendPhoto')
        check(wait(lambda: S2.disk() == []), 'файл удалён')
    finally:
        S2.stop()

    print('H. без токена бота (тестовый режим)')
    S3 = Srv(8135)
    try:
        ids = [S3.upload('t.png', PNG())[1]['id']]
        lid = S3.lead(ids)
        check(wait(lambda: S3.lead_row(lid)['notified'] == 1), 'заявка записана в outbox')
        check(S3.lead_row(lid)['notified_via'] == 'outbox' and os.path.exists(os.path.join(S3.dir, 'outbox.log')), 'способ: outbox, файл outbox.log создан')
        check(S3.disk() == ids, 'файлы остаются до срока хранения')
        contract.run(S3, check)
    finally:
        S3.stop()
    httpd.shutdown()
    print('\nИтог: %d проверок пройдено, %d провалено' % (OKS, len(FAILS)))
    for f in FAILS: print('  - ' + f)
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
