<?php
declare(strict_types=1);

namespace Jq;

/** Минимальный клиент Telegram Bot API через cURL (TLS-сертификаты проверяются всегда). */
final class Telegram
{
    public function __construct(private readonly Config $cfg)
    {
    }

    public function enabled(): bool
    {
        return $this->cfg->botToken !== '';
    }

    /**
     * @param array<string,mixed> $payload
     * @param list<array{0:string,1:string,2:string,3:string}> $files поле, имя, mime-тип, путь к файлу на диске
     * @throws TgError
     */
    public function call(string $method, array $payload = [], array $files = [], int $timeout = 60): mixed
    {
        $ch = curl_init($this->cfg->apiBase . '/bot' . $this->cfg->botToken . '/' . $method);
        $opts = [
            CURLOPT_RETURNTRANSFER => true, CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => $timeout, CURLOPT_POST => true,
        ];
        if ($files) {
            foreach ($files as [$field, $name, $mime, $path]) {
                $payload[$field] = new \CURLFile($path, $mime, $name);
            }
            $opts[CURLOPT_POSTFIELDS] = $payload;
        } else {
            $opts[CURLOPT_POSTFIELDS] = json_encode($payload === [] ? new \stdClass() : $payload, JSON_UNESCAPED_UNICODE);
            $opts[CURLOPT_HTTPHEADER] = ['Content-Type: application/json'];
        }
        curl_setopt_array($ch, $opts);
        $raw = curl_exec($ch);
        $http = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        if ($raw === false) {
            throw new TgError(0, $this->scrub(curl_error($ch)));
        }
        $j = json_decode((string)$raw, true);
        if (!is_array($j)) {
            throw new TgError($http, 'нечитаемый ответ Telegram');
        }
        if (empty($j['ok'])) {
            $p = is_array($j['parameters'] ?? null) ? $j['parameters'] : [];
            throw new TgError(
                (int)($j['error_code'] ?? $http), $this->scrub((string)($j['description'] ?? '')),
                (int)($p['retry_after'] ?? 0), isset($p['migrate_to_chat_id']) ? (string)$p['migrate_to_chat_id'] : null,
            );
        }
        return $j['result'] ?? null;
    }

    private function scrub(string $text): string
    {
        return mb_substr($this->cfg->botToken === '' ? $text : str_replace($this->cfg->botToken, '***', $text), 0, 200);
    }
}
