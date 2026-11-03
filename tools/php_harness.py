"""Общая обвязка тестов PHP-версии: боевая сборка во временную папку, встроенный сервер PHP,
«планировщик» (cron.php раз в полсекунды), вход в админку, подставной Telegram из testkit.py."""
import http.client, json, os, re, shutil, signal, subprocess, sys, tempfile, threading, time, urllib.error, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testkit as T  # noqa: E402

ROOT = T.ROOT
ADMIN = 'admin-test-password-0123456789'
ADMIN_PATH = '/admin/test-secret-path-1'  # непубличный адрес админки по умолчанию: без него админка не включается
WEBHOOK_SECRET = 'wh-secret-test'
MOCK_URL = 'http://127.0.0.1:8132'
_dist = []


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
    """Сервер заявок на PHP. Методы req/upload/lead/sql/lead_row/disk унаследованы от testkit.Srv."""

    def __init__(self, port, cron=True, **env):
        d = dist()
        self.port, self.dir, self.admin = port, tempfile.mkdtemp(prefix='jq-test-'), ADMIN
        self.private = os.path.join(d, 'jaqaiym-private')
        e = dict(os.environ, JQ_PRIVATE_DIR=self.private, JQ_PUBLIC_DIR=os.path.join(d, 'httpdocs'), DATA_DIR=self.dir, ADMIN_TOKEN=ADMIN, ADMIN_PATH=ADMIN_PATH,
                 PUBLIC_BASE_URL='http://127.0.0.1:%d' % port, TELEGRAM_API_BASE=MOCK_URL, TG_RETRY_BASE_SECONDS='1', ORPHAN_HOURS='0.0008',
                 MIN_FREE_MB='1', UPLOAD_QUOTA_MB='0.2', TG_WEBHOOK_SECRET=WEBHOOK_SECRET, PHP_CLI_SERVER_WORKERS='4')
        for k in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_JOIN_CODE', 'CORS_ORIGINS'):
            e.pop(k, None)
        e.update({k: v for k, v in env.items() if v is not None})
        self.env = e
        self.admin_path = e.get('ADMIN_PATH') or '/admin'  # без ADMIN_PATH админка отключена, а причина показана на /admin
        # настройки PHP, как на нормальном хостинге: ошибки в журнал, а не в ответ; лимит тела не меньше 11 МБ
        self._argv = ['php', '-d', 'display_errors=0', '-d', 'post_max_size=16M', '-d', 'upload_max_filesize=16M',
                      '-S', '127.0.0.1:%d' % port, '-t', os.path.join(d, 'httpdocs'), os.path.join(ROOT, 'php', 'dev-router.php')]
        self._revives = 0
        self._spawn()
        self.halt = threading.Event()
        if cron:
            threading.Thread(target=self._cron_loop, daemon=True).start()

    def _spawn(self):
        self.p = subprocess.Popen(self._argv, env=self.env, stdout=subprocess.DEVNULL, stderr=open(os.path.join(self.dir, 'server.log'), 'a'), start_new_session=True)
        for _ in range(80):
            try:
                if super().req('/api/health')[0] == 200:
                    return
            except Exception:
                time.sleep(0.1)

    def _revive(self):
        """Встроенный сервер PHP с несколькими процессами изредка падает посреди прогона (в CI это один раз случилось).
        Данные лежат на диске, поэтому достаточно запустить его заново; журнал выводится, чтобы причину было видно. True: перезапущен."""
        if self.p.poll() is not None and self._revives < 3 and not self.halt.is_set():
            self._revives += 1
            log = os.path.join(self.dir, 'server.log')
            tail = open(log, encoding='utf-8', errors='replace').read()[-600:] if os.path.exists(log) else ''
            print('  !!   тестовый сервер на порту %d завершился (код %s), запускаю заново. Журнал: %s' % (self.port, self.p.returncode, tail.strip() or 'пусто'))
            self._spawn()
            return True
        return False

    def req(self, path, data=None, headers=None):
        try:
            return super().req(path, data, headers)
        except urllib.error.URLError:
            if not self._revive():
                raise
            return super().req(path, data, headers)

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
        for attempt in (0, 1):
            try:
                c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
                c.request(method, path, body, headers or {})
                r = c.getresponse()
                data = r.read()
                c.close()
                return r.status, r, data
            except OSError:
                if attempt or not self._revive():
                    raise

    def login(self, password=None, xff=None):
        """Вход паролем. xff: адрес «посетителя» (за прокси сервер берёт последнюю запись X-Forwarded-For)."""
        fields = {'password': password if password is not None else ADMIN}
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if xff:
            headers['X-Forwarded-For'] = xff
        st, r, body = self.raw('POST', self.admin_path + '/login', urllib.parse.urlencode(fields), headers)
        header = r.getheader('Set-Cookie') or ''
        return st, (header.split(';')[0] if header else None), header

    def session(self):
        """Вход под правильным паролем: (cookie, csrf-токен страницы)."""
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
