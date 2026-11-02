<?php
declare(strict_types=1);

namespace Jq;

/**
 * Одноразовые коды по RFC 6238 (TOTP): HMAC-SHA1, шаг 30 секунд, 6 цифр.
 * Совместимо с Google Authenticator, Microsoft Authenticator, Aegis, 2FAS, Authy.
 */
final class Totp
{
    public const STEP_SECONDS = 30;
    public const DIGITS = 6;
    public const MIN_SECRET_CHARS = 16;
    private const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

    /** Ключ приводится к виду A–Z и 2–7 без пробелов, дефисов и знаков «=». */
    public static function normalize(string $secret): string
    {
        return strtoupper((string)preg_replace('/[\s=-]+/', '', $secret));
    }

    public static function isValidSecret(string $normalized): bool
    {
        return strlen($normalized) >= self::MIN_SECRET_CHARS && preg_match('/\A[A-Z2-7]+\z/', $normalized) === 1;
    }

    /** Новый ключ: 160 случайных бит в base32 (32 символа). */
    public static function newSecret(): string
    {
        return self::base32Encode(random_bytes(20));
    }

    /** Код для временного шага $step (номер шага = unix-время / 30). */
    public static function code(string $secret, int $step): string
    {
        $hash = hash_hmac('sha1', pack('J', $step), self::base32Decode($secret), true);
        $offset = ord($hash[19]) & 0x0f;
        $value = unpack('N', substr($hash, $offset, 4))[1] & 0x7fffffff;
        return str_pad((string)($value % (10 ** self::DIGITS)), self::DIGITS, '0', STR_PAD_LEFT);
    }

    /**
     * Проверка кода с допуском ±1 шаг на расхождение часов. Каждый код принимается один раз:
     * шаги не больше $lastStep (уже использованные) отвергаются.
     * @return int|null номер принятого шага или null
     */
    public static function verify(string $secret, string $code, int $now, int $lastStep = 0, int $window = 1): ?int
    {
        $code = (string)preg_replace('/\s+/', '', $code);
        if (preg_match('/\A\d{' . self::DIGITS . '}\z/', $code) !== 1) {
            return null;
        }
        $current = intdiv($now, self::STEP_SECONDS);
        $accepted = null;
        for ($step = $current - $window; $step <= $current + $window; $step++) { // все шаги проверяются без раннего выхода
            if (hash_equals(self::code($secret, $step), $code) && $step > $lastStep) {
                $accepted = max($accepted ?? $step, $step);
            }
        }
        return $accepted;
    }

    private static function base32Decode(string $s): string
    {
        $bits = '';
        foreach (str_split($s) as $char) {
            $bits .= str_pad(decbin((int)strpos(self::ALPHABET, $char)), 5, '0', STR_PAD_LEFT);
        }
        $out = '';
        foreach (str_split($bits, 8) as $byte) {
            if (strlen($byte) === 8) {
                $out .= chr((int)bindec($byte));
            }
        }
        return $out;
    }

    private static function base32Encode(string $data): string
    {
        $bits = '';
        foreach (str_split($data) as $byte) {
            $bits .= str_pad(decbin(ord($byte)), 8, '0', STR_PAD_LEFT);
        }
        $out = '';
        foreach (str_split($bits, 5) as $chunk) {
            $out .= self::ALPHABET[(int)bindec(str_pad($chunk, 5, '0'))];
        }
        return $out;
    }
}
