<?php
declare(strict_types=1);

namespace Jq;

/** HTML админки. Любые данные заявок экранируются; скрипты и стили — только с одноразовым nonce (см. CSP в AdminController). */
final class AdminPage
{
    private const CSS = 'body{font:15px/1.5 system-ui,sans-serif;background:#f5efe3;color:#2e1a10;margin:0;padding:24px;max-width:860px;margin:auto}'
        . 'h1{font-size:22px}h2{font-size:17px;margin:0 0 8px}article,.tg,.box{background:#fff;border-radius:14px;padding:18px 20px;margin:14px 0;box-shadow:0 1px 0 #0001}'
        . 'article:target{outline:2px solid #b65c37}header{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.t{color:#8a7a6c}'
        . '.tag{background:#eadfce;border-radius:99px;padding:2px 10px;font-size:12px}select{margin-left:auto;padding:6px}.s{font-size:16px;white-space:pre-line}'
        . '.f a,.f .gone{display:inline-block;margin:0 10px 6px 0;background:#f5efe3;padding:4px 10px;border-radius:8px;color:#2e1a10}.f .gone{color:#8a7a6c}'
        . '.m{color:#8a7a6c;font-size:13px}code{background:#f5efe3;padding:1px 5px;border-radius:5px}button{cursor:pointer;margin-left:6px}ul{margin:6px 0;padding-left:20px}'
        . '.top{display:flex;justify-content:space-between;align-items:center}.err{color:#a3261b}.ok{color:#2b7a3d}.bad{color:#a3261b}input[type=password],input[name=code]{padding:8px;width:100%;box-sizing:border-box;margin:8px 0}';

