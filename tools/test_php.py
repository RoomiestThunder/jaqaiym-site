#!/usr/bin/env python3
"""Автотест PHP-версии сервера заявок на подставном Telegram (настоящий токен не нужен).

  python3 tools/test_php.py

Те же сценарии, что в test_telegram.py для версии на Python, плюс то, что есть только у PHP:
подписчики приходят через вебхук (а не long-poll), повторы и очистку делает cron.php, в админку входят по паролю.
  A  текст + альбом фото + PDF доходят, файлы удаляются, выдача удалённого файла = 410
  B  подписчики по /join КОД: неверный код отклонён, рассылка всем, при сбое у одного нет дублей
  C  заблокировавший бота подписчик отключается и не мешает остальным
  D  Telegram не принял альбом как фото: уходит файлами
  E  загрузка без заявки удаляется; квота диска (507)
  F  отписка; G  нет получателей: заявка ждёт, после /start доставляется; H  без токена бота: outbox.log
"""
import json, os, re, sys, threading, urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract  # noqa: E402
import php_harness as H  # noqa: E402

T = H.T
check, wait, sent, Mock = T.check, T.wait, T.sent, T.Mock
PNG, JPG, PDF = T.PNG, T.JPG, T.PDF


def missing_page_refs(root, path):
    """Ссылки href/src на странице, которые ведут на несуществующий файл сборки."""
    refs = re.findall(r'(?:href|src)="(/[^"#?]*)', open(path, encoding='utf-8').read())
    local = [r for r in refs if not r.startswith(('//', '/api', '/admin'))]
    targets = [(r, os.path.join(root, r.lstrip('/'))) for r in local]
    return ['%s -> %s' % (os.path.relpath(path, root), r) for r, t in targets
            if not (os.path.isfile(t) or os.path.isfile(os.path.join(t, 'index.html')))]


def missing_style_refs(root, path):
    """url() в стилях (шрифты, картинки), которые ведут на несуществующий файл."""
    refs = [r.strip('\'"') for r in re.findall(r'url\(([^)]+)\)', open(path, encoding='utf-8').read())]
    return ['%s -> %s' % (os.path.relpath(path, root), r) for r in refs
            if not r.startswith('data:') and not os.path.isfile(os.path.normpath(os.path.join(os.path.dirname(path), r)))]


def broken_links(dist):
    root, bad = os.path.join(dist, 'httpdocs'), []
    for dp, _, fs in os.walk(root):
        for f in fs:
            if f.endswith('.html'):
                bad += missing_page_refs(root, os.path.join(dp, f))
            elif f.endswith('.css'):
                bad += missing_style_refs(root, os.path.join(dp, f))
    return bad


