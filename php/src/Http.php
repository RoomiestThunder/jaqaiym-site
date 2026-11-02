<?php
declare(strict_types=1);

namespace Jq;

/** Вспомогательные функции запроса и ответа. */
final class Http
{
    public static function method(): string
    {
        return strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET'));
    }

    public static function path(): string
    {
        $p = parse_url((string)($_SERVER['REQUEST_URI'] ?? '/'), PHP_URL_PATH);
        return is_string($p) && $p !== '' ? $p : '/';
    }

    public static function reqHeader(string $name): string
    {
        return trim((string)($_SERVER['HTTP_' . strtoupper(str_replace('-', '_', $name))] ?? ''));
    }

    /**
     * Адрес посетителя. Заголовки прокси учитываются только если запрос пришёл с внутреннего адреса
     * (nginx/Apache на этом же сервере); берётся последняя запись X-Forwarded-For — её дописал наш прокси,
     * а всё, что левее, мог подделать клиент.
     */
    public static function ip(): string
    {
        $addr = (string)($_SERVER['REMOTE_ADDR'] ?? '0.0.0.0');
        // «свой» прокси: внутренний адрес или адрес самого сервера (в Plesk nginx обращается к Apache по публичному IP сайта)
        $internal = $addr === (string)($_SERVER['SERVER_ADDR'] ?? '-')
            || filter_var($addr, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE) === false;
        if (!$internal) {
            return $addr;
        }
        $parts = array_map('trim', explode(',', self::reqHeader('X-Forwarded-For')));
        $last = end($parts);
        if (is_string($last) && filter_var($last, FILTER_VALIDATE_IP) !== false) {
            return $last;
        }
        $real = self::reqHeader('X-Real-IP');
        return filter_var($real, FILTER_VALIDATE_IP) !== false ? $real : $addr;
    }

    /** Читает тело запроса не более $max байт; null, если оно больше. */
    public static function body(int $max): ?string
    {
        $raw = (string)stream_get_contents(fopen('php://input', 'rb'), $max + 1);
        return strlen($raw) > $max ? null : $raw;
    }

    /**
     * Можно ли принять запрос с таким заголовком Origin: без заголовка (не браузер) или с адресом самого сайта.
     * Чужие адреса из списка CORS_ORIGINS проходят только там, где $allowCors = true (приём заявок, но не админка).
     */
    public static function originAllowed(Config $cfg, bool $allowCors = true): bool
    {
        $origin = rtrim(self::reqHeader('Origin'), '/');
        if ($origin === '') {
            return true;
        }
        if (in_array($origin, $cfg->corsOrigins, true)) {
            return $allowCors;
        }
        $host = parse_url($origin, PHP_URL_HOST);
        $port = parse_url($origin, PHP_URL_PORT);
        $mine = strtolower(self::reqHeader('Host'));
        $theirs = strtolower(is_string($host) ? $host . ($port ? ':' . $port : '') : '');
        return $theirs !== '' && $theirs === $mine;
    }

    /** @param array<string,mixed> $body */
    public static function json(int $code, array $body): void
    {
        http_response_code($code);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }

    /** Отправляет ответ и закрывает соединение, а скрипт продолжает работу (отправка в Telegram уже не задерживает посетителя). */
    public static function finish(int $code, array $body): void
    {
        $out = (string)json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        ignore_user_abort(true);
        http_response_code($code);
        header('Content-Type: application/json; charset=utf-8');
        header('Content-Length: ' . strlen($out));
        header('Connection: close');
        echo $out;
        if (function_exists('fastcgi_finish_request')) {
            fastcgi_finish_request();
            return;
        }
        while (ob_get_level() > 0) {
            ob_end_flush();
        }
        flush();
    }

    /** @param array<string,string> $headers */
    public static function html(int $code, string $html, array $headers = []): void
    {
        http_response_code($code);
        header('Content-Type: text/html; charset=utf-8');
        foreach ($headers as $name => $value) {
            header($name . ': ' . $value);
        }
        echo $html;
    }

    public static function redirect(string $to, int $code = 303): void
    {
        http_response_code($code);
        header('Location: ' . $to);
    }
}
