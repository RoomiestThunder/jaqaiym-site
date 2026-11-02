<?php
declare(strict_types=1);

namespace Jq;

/** Все настройки приложения в одном неизменяемом объекте. */
final class Config
{
    public const MIN_ADMIN_SECRET = 16;

    /** @param list<string> $corsOrigins */
    public function __construct(
        public readonly string $privateDir,
        public readonly string $publicDir,
        public readonly string $dataDir,
        public readonly string $uploadsDir,
        public readonly string $baseUrl,
        public readonly string $adminSecret,
        public readonly string $botToken,
        public readonly string $chatId,
        public readonly string $joinCode,
        public readonly string $apiBase,
        public readonly string $webhookSecret,
        public readonly array $corsOrigins,
        public readonly int $quotaBytes,
        public readonly int $minFreeBytes,
        public readonly int $maxAttempts,
        public readonly int $retentionDays,
        public readonly int $rateLeads,
        public readonly int $rateUploads,
        public readonly float $retryBase,
        public readonly float $orphanHours,
        public readonly float $unsentDays,
        public readonly string $adminPath,
        public readonly string $adminTotpSecret,
        public readonly ?string $adminProblem,
    ) {
    }

    public static function load(string $privateDir, string $publicDir): self
    {
        $env = Env::fromFile($privateDir . '/config.env');
        $data = rtrim($env->str('DATA_DIR', $privateDir . '/data'), '/');
        $admin = $env->str('ADMIN_TOKEN');
        $bot = $env->str('TELEGRAM_BOT_TOKEN');
        $cors = array_values(array_filter(array_map(
            static fn(string $o): string => rtrim(trim($o), '/'),
            explode(',', $env->str('CORS_ORIGINS')),
        )));
        $webhook = $env->str('TG_WEBHOOK_SECRET');
        if ($webhook === '' && $bot !== '') {
            $webhook = substr(hash_hmac('sha256', 'tg-webhook', $bot . '|' . $admin), 0, 48);
        }
        return new self(
            $privateDir, $publicDir, $data, $data . '/uploads',
            rtrim($env->str('PUBLIC_BASE_URL', 'http://localhost:8123'), '/'),
            $admin, $bot, trim($env->str('TELEGRAM_CHAT_ID')), trim($env->str('TELEGRAM_JOIN_CODE')),
            rtrim($env->str('TELEGRAM_API_BASE', 'https://api.telegram.org'), '/'),
            $webhook, $cors,
            (int)($env->num('UPLOAD_QUOTA_MB', 500) * 1048576),
            (int)($env->num('MIN_FREE_MB', 150) * 1048576),
            (int)$env->num('TG_MAX_ATTEMPTS', 40),
            (int)$env->num('RETENTION_DAYS', 365),
            (int)$env->num('RATE_LEADS', 12),
            (int)$env->num('RATE_UPLOADS', 40),
            $env->num('TG_RETRY_BASE_SECONDS', 60),
            $env->num('ORPHAN_HOURS', 24),
            $env->num('UNSENT_FILE_DAYS', 7),
            ...self::adminSettings($env, $admin),
        );
    }

    /**
     * Адрес админки, ключ двухфакторного входа и причина отключения админки, если настройки неверны.
     * Двухфакторный вход обязателен: без ADMIN_TOTP_SECRET админка не включается. Неверное значение
     * никогда не «молча» ослабляет защиту: админка просто не включается.
     * @return array{0:string,1:string,2:?string}
     */
    private static function adminSettings(Env $env, string $adminSecret): array
    {
        $problem = null;
        if (strlen($adminSecret) < self::MIN_ADMIN_SECRET) {
            $problem = 'в config.env не задан ADMIN_TOKEN (не короче ' . self::MIN_ADMIN_SECRET . ' символов)';
        }
        $path = $env->str('ADMIN_PATH', '/admin');
        if (preg_match('~\A/admin(/[A-Za-z0-9_-]{8,64})?\z~', $path) !== 1) {
            $problem ??= 'ADMIN_PATH задан неверно (нужен вид /admin/ЗНАЧЕНИЕ из 8–64 букв, цифр, - и _)';
            $path = '/admin';
        }
        $totp = Totp::normalize($env->str('ADMIN_TOTP_SECRET'));
        if ($totp === '') {
            $problem ??= 'не задан ADMIN_TOTP_SECRET: без двухфакторного входа админка не включается (ключ выдаёт python3 tools/make_2fa.py)';
        } elseif (!Totp::isValidSecret($totp)) {
            $problem ??= 'ADMIN_TOTP_SECRET задан неверно (нужен ключ из 16 и более символов A–Z и 2–7)';
            $totp = '';
        }
        return [$path, $totp, $problem];
    }

    public function adminEnabled(): bool
    {
        return $this->adminProblem === null;
    }

    public function https(): bool
    {
        return str_starts_with($this->baseUrl, 'https://');
    }

    /** Ключ для подписи cookie админки и для хеширования IP: выводится из секретов, отдельно не хранится. */
    public function key(string $purpose): string
    {
        return hash_hmac('sha256', $purpose, $this->adminSecret . '|' . $this->botToken);
    }

    public function ensureDirs(): void
    {
        foreach ([$this->dataDir, $this->uploadsDir, $this->dataDir . '/locks'] as $dir) {
            if (!is_dir($dir) && !mkdir($dir, 0700, true) && !is_dir($dir)) {
                throw new \RuntimeException('Не удалось создать папку данных');
            }
        }
    }
}
