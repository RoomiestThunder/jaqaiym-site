<?php
declare(strict_types=1);

namespace Jq;

/** Настройки: переменные окружения важнее файла config.env, который лежит вне корня сайта. */
final class Env
{
    /** @param array<string,string> $file */
    private function __construct(private readonly array $file)
    {
    }

    public static function fromFile(string $path): self
    {
        $vals = [];
        if (is_file($path) && is_readable($path)) {
            foreach (file($path, FILE_IGNORE_NEW_LINES) ?: [] as $line) {
                $line = trim($line);
                if ($line === '' || $line[0] === '#' || !str_contains($line, '=')) {
                    continue;
                }
                [$key, $value] = explode('=', $line, 2);
                $vals[trim($key)] = trim(trim($value), "\"'");
            }
        }
        return new self($vals);
    }

    public function str(string $key, string $default = ''): string
    {
        $env = getenv($key);
        if ($env !== false && $env !== '') {
            return $env;
        }
        return $this->file[$key] ?? $default;
    }

    public function num(string $key, float $default): float
    {
        $v = $this->str($key);
        return is_numeric($v) ? (float)$v : $default;
    }
}
