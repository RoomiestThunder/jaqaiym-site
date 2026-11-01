"""Доставка заявок в Telegram: текст, фото (альбомом) и PDF; подписчики бота; чистка временных файлов.

Принципы:
  * Заявка сохраняется в базе ДО отправки; сбой Telegram заявку не теряет.
  * Файлы лежат на диске только до успешной отправки всем получателям, затем удаляются.
  * Повтор после сбоя не дублирует то, что уже дошло (учёт по таблице tg_sent: заявка x чат x «text» или файл).
  * Получатели: общий чат из TELEGRAM_CHAT_ID и подписчики, которые сами подключились командой /join КОД.
Только стандартная библиотека Python.
"""
import hmac, json, os, re, sys, threading, time, urllib.error, urllib.request, uuid
from datetime import datetime, timedelta, timezone

API_BASE = os.environ.get('TELEGRAM_API_BASE', 'https://api.telegram.org').rstrip('/')   # для тестов можно подменить
RETRY_BASE = float(os.environ.get('TG_RETRY_BASE_SECONDS', 60))     # первая пауза между попытками, дальше удваивается (максимум час)
RETRY_TICK = float(os.environ.get('TG_RETRY_TICK_SECONDS', 30))     # как часто сервер проверяет, что пора повторить
MAX_ATTEMPTS = int(os.environ.get('TG_MAX_ATTEMPTS', 40))           # после этого ждём кнопку «Повторить» в админке
CLEAN_TICK = float(os.environ.get('CLEANUP_TICK_SECONDS', 600))
ORPHAN_HOURS = float(os.environ.get('ORPHAN_HOURS', 24))            # загрузки без заявки удаляются через сутки
UNSENT_DAYS = float(os.environ.get('UNSENT_FILE_DAYS', 7))          # неотправленные файлы удаляются через неделю
POLL_TIMEOUT = int(os.environ.get('TG_POLL_TIMEOUT', 25))


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def iso_after(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec='seconds')


def iso_before(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec='seconds')


class TgError(Exception):
    def __init__(self, code, desc, retry_after=0, migrate_to=None):
        super().__init__('%s: %s' % (code, desc))
        self.code, self.desc, self.retry_after, self.migrate_to = code, str(desc or ''), int(retry_after or 0), migrate_to

    @property
    def permanent(self):
        """Чат недоступен насовсем (бота удалили или заблокировали): ждать бессмысленно."""
        d = self.desc.lower()
        return self.code == 403 or (self.code == 400 and any(s in d for s in ('chat not found', 'kicked', 'blocked', 'not a member', 'deactivated', 'have no rights')))


def multipart(fields, files):
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n' % (b, k)).encode() + str(v).encode('utf-8') + b'\r\n')
    for field, fname, mime, data in files:
        safe = str(fname).replace('"', "'").replace('\r', ' ').replace('\n', ' ')
        out.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n' % (b, field, safe, mime)).encode('utf-8') + data + b'\r\n')
    out.append(('--%s--\r\n' % b).encode())
    return b''.join(out), 'multipart/form-data; boundary=' + b


