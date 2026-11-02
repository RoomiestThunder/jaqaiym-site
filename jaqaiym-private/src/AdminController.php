<?php
declare(strict_types=1);

namespace Jq;

/** Админка: вход, список заявок, действия, скачивание файлов. Всё, кроме входа, требует подписанной cookie. */
final class AdminController
{
    private const BOT_CACHE_SECONDS = 3600;
    private const INLINE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

    public function __construct(private readonly Services $s)
    {
    }

    public function page(): void
    {
        $nonce = base64_encode(random_bytes(16));
        header("Content-Security-Policy: default-src 'none'; style-src 'nonce-$nonce'; script-src 'nonce-$nonce'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
        if (!$this->s->auth->valid()) {
            Http::html($this->s->cfg->adminEnabled() ? 200 : 503, $this->loginPage($nonce, null));
            return;
        }
        Http::html(200, AdminPage::dashboard($this->dashboardData(), $nonce));
    }

    public function login(): void
    {
        $nonce = base64_encode(random_bytes(16));
        header("Content-Security-Policy: default-src 'none'; style-src 'nonce-$nonce'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
        $cfg = $this->s->cfg;
        if (!$cfg->adminEnabled()) {
            Http::html(503, $this->loginPage($nonce, null));
            return;
        }
        if (!Http::originAllowed($cfg, false)) {
            Http::html(403, $this->loginPage($nonce, 'Запрос отклонён.'));
            return;
        }
        $ip = Http::ip();
        if ($this->s->auth->loginBlocked($ip)) {
            Http::html(429, $this->loginPage($nonce, 'Слишком много неудачных попыток входа. Подождите 15 минут.'));
            return;
        }
        if (!$this->s->auth->passwordOk(self::postString('password'))) {
            $this->s->auth->loginFailed($ip);
            usleep(400000); // замедляет перебор
            Http::html(401, $this->loginPage($nonce, 'Неверный пароль.'));
            return;
        }
        $this->s->auth->grant();
        Http::redirect($cfg->adminPath);
    }

    private function loginPage(string $nonce, ?string $error): string
    {
        $cfg = $this->s->cfg;
        return AdminPage::login($nonce, $error, $cfg->adminProblem, $cfg->adminPath . '/login');
    }

    private static function postString(string $key): string
    {
        $value = $_POST[$key] ?? '';
        return is_string($value) ? $value : '';
    }

    public function logout(): void
    {
        if (!$this->guard()) {
            return;
        }
        $this->s->auth->revoke();
        Http::json(200, ['ok' => true]);
    }

    /** Проверка доступа для действий админки: вход, а для POST ещё и токен защиты от подделки запроса. */
    private function guard(bool $changes = true): bool
    {
        $ok = $changes ? $this->s->auth->csrfOk() : $this->s->auth->valid();
        if (!$ok) {
            Http::json(403, ['error' => 'forbidden']);
        }
        return $ok;
    }

    public function leadsJson(): void
    {
        if ($this->guard(false)) {
            Http::json(200, ['leads' => $this->s->leads->rows()]);
        }
    }

    public function setStatus(int $id): void
    {
        if (!$this->guard()) {
            return;
        }
        $body = json_decode((string)Http::body(1000), true);
        $status = is_array($body) ? ($body['status'] ?? null) : null;
        if (!$this->s->schema->has('status', $status)) {
            Http::json(422, ['error' => 'bad_status']);
            return;
        }
        $this->s->leads->setStatus($id, (string)$status);
        Http::json(200, ['ok' => true]);
    }

    public function resend(int $id): void
    {
        if (!$this->guard()) {
            return;
        }
        $this->s->notifier->reset($id);
        Http::finish(200, ['ok' => true]);
        $this->s->notifier->deliver($id);
    }

    public function removeSubscriber(string $chatId): void
    {
        if ($this->guard()) {
            $this->s->subs->deactivate($chatId);
            Http::json(200, ['ok' => true]);
        }
    }

    public function setWebhook(): void
    {
        if (!$this->guard()) {
            return;
        }
        $cfg = $this->s->cfg;
        try {
            $this->s->tg->call('setWebhook', [
                'url' => $cfg->baseUrl . '/api/tg/webhook', 'secret_token' => $cfg->webhookSecret,
                'allowed_updates' => ['message', 'my_chat_member'], 'drop_pending_updates' => false,
            ], [], 15);
            Http::json(200, ['ok' => true]);
        } catch (TgError $e) {
            Http::json(502, ['error' => 'telegram', 'message' => $e->desc]);
        }
    }

    public function file(string $id): void
    {
        if (!$this->guard(false)) {
            return;
        }
        $row = $this->s->db->one('SELECT * FROM attachments WHERE id=?', [$id]);
        if ($row === null) {
            Http::json(404, ['error' => 'not_found']);
            return;
        }
        $path = $this->s->files->path($id);
        if ($row['path'] === null || !is_file($path)) {
            Http::json(410, ['error' => 'deleted', 'message' => 'Файл уже отправлен в Telegram и удалён с сервера']);
            return;
        }
        $mime = in_array($row['mime'], [...self::INLINE_TYPES, 'application/pdf'], true) ? (string)$row['mime'] : 'application/octet-stream';
        header('Content-Type: ' . $mime);
        header('Content-Length: ' . filesize($path));
        header("Content-Security-Policy: default-src 'none'; sandbox");
        header("Content-Disposition: " . (in_array($mime, self::INLINE_TYPES, true) ? 'inline' : 'attachment') . "; filename*=UTF-8''" . rawurlencode((string)($row['filename'] ?: 'file')));
        readfile($path);
    }

    /** @return array<string,mixed> */
    private function dashboardData(): array
    {
        $schema = $this->s->schema;
        $leads = $this->s->leads->rows();
        foreach ($leads as &$l) {
            $l['summary'] = $this->s->summary->make($l['payload']);
            $ch = $l['payload']['customer']['preferred_channel'] ?? null;
            $l['channel_label'] = $ch ? $schema->lab('channel', $ch) : 'способ не указан';
        }
        return [
            'leads' => $leads, 'status' => $schema->group('status'), 'csrf' => $this->s->auth->csrf(),
            'tg' => $this->telegramInfo(), 'diag' => $this->diagnostics(), 'logout_url' => $this->s->cfg->adminPath . '/logout',
        ];
    }

    /** @return array<string,mixed> */
    private function telegramInfo(): array
    {
        $cfg = $this->s->cfg;
        $enabled = $this->s->tg->enabled();
        $webhook = null;
        if ($enabled) {
            try {
                $webhook = $this->s->tg->call('getWebhookInfo', [], [], 8);
            } catch (TgError) {
                $webhook = null;
            }
        }
        return [
            'enabled' => $enabled, 'bot' => $enabled ? $this->botUsername() : null, 'chat' => $cfg->chatId, 'join_code' => $cfg->joinCode,
            'subs' => $this->s->subs->all(), 'webhook' => is_array($webhook) ? $webhook : null, 'webhook_url' => $cfg->baseUrl . '/api/tg/webhook',
            'unsent_days' => sprintf('%g', $cfg->unsentDays),
        ];
    }

    private function botUsername(): ?string
    {
        $row = $this->s->db->one("SELECT v FROM kv WHERE k='bot_username'");
        $cached = $row ? json_decode((string)$row['v'], true) : null;
        if (is_array($cached) && time() - (int)$cached['at'] < self::BOT_CACHE_SECONDS) {
            return $cached['name'] ?: null;
        }
        try {
            $me = $this->s->tg->call('getMe', [], [], 8);
        } catch (TgError) {
            return null;
        }
        $name = is_array($me) ? (string)($me['username'] ?? '') : '';
        $this->s->db->run("INSERT OR REPLACE INTO kv(k,v) VALUES('bot_username',?)", [json_encode(['name' => $name, 'at' => time()])]);
        return $name ?: null;
    }

    /** Значение вида «16M» из настроек PHP в байтах. */
    private static function iniBytes(string $v): int
    {
        $n = (int)$v;
        return match (strtolower(substr(trim($v), -1))) {
            'g' => $n * 1073741824,
            'm' => $n * 1048576,
            'k' => $n * 1024,
            default => $n,
        };
    }

    /** @return array<string,mixed> */
    private function diagnostics(): array
    {
        $cfg = $this->s->cfg;
        $schema = $this->s->schema;
        $data = realpath($cfg->dataDir) ?: $cfg->dataDir;
        $pub = realpath($cfg->publicDir) ?: $cfg->publicDir;
        return [
            'php' => PHP_VERSION, 'sapi' => PHP_SAPI,
            'ext' => [
                'curl' => extension_loaded('curl'), 'pdo_sqlite' => extension_loaded('pdo_sqlite'), 'mbstring' => extension_loaded('mbstring'),
                'openssl' => extension_loaded('openssl'), 'fastcgi_finish_request' => function_exists('fastcgi_finish_request'),
            ],
            'ini' => array_combine($k = ['memory_limit', 'max_execution_time', 'post_max_size', 'upload_max_filesize'], array_map('ini_get', $k)),
            'post_ok' => self::iniBytes((string)ini_get('post_max_size')) >= ((int)$schema->limits()['max_file_mb'] + 1) * 1048576,
            'max_file_mb' => (int)$schema->limits()['max_file_mb'],
            'outside' => !str_starts_with($data . '/', rtrim($pub, '/') . '/'),
            'free' => $this->s->files->freeBytes(), 'used' => $this->s->files->usedBytes(), 'quota' => $cfg->quotaBytes,
            'client_ip' => Http::ip(), 'remote_addr' => (string)($_SERVER['REMOTE_ADDR'] ?? ''),
        ];
    }
}