def main():
    httpd = ThreadingHTTPServer(('127.0.0.1', 8132), Mock)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    S = H.PhpSrv(8133, TELEGRAM_BOT_TOKEN='TESTTOKEN', TELEGRAM_CHAT_ID='111', TELEGRAM_JOIN_CODE='secret123', CORS_ORIGINS='https://roomiestthunder.github.io')
    try:
        print('A. текст + альбом + PDF, файлы удаляются')
        ids = [S.upload('a.png', PNG())[1]['id'], S.upload('b.png', PNG())[1]['id'], S.upload('c.jpg', JPG())[1]['id'], S.upload('план.pdf', PDF())[1]['id']]
        check(len(S.disk()) == 4, 'до отправки на диске 4 файла')
        lid = S.lead(ids)
        check(wait(lambda: S.lead_row(lid)['notified'] == 1), 'заявка помечена доставленной')
        text = sent('sendMessage', 111, lid)
        check(len(text) == 1 and 'Файлы: 4' in text[0]['text'], 'одно текстовое сообщение, в нём указано число файлов')
        check('%s#lead-%d' % (H.ADMIN_PATH, lid) in text[0]['text'] and H.ADMIN not in text[0]['text'] and 'token=' not in text[0]['text'], 'ссылка на карточку без пароля и токена')
        g = sent('sendMediaGroup', 111, lid)
        check(len(g) == 1 and len(g[0]['files']) == 3, 'фото ушли одним альбомом (3 шт.)')
        d = sent('sendDocument', 111, lid)
        check(len(d) == 1 and d[0]['files'][0][1] == 'план.pdf', 'PDF ушёл документом с исходным именем')
        check(S.disk() == [], 'после отправки на диске файлов нет')
        check(S.lead_row(lid)['notified_via'] == 'telegram', 'способ доставки: telegram')
        cookie, csrf = S.session()
        check(S.req('/api/files/%s' % ids[0], headers={'Cookie': cookie})[0] == 410, 'удалённый файл отдаётся как 410')
        check(all(r['deleted_at'] for r in S.sql('SELECT deleted_at FROM attachments')), 'в базе файлы помечены удалёнными')
        page = S.admin_get(H.ADMIN_PATH, cookie)[2].decode()
        check('отправлен в Telegram и удалён с сервера' in page and 'доставлено в Telegram' in page, 'админка показывает доставку и удалённые файлы')

        print('A2. CORS: страница с github.io может слать заявки')
        def opt(origin):
            r = urllib.request.Request('http://127.0.0.1:8133/api/leads', method='OPTIONS', headers={'Origin': origin, 'Access-Control-Request-Method': 'POST'})
            with urllib.request.urlopen(r, timeout=5) as x:
                return x.status, x.headers
        st, h = opt('https://roomiestthunder.github.io')
        check(st == 204 and h.get('Access-Control-Allow-Origin') == 'https://roomiestthunder.github.io' and 'Content-Type' in h.get('Access-Control-Allow-Headers', ''), 'предзапрос с github.io разрешён')
        check('Access-Control-Allow-Origin' not in opt('https://evil.example')[1], 'чужой адрес не получает разрешения')

        print('B. подписчики через вебхук и частичный сбой')
        S.join(222, '/join@jq_test_bot secret123'); S.join(-1003, '/join secret123', 'supergroup', 'Команда'); S.join(444, '/join wrong')
        check(wait(lambda: len(S.sql('SELECT * FROM tg_subscribers WHERE active=1')) == 2), 'по верному коду подписались личный чат и группа')
        check(any('Неверный код' in e['text'] for e in sent('sendMessage', 444)), 'неверный код отклонён, подписки нет')
        Mock.fail[('sendMediaGroup', '222')] = [(429, 'Too Many Requests: retry after 1', 1)]
        ids = [S.upload('x.png', PNG())[1]['id'], S.upload('y.png', PNG())[1]['id']]
        lid = S.lead(ids)
        check(wait(lambda: S.lead_row(lid)['notified'] == 1, 25), 'после сбоя у одного получателя заявка доставлена повтором (cron)')
        for ch in ('111', '222', '-1003'):
            check(len(sent('sendMessage', ch, lid)) == 1, 'чат %s получил текст ровно один раз' % ch)
            check(len(sent('sendMediaGroup', ch, lid)) == 1, 'чат %s получил альбом ровно один раз' % ch)
        check(S.disk() == [], 'файлы удалены только после доставки всем')

        print('C. заблокировавший бота подписчик')
        S.join(555, '/join secret123')
        check(wait(lambda: len(S.sql('SELECT * FROM tg_subscribers WHERE active=1')) == 3), 'ещё один подписчик')
        Mock.fail[('sendMessage', '555')] = [(403, 'Forbidden: bot was blocked by the user', 0)]
        lid = S.lead([S.upload('z.png', PNG())[1]['id']])
        check(wait(lambda: S.lead_row(lid)['notified'] == 1), 'заявка доставлена остальным')
        check(S.sql('SELECT active FROM tg_subscribers WHERE chat_id=?', '555')[0]['active'] == 0, 'недоступный подписчик отключён')
        check(S.disk() == [], 'файлы удалены')

        print('D. альбом не принят как фото')
        Mock.fail[('sendMediaGroup', '111')] = [(400, 'Bad Request: PHOTO_INVALID_DIMENSIONS', 0)]
        lid = S.lead([S.upload('big1.png', PNG())[1]['id'], S.upload('big2.png', PNG())[1]['id']])
        check(wait(lambda: S.lead_row(lid)['notified'] == 1), 'заявка доставлена')
        check(len(sent('sendDocument', 111, lid)) == 2, 'в чат 111 изображения ушли файлами (запасной путь)')
        check(S.disk() == [], 'файлы удалены')

        print('E. очистка и квота')
        orphan = S.upload('orphan.jpg', JPG())[1]['id']
        check(orphan in S.disk(), 'загрузка без заявки лежит на диске')
        check(wait(lambda: orphan not in S.disk(), 15), 'через ORPHAN_HOURS загрузка без заявки удалена (cron)')
        big = b'\xff\xd8\xff\xe0' + os.urandom(150000)
        check(S.upload('big.jpg', big)[0] == 201, 'файл в пределах квоты принят')
        st, d = S.upload('big2.jpg', big)
        check(st == 507 and d.get('error') == 'storage_full', 'сверх квоты отказ 507 storage_full')
        check(wait(lambda: S.disk() == [], 15), 'после очистки место освободилось')
        check(S.upload('again.jpg', JPG())[0] == 201, 'загрузка снова принимается')

        print('F. отписка')
        S.join(222, '/leave')
        check(wait(lambda: S.sql('SELECT active FROM tg_subscribers WHERE chat_id=?', '222')[0]['active'] == 0), '/leave отключает подписку')

        print('F2. кнопка «Повторить отправку» и вебхук')
        lid = S.lead()
        check(wait(lambda: S.lead_row(lid)['notified'] == 1), 'заявка без файлов доставлена')
        before = len(sent('sendMessage', 111, lid))
        st, d = S.admin_post('/api/admin/leads/%d/resend' % lid, cookie, csrf)
        check(st == 200 and wait(lambda: S.lead_row(lid)['notified'] == 1), 'повторная отправка по кнопке отработала')
        check(len(sent('sendMessage', 111, lid)) == before, 'дошедшее второй раз не дублируется')
        st, d = S.admin_post('/api/admin/webhook/set', cookie, csrf)
        check(st == 200 and Mock.webhook.get('url') == 'http://127.0.0.1:8133/api/tg/webhook' and Mock.webhook.get('secret_token') == H.WEBHOOK_SECRET, 'кнопка «подключить вебхук» передаёт Telegram адрес и секрет')
        check('Вебхук подключён' in S.admin_get(H.ADMIN_PATH, cookie)[2].decode(), 'админка показывает, что вебхук подключён')
    finally:
        S.stop()

    print('G. нет получателей: заявка ждёт подписчика')
    S2 = H.PhpSrv(8134, TELEGRAM_BOT_TOKEN='TESTTOKEN', TELEGRAM_JOIN_CODE='secret123')
    try:
        ids = [S2.upload('w.png', PNG())[1]['id']]
        lid = S2.lead(ids)
        check(wait(lambda: 'Нет получателей' in (S2.lead_row(lid)['notify_error'] or '')), 'без получателей заявка ждёт, причина видна')
        check(S2.disk() == ids, 'файл пока лежит на диске')
        S2.join(777, '/start secret123')
        ok = wait(lambda: S2.lead_row(lid)['notified'] == 1, 20)
        check(ok, 'после подписки заявка доставлена')
        if not ok:
            print('   отладка:', {k: S2.lead_row(lid)[k] for k in ('notified', 'notify_attempts', 'notify_error', 'next_attempt_at', 'tg_targets')}, '\n   log:', S2.log())
        check(len(sent('sendPhoto', 777, lid)) == 1, 'одно фото ушло методом sendPhoto')
        check(wait(lambda: S2.disk() == []), 'файл удалён')
    finally:
        S2.stop()

    print('H. без токена бота (тестовый режим)')
    S3 = H.PhpSrv(8135)
    try:
        ids = [S3.upload('t.png', PNG())[1]['id']]
        lid = S3.lead(ids)
        check(wait(lambda: S3.lead_row(lid)['notified'] == 1), 'заявка записана в outbox')
        check(S3.lead_row(lid)['notified_via'] == 'outbox' and os.path.exists(os.path.join(S3.dir, 'outbox.log')), 'способ: outbox, файл outbox.log создан')
        check(S3.disk() == ids, 'файлы остаются до срока хранения')
        check(S3.push({'update_id': 1, 'message': {'text': '/join x', 'chat': {'id': 1, 'type': 'private'}}})[0] == 404, 'вебхук без токена бота отключён (404)')
        print('I. целостность сборки')
        bad = broken_links(H.dist())
        check(not bad, 'все ссылки страниц и url() в стилях (шрифты, картинки) ведут на существующие файлы: %s' % bad[:5])
        check(S3.raw('GET', '/fonts/manrope-latin.woff2')[0] == 200, 'шрифт отдаётся с сервера (200)')
        contract.run(S3, check)
    finally:
        S3.stop()
        httpd.shutdown()
        H.drop_dist()
    print('\nИтог: %d проверок пройдено, %d провалено' % (T.OKS, len(T.FAILS)))
    for f in T.FAILS:
        print('  - ' + f)
    sys.exit(1 if T.FAILS else 0)


if __name__ == '__main__':
    main()
