<?php
declare(strict_types=1);

namespace Jq;

/** Ошибка Telegram Bot API или сети. Токен в текст ошибки никогда не попадает. */
final class TgError extends \RuntimeException
{
    public function __construct(
        public readonly int $httpCode,
        public readonly string $desc,
        public readonly int $retryAfter = 0,
        public readonly ?string $migrateTo = null,
    ) {
        parent::__construct($httpCode . ': ' . $desc);
    }

    /** Чат недоступен насовсем (бота удалили или заблокировали): ждать бессмысленно. */
    public function permanent(): bool
    {
        if ($this->httpCode === 403) {
            return true;
        }
        $d = strtolower($this->desc);
        foreach (['chat not found', 'kicked', 'blocked', 'not a member', 'deactivated', 'have no rights'] as $s) {
            if ($this->httpCode === 400 && str_contains($d, $s)) {
                return true;
            }
        }
        return false;
    }
}
