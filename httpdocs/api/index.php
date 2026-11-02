<?php
declare(strict_types=1);

// Единственный PHP-файл в корне сайта: подключает код из папки вне корня (jaqaiym-private) и передаёт ему запрос.
// Расположение папки: переменная JQ_PRIVATE_DIR или соседняя с httpdocs папка jaqaiym-private.

ini_set('display_errors', '0');
ini_set('log_errors', '1');
umask(0077); // всё, что создаёт приложение (база, загрузки, журналы), доступно только владельцу

$publicDir = dirname(__DIR__);
$privateDir = rtrim((string)(getenv('JQ_PRIVATE_DIR') ?: dirname($publicDir) . '/jaqaiym-private'), '/');

if (!is_file($privateDir . '/src/bootstrap.php')) {
    http_response_code(500);
    header('Content-Type: application/json; charset=utf-8');
    echo '{"error":"server"}';
    error_log('jaqaiym: не найдена папка с кодом: ' . $privateDir);
    exit;
}
require $privateDir . '/src/bootstrap.php';

$cfg = Jq\Config::load($privateDir, $publicDir);
ini_set('error_log', $cfg->dataDir . '/php-error.log');
(new Jq\App($cfg))->handle();
