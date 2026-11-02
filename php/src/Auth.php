<?php
declare(strict_types=1);

namespace Jq;

/**
 * Вход в админку: пароль (ADMIN_TOKEN) и одноразовый код из приложения (TOTP, ключ ADMIN_TOTP_SECRET). Без ключа админка не включается.
 * Пароль не попадает ни в адрес, ни в сообщения Telegram: после входа выдаётся подписанная cookie
 * (HttpOnly, Secure на https, SameSite=Lax) на 12 часов. Смена ADMIN_TOKEN сразу делает все выданные cookie недействительными.
 *
 * Защита от перебора: считаются только неудачные попытки и только с одного адреса (8 за 15 минут, IPv6 по сети /64).
 * Общего счётчика нет: постороннему не удастся «запереть» владельца, отправив много запросов.
 */
final class Auth
{
    private const TTL = 43200;
    private const LOGIN_FAILURES = 8;
    private const LOGIN_WINDOW = 900;
    private const TOTP_STEP_KEY = 'totp_last_step';
    private const EPOCH_KEY = 'session_epoch';

    public function __construct(private readonly Config $cfg, private readonly Limiter $limiter, private readonly Db $db)
    {
    }

    private function cookieName(): string
    {
        return $this->cfg->https() ? '__Host-jq_admin' : 'jq_admin';
    }

    private function sign(string $data): string
    {
        return rtrim(strtr(base64_encode(hash_hmac('sha256', $data, $this->cfg->key('session'), true)), '+/', '-_'), '=');
    }

    public function loginBlocked(string $ip): bool
    {
        return $this->limiter->blocked('login_fail', $this->limiter->who($ip), self::LOGIN_FAILURES, self::LOGIN_WINDOW);
    }

    public function loginFailed(string $ip): void
    {
        $this->limiter->record('login_fail', $this->limiter->who($ip));
    }

    /** Пароль и код. Код принимается один раз и только после верного пароля. */
    public function credentialsOk(string $password, string $code): bool
    {
        return $this->passwordOk($password) && $this->codeOk($code);
    }

    private function passwordOk(string $given): bool
    {
        return $this->cfg->adminEnabled() && hash_equals(hash('sha256', $this->cfg->adminSecret), hash('sha256', $given));
    }

    private function codeOk(string $code): bool
    {
        return (bool)$this->db->tx(function () use ($code): bool {
            $last = (int)$this->db->val('SELECT v FROM kv WHERE k=?', [self::TOTP_STEP_KEY]);
            $step = Totp::verify($this->cfg->adminTotpSecret, $code, time(), $last);
            if ($step === null) {
                return false;
            }
            $this->db->run('INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)', [self::TOTP_STEP_KEY, (string)$step]);
            return true;
        });
    }

    /** «Поколение» входов: выход увеличивает его, и все выданные до этого cookie перестают действовать (в том числе украденные). */
    private function epoch(): string
    {
        return (string)($this->db->val('SELECT v FROM kv WHERE k=?', [self::EPOCH_KEY]) ?? '0');
    }

    public function grant(): void
    {
        $exp = (string)(time() + self::TTL);
        $this->setCookie($exp . '.' . $this->sign('s|' . $exp . '|' . $this->epoch()), time() + self::TTL);
    }

    public function revoke(): void
    {
        $this->db->run('INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)', [self::EPOCH_KEY, (string)((int)$this->epoch() + 1)]);
        $this->setCookie('', time() - 3600);
    }

    private function setCookie(string $value, int $expires): void
    {
        setcookie($this->cookieName(), $value, [
            'expires' => $expires, 'path' => '/', 'secure' => $this->cfg->https(), 'httponly' => true, 'samesite' => 'Lax',
        ]);
    }

    private function cookie(): string
    {
        return (string)($_COOKIE[$this->cookieName()] ?? '');
    }

    public function valid(): bool
    {
        if (!$this->cfg->adminEnabled()) {
            return false;
        }
        $parts = explode('.', $this->cookie(), 2);
        if (count($parts) !== 2 || !ctype_digit($parts[0]) || (int)$parts[0] < time()) {
            return false;
        }
        return hash_equals($this->sign('s|' . $parts[0] . '|' . $this->epoch()), $parts[1]);
    }

    /** Токен для запросов, меняющих данные: вшивается в страницу админки, привязан к текущему входу. */
    public function csrf(): string
    {
        return hash_hmac('sha256', 'csrf|' . $this->cookie(), $this->cfg->key('csrf'));
    }

    public function csrfOk(): bool
    {
        return $this->valid() && hash_equals($this->csrf(), Http::reqHeader('X-CSRF-Token')) && Http::originAllowed($this->cfg, false);
    }
}