class Notifier:
    def __init__(self, db, db_lock, text_fn, log=None):
        self.db, self.lock, self.text_fn = db, db_lock, text_fn
        self.log = log or (lambda m: sys.stderr.write(m + '\n'))
        self.inflight, self.inflight_lock = set(), threading.Lock()
        self.bad_codes = {}
        self._bot_username = None

    # ---------- настройки ----------
    @staticmethod
    def token():
        return os.environ.get('TELEGRAM_BOT_TOKEN') or ''

    @staticmethod
    def static_chat():
        return (os.environ.get('TELEGRAM_CHAT_ID') or '').strip()

    @staticmethod
    def join_code():
        return (os.environ.get('TELEGRAM_JOIN_CODE') or '').strip()

    # ---------- Telegram API ----------
    def api(self, method, payload=None, files=None, timeout=60):
        tok = self.token()
        url = '%s/bot%s/%s' % (API_BASE, tok, method)
        try:
            if files:
                body, ctype = multipart(payload or {}, files)
            else:
                body, ctype = json.dumps(payload or {}).encode(), 'application/json'
            data = json.loads(urllib.request.urlopen(urllib.request.Request(url, data=body, headers={'Content-Type': ctype}), timeout=timeout).read())
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read())
            except Exception:
                j = {}
            p = j.get('parameters') or {}
            raise TgError(e.code, j.get('description') or e.reason, p.get('retry_after'), p.get('migrate_to_chat_id'))
        except Exception as e:                       # сеть, таймаут: токен в текст ошибки не попадает
            raise TgError(0, (type(e).__name__ + ': ' + str(e)).replace(tok, '***')[:200])
        if not data.get('ok'):
            p = data.get('parameters') or {}
            raise TgError(data.get('error_code', 0), data.get('description'), p.get('retry_after'), p.get('migrate_to_chat_id'))
        return data['result']

    def bot_username(self):
        if self._bot_username is None and self.token():
            try:
                self._bot_username = self.api('getMe', timeout=10).get('username') or ''
            except TgError:
                return None
        return self._bot_username or None

    # ---------- получатели ----------
    def subscribers(self, only_active=True):
        with self.lock:
            q = 'SELECT * FROM tg_subscribers' + (' WHERE active=1' if only_active else '') + ' ORDER BY joined_at'
            return [dict(r) for r in self.db.execute(q)]

    def _upsert_subscriber(self, chat_id, title, kind):
        with self.lock:
            self.db.execute('INSERT INTO tg_subscribers(chat_id,title,kind,joined_at,active) VALUES(?,?,?,?,1) '
                            'ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, kind=excluded.kind, active=1', (str(chat_id), title, kind, now()))
            # заявки, которые ждали получателя, отправляются сразу, без долгой паузы
            self.db.execute('UPDATE leads SET next_attempt_at=NULL, notify_attempts=0 WHERE notified=0 AND tg_targets IS NULL')
            self.db.commit()

    def deactivate_subscriber(self, chat_id):
        with self.lock:
            self.db.execute('UPDATE tg_subscribers SET active=0 WHERE chat_id=?', (str(chat_id),))
            self.db.commit()

    def _say(self, chat_id, text):
        try:
            self.api('sendMessage', {'chat_id': chat_id, 'text': text, 'link_preview_options': {'is_disabled': True}}, timeout=15)
        except TgError:
            pass

    def handle_update(self, u):
        m = u.get('my_chat_member')
        if m and (m.get('new_chat_member') or {}).get('status') in ('left', 'kicked'):
            self.deactivate_subscriber((m.get('chat') or {}).get('id'))
            return
        msg = u.get('message') or {}
        text = (msg.get('text') or '').strip()
        chat = msg.get('chat') or {}
        mt = re.match(r'^/(start|join|leave|stop|help)(?:@\w+)?(?:\s+(.*))?$', text, re.S)
        if not mt or chat.get('id') is None:
            return
        cmd, arg, cid = mt.group(1), (mt.group(2) or '').strip(), chat['id']
        private = chat.get('type') == 'private'
        if cmd in ('leave', 'stop'):
            self.deactivate_subscriber(cid)
            self._say(cid, 'Подписка отключена: новые заявки сюда больше приходить не будут. Подключиться снова: /join КОД')
            return
        code = self.join_code()
        if cmd in ('join', 'start') and arg and code:
            hist = [t for t in self.bad_codes.get(cid, []) if time.time() - t < 600]
            if len(hist) >= 5:
                return                                  # слишком много неверных кодов: молчим
            if hmac.compare_digest(arg.encode(), code.encode()):
                title = chat.get('title') or ' '.join(x for x in (chat.get('first_name'), chat.get('last_name')) if x) or chat.get('username') or str(cid)
                self._upsert_subscriber(cid, title, chat.get('type') or '')
                self._say(cid, 'Готово: этот чат подписан на заявки JAQAIYM. Отписаться: /leave')
            else:
                hist.append(time.time()); self.bad_codes[cid] = hist
                self._say(cid, 'Неверный код. Попросите актуальный код у администратора сайта.')
            return
        if private or cmd == 'join':
            self._say(cid, 'Это бот заявок JAQAIYM. Чтобы получать заявки, отправьте /join КОД (код выдаёт администратор сайта).')

    def poll_loop(self):
        offset, first = None, True
        while True:
            if not self.token() or not self.join_code():
                time.sleep(15); continue
            try:
                if first:
                    try:
                        self.api('deleteWebhook', {}, timeout=15)       # getUpdates не работает, пока включён webhook
                    except TgError:
                        pass
                    first = False
                payload = {'timeout': POLL_TIMEOUT, 'allowed_updates': ['message', 'my_chat_member']}
                if offset is not None:
                    payload['offset'] = offset
                for u in self.api('getUpdates', payload, timeout=POLL_TIMEOUT + 15):
                    offset = u['update_id'] + 1
                    try:
                        self.handle_update(u)
                    except Exception as e:
                        self.log('poll: ошибка обработки: %r' % e)
            except TgError as e:
                self.log('poll: %s' % e)
                time.sleep(max(5, e.retry_after))

    # ---------- доставка заявки ----------
    def deliver_async(self, lead_id):
        threading.Thread(target=self.deliver, args=(lead_id,), daemon=True).start()

    def deliver(self, lead_id):
        with self.inflight_lock:
            if lead_id in self.inflight:
                return
            self.inflight.add(lead_id)
        try:
            self._deliver(lead_id)
        except Exception as e:
            self.log('deliver %s: %r' % (lead_id, e))
            self._fail(lead_id, 'Внутренняя ошибка: %s' % str(e)[:150], 0)
        finally:
            with self.inflight_lock:
                self.inflight.discard(lead_id)

    def _lead(self, lead_id):
        with self.lock:
            r = self.db.execute('SELECT * FROM leads WHERE id=?', (lead_id,)).fetchone()
            return dict(r) if r else None

    def _attachments(self, lead_id):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM attachments WHERE lead_id=? ORDER BY created_at, id', (lead_id,))]

    def _sent_items(self, lead_id, chat):
        with self.lock:
            return {r['item'] for r in self.db.execute('SELECT item FROM tg_sent WHERE lead_id=? AND chat_id=?', (lead_id, str(chat)))}

    def _targets(self, lead):
        if lead.get('tg_targets'):
            return json.loads(lead['tg_targets'])
        t = []
        if self.static_chat():
            t.append(self.static_chat())
        t += [s['chat_id'] for s in self.subscribers() if s['chat_id'] not in t]
        if not t:
            return None
        with self.lock:
            self.db.execute('UPDATE leads SET tg_targets=? WHERE id=?', (json.dumps(t), lead['id']))
            self.db.commit()
        return t

    def _set_targets(self, lead_id, targets):
        with self.lock:
            self.db.execute('UPDATE leads SET tg_targets=? WHERE id=?', (json.dumps(targets), lead_id))
            self.db.commit()

    def _fail(self, lead_id, error, retry_after):
        with self.lock:
            r = self.db.execute('SELECT notify_attempts FROM leads WHERE id=?', (lead_id,)).fetchone()
            n = (r['notify_attempts'] if r else 0) + 1
            delay = max(min(RETRY_BASE * (2 ** (n - 1)), 3600), (retry_after or 0) + 1)
            self.db.execute('UPDATE leads SET notify_attempts=?, notify_error=?, next_attempt_at=? WHERE id=?', (n, error[:300], iso_after(delay), lead_id))
            self.db.commit()

    def _done(self, lead_id, via):
        with self.lock:
            self.db.execute('UPDATE leads SET notified=1, notified_via=?, notify_error=NULL, next_attempt_at=NULL, notify_attempts=notify_attempts+1 WHERE id=?', (via, lead_id))
            self.db.commit()

    def _delete_file(self, att):
        with self.lock:
            r = self.db.execute('SELECT path FROM attachments WHERE id=?', (att['id'],)).fetchone()
            path = r['path'] if r else None
            self.db.execute('UPDATE attachments SET path=NULL, deleted_at=? WHERE id=?', (now(), att['id']))
            self.db.commit()
        if path:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                self.log('не удалось удалить %s: %r' % (path, e))

    def _release(self, lead_id):
        """Удаляет файлы заявки, которые уже дошли до всех её получателей."""
        lead = self._lead(lead_id)
        targets = json.loads(lead['tg_targets'] or '[]') if lead else []
        if not targets:
            return
        for a in self._attachments(lead_id):
            if not a['path']:
                continue
            with self.lock:
                got = {r['chat_id'] for r in self.db.execute('SELECT chat_id FROM tg_sent WHERE lead_id=? AND item=?', (lead_id, a['id']))}
            if all(t in got for t in targets):
                self._delete_file(a)

    def _mark(self, lead_id, chat, item):
        with self.lock:
            self.db.execute('INSERT OR IGNORE INTO tg_sent(lead_id,chat_id,item,sent_at) VALUES(?,?,?,?)', (lead_id, str(chat), item, now()))
            self.db.commit()
        if item != 'text':
            self._release(lead_id)

    def _read(self, att):
        with open(att['path'], 'rb') as f:
            return f.read()

    def _send_images(self, lead, chat, imgs):
        cap = 'Заявка №%d: фото' % lead['id']
        try:
            if len(imgs) == 1:
                a = imgs[0]
                self.api('sendPhoto', {'chat_id': chat, 'caption': cap}, [('photo', a['filename'] or 'photo', a['mime'], self._read(a))])
            else:
                media = [{'type': 'photo', 'media': 'attach://f%d' % i} for i in range(len(imgs))]
                media[0]['caption'] = cap
                self.api('sendMediaGroup', {'chat_id': chat, 'media': json.dumps(media)}, [('f%d' % i, a['filename'] or 'photo', a['mime'], self._read(a)) for i, a in enumerate(imgs)])
            for a in imgs:
                self._mark(lead['id'], chat, a['id'])
        except TgError as e:
            if e.code != 400 or e.migrate_to or e.permanent:
                raise
            for a in imgs:                           # Telegram не принял как фото (размер, пропорции, формат): шлём файлом
                self._send_doc(lead, chat, a)

    def _send_doc(self, lead, chat, a):
        self.api('sendDocument', {'chat_id': chat, 'caption': 'Заявка №%d: %s' % (lead['id'], a['filename'] or 'файл')},
                 [('document', a['filename'] or 'file', a['mime'], self._read(a))])
        self._mark(lead['id'], chat, a['id'])

    def _deliver_chat(self, lead, chat, text, atts):
        sent = self._sent_items(lead['id'], chat)
        if 'text' not in sent:
            self.api('sendMessage', {'chat_id': chat, 'text': text[:4000], 'link_preview_options': {'is_disabled': True}}, timeout=30)
            self._mark(lead['id'], chat, 'text')
        pend = [a for a in atts if a['path'] and not a['deleted_at'] and a['id'] not in sent]
        imgs = [a for a in pend if (a['mime'] or '').startswith('image/')]
        for i in range(0, len(imgs), 10):
            self._send_images(lead, chat, imgs[i:i + 10])
        for a in pend:
            if not (a['mime'] or '').startswith('image/'):
                self._send_doc(lead, chat, a)

    def _deliver(self, lead_id):
        lead = self._lead(lead_id)
        if not lead or lead['notified']:
            return
        atts = self._attachments(lead_id)
        text = self.text_fn(lead, len(atts))
        if not self.token():                         # тестовый режим без Telegram: пишем в outbox.log, файлы ждут срока хранения
            self.outbox(lead, text, atts)
            self._done(lead_id, 'outbox')
            return
        targets = self._targets(lead)
        if not targets:
            self._fail(lead_id, 'Нет получателей: подключите чат командой /join КОД или задайте TELEGRAM_CHAT_ID', 0)
            return
        errors, wait = [], 0
        for chat in list(targets):
            try:
                self._deliver_chat(lead, chat, text, atts)
            except TgError as e:
                wait = max(wait, e.retry_after)
                if e.migrate_to:                      # группу превратили в супергруппу: у неё новый id
                    new = str(e.migrate_to)
                    targets = [new if t == chat else t for t in targets]
                    self._set_targets(lead_id, targets)
                    with self.lock:
                        self.db.execute('UPDATE tg_sent SET chat_id=? WHERE lead_id=? AND chat_id=?', (new, lead_id, str(chat)))
                        self.db.execute('UPDATE tg_subscribers SET chat_id=? WHERE chat_id=?', (new, str(chat)))
                        self.db.commit()
                    errors.append('чат перенесён, повтор')
                elif e.permanent and str(chat) != self.static_chat():
                    self.log('получатель %s недоступен (%s): отключён' % (chat, e.desc))
                    self.deactivate_subscriber(chat)
                    targets = [t for t in targets if t != chat]
                    self._set_targets(lead_id, targets)
                else:
                    errors.append('Telegram %s: %s' % (e.code, e.desc))
        if errors:
            self._fail(lead_id, '; '.join(dict.fromkeys(errors)), wait)
            return
        if not targets:
            self._fail(lead_id, 'Все получатели недоступны: подключите чат командой /join КОД', 0)
            return
        for a in self._attachments(lead_id):         # всё доставлено: оставшиеся файлы заявки больше не нужны
            if a['path']:
                self._delete_file(a)
        self._done(lead_id, 'telegram')

    def outbox(self, lead, text, atts):
        names = ', '.join('%s (%d КБ)' % (a['filename'], round((a['size'] or 0) / 1024)) for a in atts)
        with open(os.path.join(os.path.dirname(self._db_path()), 'outbox.log'), 'a', encoding='utf-8') as f:
            f.write('--- %s ---\n%s%s\n\n' % (now(), text, ('\nФайлы: ' + names) if names else ''))

    def _db_path(self):
        with self.lock:
            return [r['file'] for r in self.db.execute('PRAGMA database_list') if r['name'] == 'main'][0]

    # ---------- фоновые циклы и чистка ----------
    def retry_loop(self):
        while True:
            time.sleep(RETRY_TICK)
            with self.lock:
                ids = [r['id'] for r in self.db.execute(
                    'SELECT id FROM leads WHERE notified=0 AND notify_attempts<? AND (next_attempt_at IS NULL OR next_attempt_at<=?)', (MAX_ATTEMPTS, now()))]
            for i in ids:
                self.deliver(i)

    def cleanup(self, uploads):
        """Удаляет загрузки без заявки, давно неотправленные файлы и «потерянные» файлы на диске."""
        removed = 0
        with self.lock:
            rows = [dict(r) for r in self.db.execute(
                'SELECT * FROM attachments WHERE path IS NOT NULL AND ((lead_id IS NULL AND created_at<?) OR (lead_id IS NOT NULL AND created_at<?))',
                (iso_before(ORPHAN_HOURS * 3600), iso_before(UNSENT_DAYS * 86400)))]
        for a in rows:
            self._delete_file(a); removed += 1
        with self.lock:
            known = {r['id'] for r in self.db.execute('SELECT id FROM attachments WHERE path IS NOT NULL')}
        for name in os.listdir(uploads):
            p = os.path.join(uploads, name)
            if name not in known and os.path.isfile(p) and time.time() - os.path.getmtime(p) > 3600:
                try:
                    os.remove(p); removed += 1
                except OSError:
                    pass
        return removed

    def cleanup_loop(self, uploads):
        while True:
            time.sleep(CLEAN_TICK)
            try:
                n = self.cleanup(uploads)
                if n:
                    self.log('очистка: удалено файлов: %d' % n)
            except Exception as e:
                self.log('очистка: %r' % e)

    def used_bytes(self):
        with self.lock:
            return self.db.execute('SELECT COALESCE(SUM(size),0) FROM attachments WHERE path IS NOT NULL').fetchone()[0]

    def start(self, uploads):
        for target, args in ((self.retry_loop, ()), (self.cleanup_loop, (uploads,)), (self.poll_loop, ())):
            threading.Thread(target=target, args=args, daemon=True).start()

    def resend(self, lead_id):
        """Кнопка «Повторить отправку»: дошедшее не дублируется, досылается только недостающее."""
        with self.lock:
            self.db.execute('UPDATE leads SET notified=0, notify_attempts=0, next_attempt_at=NULL WHERE id=?', (lead_id,))
            self.db.commit()
        self.deliver_async(lead_id)
