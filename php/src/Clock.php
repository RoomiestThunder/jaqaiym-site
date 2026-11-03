<?php
declare(strict_types=1);

namespace Jq;

/** Время в UTC в формате ISO 8601: 2026-11-02T10:00:00+00:00 (сравнивается как строка). */
final class Clock
{
    public static function now(): string
    {
        return gmdate('Y-m-d\TH:i:s') . '+00:00';
    }

    public static function after(float $seconds): string
    {
        return gmdate('Y-m-d\TH:i:s', time() + (int)$seconds) . '+00:00';
    }

    public static function before(float $seconds): string
    {
        return gmdate('Y-m-d\TH:i:s', time() - (int)$seconds) . '+00:00';
    }
}
