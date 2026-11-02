<?php
declare(strict_types=1);

// Запуск по расписанию (Plesk: «Планировщик задач» → «Запустить PHP-скрипт», раз в минуту):
// повтор неудавшихся отправок в Telegram, очистка временных файлов, удаление заявок по истечении срока хранения.
// Из браузера не запускается.

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

umask(0077); // всё, что создаёт приложение, доступно только владельцу

$privateDir = dirname(__DIR__);
require $privateDir . '/src/bootstrap.php';

$publicDir = (string)(getenv('JQ_PUBLIC_DIR') ?: dirname($privateDir) . '/httpdocs');
$cfg = Jq\Config::load($privateDir, $publicDir);
$cfg->ensureDirs();
ini_set('error_log', $cfg->dataDir . '/php-error.log');

$lock = fopen($cfg->dataDir . '/locks/cron.lock', 'c');
if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
    exit(0); // предыдущий запуск ещё работает
}
try {
    $s = new Jq\Services($cfg);
    $done = $s->maintenance->run();
    if (getenv('JQ_VERBOSE')) {
        echo json_encode($done), "\n";
    }
} catch (Throwable $e) {
    error_log('jaqaiym cron: ' . get_class($e) . ': ' . $e->getMessage());
    exit(1);
}
