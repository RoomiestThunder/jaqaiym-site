"""Общая обвязка тестов PHP-версии: боевая сборка во временную папку, встроенный сервер PHP,
«планировщик» (cron.php раз в полсекунды), вход в админку, подставной Telegram из test_telegram.py."""
import base64, hashlib, hmac, http.client, json, os, re, shutil, signal, struct, subprocess, sys, tempfile, threading, time, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_telegram as T  # noqa: E402

ROOT = T.ROOT
ADMIN = 'admin-test-password-0123456789'
WEBHOOK_SECRET = 'wh-secret-test'
MOCK_URL = 'http://127.0.0.1:8132'
_dist = []


def totp_code(secret_b32, at=None):
    """Одноразовый код по RFC 6238 (HMAC-SHA1, шаг 30 с, 6 цифр): независимая от PHP реализация для сверки."""
    key = base64.b32decode(secret_b32 + '=' * (-len(secret_b32) % 8), casefold=True)
    counter = int((time.time() if at is None else at) // 30)
    mac = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = mac[-1] & 15
    return '%06d' % ((struct.unpack('>I', mac[offset:offset + 4])[0] & 0x7fffffff) % 10 ** 6)


def dist():
    """Собирает сайт один раз на весь прогон."""
    if not _dist:
        out = tempfile.mkdtemp(prefix='jq-dist-')
        subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'build_php.py'), '--out', out, '--noindex'], check=True, stdout=subprocess.DEVNULL)
        _dist.append(out)
    return _dist[0]


def drop_dist():
    for d in _dist:
        shutil.rmtree(d, ignore_errors=True)
    _dist.clear()


class PhpSrv(T.Srv):
    """Сервер заявок на PHP. Методы req/upload/lead/sql/lead_row/disk унаследованы от версии для Python."""

    def __init__(self, port, cron=True, **env):
        d = dist()
        self.port, self.dir, self.admin = port, tempfile.mkdtemp(prefix='jq-test-'), ADMIN
        self.private = os.path.join(d, 'jaqaiym-private')
        e = dict(os.environ, JQ_PRIVATE_DIR=self.private, JQ_PUBLIC_DIR=os.path.join(d, 'httpdocs'), DATA_DIR=self.dir, ADMIN_TOKEN=ADMIN,
                 PUBLIC_BASE_URL='http://127.0.0.1:%d' % port, TELEGRAM_API_BASE=MOCK_URL, TG_RETRY_BASE_SECONDS='1', ORPHAN_HOURS='0.0008',
                 MIN_FREE_MB='1', UPLOAD_QUOTA_MB='0.2', TG_WEBHOOK_SECRET=WEBHOOK_SECRET, PHP_CLI_SERVER_WORKERS='4')
        for k in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_JOIN_CODE', 'CORS_ORIGINS'):
            e.pop(k, None)
        e.update({k: v for k, v in env.items() if v is not None})
        self.env = e
        self.admin_path, self.totp_secret = e.get('ADMIN_PATH', '/admin'), e.get('ADMIN_TOTP_SECRET', '')
        # настройки PHP, как на нормальном хостинге: ошибки в журнал, а не в ответ; лимит тела не меньше 11 МБ
        self.p = subprocess.Popen(['php', '-d', 'display_errors=0', '-d', 'post_max_size=16M', '-d', 'upload_max_filesize=16M',
                                   '-S', '127.0.0.1:%d' % port, '-t', os.path.join(d, 'httpdocs'), os.path.join(ROOT, 'php', 'dev-router.php')],
                                  env=e, stdout=subprocess.DEVNULL, stderr=open(os.path.join(self.dir, 'server.log'), 'w'), start_new_session=True)
        for _ in range(80):
            try:
                if self.req('/api/health')[0] == 200:
                    break
            except Exception:
                time.sleep(0.1)
        self.halt = threading.Event()
        if cron:
            threading.Thread(target=self._cron_loop, daemon=True).start()

    def _cron_loop(self):
        script = os.path.join(self.private, 'bin', 'cron.php')
        while not self.halt.is_set():
            subprocess.run(['php', script], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.halt.wait(0.5)

    def cron_once(self):
        return subprocess.run(['php', os.path.join(self.private, 'bin', 'cron.php')], env=dict(self.env, JQ_VERBOSE='1'), capture_output=True, text=True).stdout

    def stop(self):
        self.halt.set()
        try:
            os.killpg(self.p.pid, signal.SIGTERM)  # группа целиком: у встроенного сервера есть дочерние процессы
        except ProcessLookupError:
            pass
        self.p.wait(5)
        shutil.rmtree(self.dir, ignore_errors=True)

    def log(self):
        out = ''
        for name in ('server.log', 'php-error.log'):
            p = os.path.join(self.dir, name)
            out += open(p).read()[-800:] if os.path.exists(p) else ''
        return out

    # ---------- «сырые» запросы без автоматических переходов по ссылкам ----------
    def raw(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        c.request(method, path, body, headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, r, data

    def login(self, password=None, code=None, step_offset=0, xff=None):
        """Вход. code=None: при включённой 2FA подставляется верный код (со сдвигом step_offset шагов по 30 с); code='' — без кода.
        xff: адрес «посетителя» (за прокси сервер берёт последнюю запись X-Forwarded-For)."""
        fields = {'password': password if password is not None else ADMIN}
        if code is None and self.totp_secret:
            code = totp_code(self.totp_secret, time.time() + 30 * step_offset)
        if code:
            fields['code'] = code
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if xff:
            headers['X-Forwarded-For'] = xff
        st, r, body = self.raw('POST', self.admin_path + '/login', urllib.parse.urlencode(fields), headers)
        header = r.getheader('Set-Cookie') or ''
        return st, (header.split(';')[0] if header else None), header

    def session(self):
        """Вход под правильным паролем (и кодом, если включена 2FA): (cookie, csrf-токен страницы)."""
        st, cookie, _ = self.login()
        assert st == 303 and cookie, 'вход не удался: %s' % st
        st, _, body = self.raw('GET', self.admin_path, headers={'Cookie': cookie})
        return cookie, re.search(rb'var csrf="([0-9a-f]+)"', body).group(1).decode()

    def admin_get(self, path, cookie):
        st, r, body = self.raw('GET', path, headers={'Cookie': cookie})
        return st, r, body

    def admin_post(self, path, cookie, csrf, body=None, **headers):
        h = {'Cookie': cookie, 'Content-Type': 'application/json'}
        if csrf is not None:
            h['X-CSRF-Token'] = csrf
        h.update(headers)
        st, _, data = self.raw('POST', path, json.dumps(body or {}), h)
        try:
            return st, json.loads(data or b'{}')
        except ValueError:
            return st, {}

    def push(self, update, secret=WEBHOOK_SECRET):
        h = {'Content-Type': 'application/json'}
        if secret is not None:
            h['X-Telegram-Bot-Api-Secret-Token'] = secret
        return self.req('/api/tg/webhook', json.dumps(update).encode(), h)

    def join(self, chat_id, text, kind='private', title=None):
        return self.push({'update_id': int(time.time() * 1000) % 10**9, 'message': {'text': text, 'chat': {'id': chat_id, 'type': kind, 'title': title, 'first_name': 'Айгүл'}}})