    private static function e(mixed $s): string
    {
        return htmlspecialchars((string)$s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    }

    private static function shell(string $title, string $nonce, string $body, string $script = ''): string
    {
        return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            . '<meta name="robots" content="noindex,nofollow"><meta name="color-scheme" content="only light"><title>' . self::e($title) . '</title>'
            . '<style nonce="' . self::e($nonce) . '">' . self::CSS . '</style>' . $body
            . ($script !== '' ? '<script nonce="' . self::e($nonce) . '">' . $script . '</script>' : '');
    }

    /** @param ?string $disabled причина отключения админки (null: включена); $totp: запрашивать ли одноразовый код */
    public static function login(string $nonce, ?string $error, ?string $disabled, string $action, bool $totp): string
    {
        $body = '<div class="box"><h1>JAQAIYM: вход для команды</h1>';
        if ($disabled !== null) {
            $body .= '<p class="err">Админка отключена: ' . self::e($disabled) . '.</p></div>';
        } else {
            $code = $totp ? '<label>Код из приложения-аутентификатора<input type="text" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" required></label>' : '';
            $body .= ($error !== null ? '<p class="err">' . self::e($error) . '</p>' : '')
                . '<form method="post" action="' . self::e($action) . '"><label>Пароль<input type="password" name="password" autocomplete="current-password" autofocus required></label>'
                . $code . '<button type="submit">Войти</button></form></div>';
        }
        return self::shell('Вход: JAQAIYM', $nonce, $body);
    }

    /**
     * @param array<string,mixed> $c leads, tg, diag, status (подписи статусов), csrf
     */
    public static function dashboard(array $c, string $nonce): string
    {
        $cards = array_map(fn(array $l) => self::card($l, $c['status']), $c['leads']);
        $body = '<div class="top"><h1>Заявки (' . count($cards) . ')</h1><button data-act="' . self::e($c['logout_url']) . '">Выйти</button></div>'
            . self::telegram($c['tg'], $c['diag'])
            . ($cards ? implode('', $cards) : '<p>Заявок пока нет.</p>')
            . self::diag($c['diag']);
        $script = "(function(){var csrf=" . json_encode($c['csrf']) . ";"
            . "function post(u,b){return fetch(u,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(b||{})});}"
            . "document.addEventListener('click',function(e){var b=e.target.closest('[data-act]');if(!b)return;"
            . "post(b.getAttribute('data-act')).then(function(r){if(!r.ok){alert('Не получилось: '+r.status);return}location.reload()})});"
            . "document.addEventListener('change',function(e){var s=e.target.closest('select[data-status]');if(!s)return;"
            . "post('/api/admin/leads/'+s.getAttribute('data-status')+'/status',{status:s.value}).then(function(r){if(!r.ok)alert('Не получилось: '+r.status)})});})();";
        return self::shell('Заявки JAQAIYM', $nonce, $body, $script);
    }

    /** @param array<string,mixed> $l @param array<string,string> $statuses */
    private static function card(array $l, array $statuses): string
    {
        $c = $l['payload']['customer'] ?? [];
        $src = $l['payload']['source'] ?? [];
        $opts = '';
        foreach ($statuses as $k => $v) {
            $opts .= '<option value="' . self::e($k) . '"' . ($k === $l['status'] ? ' selected' : '') . '>' . self::e($v) . '</option>';
        }
        $files = '';
        foreach ($l['files'] as $f) {
            $name = self::e($f['filename'] ?: 'файл');
            $files .= $f['on_disk']
                ? '<a href="/api/files/' . self::e($f['id']) . '" target="_blank" rel="noopener">' . $name . '</a>'
                : '<span class="gone">' . $name . ': ' . ($l['notified'] ? 'отправлен в Telegram и удалён с сервера' : 'удалён с сервера, не отправлен') . '</span>';
        }
        $time = $c['preferred_time'] ?? '';
        return '<article id="lead-' . (int)$l['id'] . '"><header><b>№' . (int)$l['id'] . '</b> <span class="t">' . self::e(substr(str_replace('T', ' ', (string)$l['created_at']), 0, 16))
            . '</span><span class="tag">' . ($l['lead_type'] === 'quick' ? 'быстрая' : 'проект') . '</span><select data-status="' . (int)$l['id'] . '">' . $opts . '</select></header>'
            . '<p class="s">' . self::e($l['summary']) . '</p>'
            . '<p><b>' . self::e($c['name'] ?? '—') . '</b> · <a href="tel:' . self::e($c['phone'] ?? '') . '">' . self::e($c['phone'] ?? '') . '</a> · '
            . self::e($l['channel_label']) . ($time !== '' ? ' · удобно: ' . self::e($time) : '') . '</p>'
            . '<p class="f">' . ($files ?: '<i>файлов нет</i>') . '</p>'
            . '<p class="m">Источник: ' . self::e($src['page'] ?? '—') . ' ' . self::e(is_string($src['project_id'] ?? null) ? $src['project_id'] : '') . ' · ' . self::delivery($l) . '</p></article>';
    }

    /** @param array<string,mixed> $l */
    private static function delivery(array $l): string
    {
        if ((int)$l['notified'] === 1) {
            return $l['notified_via'] === 'telegram' ? 'доставлено в Telegram' : 'записано в outbox.log (тест, без Telegram)';
        }
        $next = $l['next_attempt_at'] ? ', следующая после ' . self::e(substr(str_replace('T', ' ', (string)$l['next_attempt_at']), 0, 16)) . ' UTC' : '';
        return '<span class="bad">НЕ доставлено: ' . self::e($l['notify_error'] ?: 'ожидает отправки') . ' · попыток: ' . (int)$l['notify_attempts'] . $next . '</span>'
            . ' <button data-act="/api/admin/leads/' . (int)$l['id'] . '/resend">повторить отправку</button>';
    }

    /** @param array<string,mixed> $t @param array<string,mixed> $d */
    private static function telegram(array $t, array $d): string
    {
        $h = '<section class="tg"><h2>Telegram</h2>';
        if (!$t['enabled']) {
            return $h . '<p>Бот не подключён: задайте <code>TELEGRAM_BOT_TOKEN</code>. Сейчас уведомления пишутся в <code>outbox.log</code>, файлы хранятся '
                . self::e($t['unsent_days']) . ' сут.</p>' . self::space($d) . '</section>';
        }
        $h .= '<p>Бот: ' . ($t['bot'] ? '<b>@' . self::e($t['bot']) . '</b>' : 'проверка…') . ($t['chat'] !== '' ? ' · общий чат: <code>' . self::e($t['chat']) . '</code>' : '') . '</p>';
        if ($t['join_code'] && $t['bot']) {
            $h .= '<p>Пригласить в личные сообщения: <a href="https://t.me/' . self::e($t['bot']) . '?start=' . self::e($t['join_code']) . '">ссылка</a><br>'
                . 'Добавить бота в группу: <a href="https://t.me/' . self::e($t['bot']) . '?startgroup=' . self::e($t['join_code']) . '">ссылка</a><br>'
                . '<span class="m">Ссылки содержат секретный код: отправляйте только сотрудникам. Либо командой <code>/join КОД</code>.</span></p>';
        } elseif (!$t['join_code']) {
            $h .= '<p class="m">Чтобы подписчики подключались сами, задайте <code>TELEGRAM_JOIN_CODE</code> (секретный код).</p>';
        }
        $h .= self::webhook($t['webhook'], $t['webhook_url']);
        $subs = '';
        foreach ($t['subs'] as $s) {
            $subs .= '<li>' . self::e($s['title'] ?: $s['chat_id']) . ' <span class="m">(' . self::e($s['kind'] ?? '') . ')</span>'
                . ' <button data-act="/api/admin/subscribers/' . self::e($s['chat_id']) . '/remove">отключить</button></li>';
        }
        $none = 'нет подписчиков' . ($t['chat'] !== '' ? '' : ' и не задан общий чат: заявки ждут получателя');
        return $h . '<p>Получатели: ' . ($subs !== '' ? '<ul>' . $subs . '</ul>' : $none) . '</p>' . self::space($d) . '</section>';
    }

    /** @param array<string,mixed>|null $w ответ getWebhookInfo; null, если проверить не удалось */
    private static function webhook(?array $w, string $url): string
    {
        $btn = ' <button data-act="/api/admin/webhook/set">подключить вебхук</button>';
        if ($w === null) {
            return '<p class="bad">Вебхук: не удалось проверить (нет связи с Telegram).</p>';
        }
        if (($w['url'] ?? '') !== $url) {
            return '<p class="bad">Вебхук: не подключён. Без него бот не увидит команду /join.' . $btn . '</p>';
        }
        $problem = !empty($w['last_error_message']) ? ' · <span class="bad">последняя ошибка: ' . self::e($w['last_error_message']) . '</span>' : '';
        return '<p class="ok">Вебхук подключён</p><p class="m">Ожидают обработки: ' . (int)($w['pending_update_count'] ?? 0) . $problem . '</p>';
    }

    /** @param array<string,mixed> $d */
    private static function space(array $d): string
    {
        return '<p class="m">Временные файлы на диске: ' . sprintf('%.1f', $d['used'] / 1048576) . ' МБ из ' . sprintf('%.0f', $d['quota'] / 1048576)
            . ' МБ (после отправки в Telegram удаляются).</p>';
    }

    /** @param array<string,mixed> $d */
    private static function diag(array $d): string
    {
        $ext = '';
        foreach ($d['ext'] as $name => $ok) {
            $ext .= ' <code class="' . ($ok ? 'ok' : 'bad') . '">' . self::e($name) . ($ok ? '' : ' нет') . '</code>';
        }
        $rows = '';
        foreach ($d['ini'] as $k => $v) {
            $rows .= self::e($k) . '=' . self::e($v) . ' · ';
        }
        return '<section class="tg"><h2>Состояние сервера</h2><p class="m">PHP ' . self::e($d['php']) . ' (' . self::e($d['sapi']) . ')<br>Расширения:' . $ext
            . '<br>' . rtrim($rows, ' ·')
            . ($d['post_ok'] ? '' : '<br><b class="bad">post_max_size меньше ' . ($d['max_file_mb'] + 1) . ' МБ: фото крупнее лимита не загрузятся. Увеличьте в настройках PHP (Plesk → PHP).</b>')
            . '<br>Данные вне корня сайта: <b class="' . ($d['outside'] ? 'ok">да' : 'bad">НЕТ') . '</b>'
            . '<br>Свободно на диске: ' . sprintf('%.0f', $d['free'] / 1048576) . ' МБ'
            . '<br>Вход: ' . ($d['two_factor'] ? '<b class="ok">пароль и одноразовый код (2FA включена)</b>' : '<b class="bad">только пароль: включите 2FA (ADMIN_TOTP_SECRET)</b>')
            . ' · адрес админки: ' . ($d['admin_path'] === '/admin' ? '<b class="bad">стандартный /admin (смените ADMIN_PATH)</b>' : '<b class="ok">нестандартный</b>')
            . '<br>Ваш адрес по данным сервера: <b>' . self::e($d['client_ip']) . '</b> (REMOTE_ADDR ' . self::e($d['remote_addr']) . '). Если здесь адрес самого сервера, лимиты запросов считаются на всех посетителей вместе.</p></section>';
    }
}
