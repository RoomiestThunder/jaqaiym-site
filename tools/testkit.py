"""Общие части тестов: подставной Telegram, проверки, помощники для заявок и файлов.
Сервер под тестом (tools/php_harness.py: PhpSrv) наследует Srv отсюда."""
import email, email.policy, json, os, re, shutil, sqlite3, threading, time, urllib.error, urllib.parse, urllib.request, uuid
from http.server import BaseHTTPRequestHandler

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


class Srv:
    """Что умеет любой сервер под тестом: запросы, загрузка файлов, заявка, чтение базы и папки загрузок.
    Запуск и остановку процесса определяет наследник (PhpSrv)."""

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
    def stop(self): shutil.rmtree(self.dir, ignore_errors=True)




def wait(cond, timeout=40, step=0.2):  # с запасом: на нагруженном компьютере cron и сервер отвечают медленнее
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
