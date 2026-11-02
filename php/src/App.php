<?php
declare(strict_types=1);

namespace Jq;

/** Маршрутизация: какой адрес какому обработчику принадлежит. Всё, что вне списка, — 404. */
final class App
{
    private const PUBLIC_PATHS = '#^/api/(health|leads|attachments)$#';

    public function __construct(private readonly Config $cfg)
    {
    }

    public function handle(): void
    {
        $path = Http::path();
        $method = Http::method();
        $this->headers($path);
        if ($method === 'OPTIONS' && str_starts_with($path, '/api/')) {
            http_response_code(204);
            return;
        }
        try {
            $s = new Services($this->cfg);
            $this->dispatch($method, $path, new PublicApi($s), new AdminController($s));
        } catch (\Throwable $e) {
            error_log('jaqaiym: ' . get_class($e) . ': ' . $e->getMessage() . ' @ ' . basename($e->getFile()) . ':' . $e->getLine());
            if (!headers_sent()) {
                Http::json(500, ['error' => 'server']);
            }
        }
    }

    private function dispatch(string $method, string $path, PublicApi $pub, AdminController $admin): void
    {
        $routes = [
            ['GET', '#^/api/health$#', fn() => Http::json(200, ['ok' => true])],
            ['POST', '#^/api/leads$#', fn() => $pub->leads()],
            ['POST', '#^/api/attachments$#', fn() => $pub->upload()],
            ['POST', '#^/api/tg/webhook$#', fn() => $pub->webhook()],
            ['GET', '#^/admin/?$#', fn() => $admin->page()],
            ['POST', '#^/admin/login$#', fn() => $admin->login()],
            ['POST', '#^/admin/logout$#', fn() => $admin->logout()],
            ['GET', '#^/api/admin/leads$#', fn() => $admin->leadsJson()],
            ['POST', '#^/api/admin/leads/(\d+)/status$#', fn(array $m) => $admin->setStatus((int)$m[1])],
            ['POST', '#^/api/admin/leads/(\d+)/resend$#', fn(array $m) => $admin->resend((int)$m[1])],
            ['POST', '#^/api/admin/subscribers/(-?\d+)/remove$#', fn(array $m) => $admin->removeSubscriber($m[1])],
            ['POST', '#^/api/admin/webhook/set$#', fn() => $admin->setWebhook()],
            ['GET', '#^/api/files/([0-9a-f]{32})$#', fn(array $m) => $admin->file($m[1])],
        ];
        foreach ($routes as [$verb, $pattern, $handler]) {
            if ($method === $verb && preg_match($pattern, $path, $m)) {
                $handler($m);
                return;
            }
        }
        Http::json(404, ['error' => 'not_found']);
    }

    private function headers(string $path): void
    {
        header('X-Content-Type-Options: nosniff');
        header('Referrer-Policy: same-origin');
        header('X-Frame-Options: DENY');
        header('Cache-Control: no-store');
        header_remove('X-Powered-By');
        $origin = rtrim(Http::reqHeader('Origin'), '/');
        if ($origin !== '' && in_array($origin, $this->cfg->corsOrigins, true) && preg_match(self::PUBLIC_PATHS, $path)) {
            header('Access-Control-Allow-Origin: ' . $origin);
            header('Vary: Origin');
            header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
            header('Access-Control-Allow-Headers: Content-Type, X-File-Name');
            header('Access-Control-Max-Age: 600');
        }
    }
}
