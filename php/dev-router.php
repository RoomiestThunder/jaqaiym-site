<?php
// Только для разработки: роутер встроенного сервера PHP (php -S -t <httpdocs>), повторяет правила .htaccess:
// /api и /admin — в точку входа, посторонние .php и скрытые файлы закрыты, несуществующее — 404 (а не index.html).
// На хостинге не используется.
$path = rawurldecode(parse_url((string)($_SERVER['REQUEST_URI'] ?? '/'), PHP_URL_PATH) ?: '/');
$root = realpath((string)$_SERVER['DOCUMENT_ROOT']);

if ($path === '/admin' || str_starts_with($path, '/admin/') || str_starts_with($path, '/api/')) {
    require $_SERVER['DOCUMENT_ROOT'] . '/api/index.php';
    return true;
}
$real = realpath($root . $path);
$inside = $real !== false && ($real === $root || str_starts_with($real, $root . '/'));
$hidden = (bool)preg_match('~(^|/)\.|\.(php|phtml|phar|inc)$~', $path);
if ($inside && !$hidden && (is_file($real) || is_file($real . '/index.html'))) {
    return false; // существующий файл или папка с index.html отдаёт сам сервер
}
http_response_code(404);
echo 'Not found';
return true;
