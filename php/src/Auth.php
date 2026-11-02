<?php
declare(strict_types=1);

namespace Jq;

/**
 * Вход в админку по паролю (ADMIN_TOKEN). Пароль не попадает ни в адрес, ни в сообщения Telegram:
 * после входа выдаётся подписанная cookie (HttpOnly, Secure на https, SameSite=Lax) на 12 часов.
 * Смена ADMIN_TOKEN сразу делает все выданные cookie недействительными.
 */
final class Auth
{
    private const TTL = 43200;
    private const LOGIN_LIMIT = 8;
    private const LOGIN_WINDOW = 900;
    private const LOGIN_LIMIT_ALL = 40;
    private const LOGIN_WINDOW_ALL = 3600;

    public function __construct(private readonly Config $cfg, private readonly Limiter $limiter)
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

    /** Засчитывает попытку входа; false, если лимит исчерпан (с этого IP или в целом по сайту). */
    public function loginAllowed(string $ip): bool
    {
        return $this->limiter->allow('login', $this->limiter->who($ip), self::LOGIN_LIMIT, self::LOGIN_WINDOW)
            && $this->limiter->allow('login_all', 'all', self::LOGIN_LIMIT_ALL, self::LOGIN_WINDOW_ALL);
    }

    public function passwordOk(string $given): bool
    {
        return $this->cfg->adminEnabled() && hash_equals(hash('sha256', $this->cfg->adminSecret), hash('sha256', $given));
    }

    public function grant(): void
    {
        $exp = (string)(time() + self::TTL);
        $this->setCookie($exp . '.' . $this->sign('s|' . $exp), time() + self::TTL);
    }

    public function revoke(): void
    {
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
        return hash_equals($this->sign('s|' . $parts[0]), $parts[1]);
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
