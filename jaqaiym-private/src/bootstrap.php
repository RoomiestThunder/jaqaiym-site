<?php
declare(strict_types=1);

// Автозагрузка классов Jq\Имя из этой папки; сторонних библиотек нет.
spl_autoload_register(static function (string $class): void {
    if (!str_starts_with($class, 'Jq\\')) {
        return;
    }
    $file = __DIR__ . '/' . substr($class, 3) . '.php';
    if (is_file($file)) {
        require $file;
    }
});
