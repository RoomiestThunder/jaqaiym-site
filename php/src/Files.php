<?php
declare(strict_types=1);

namespace Jq;

/** Временное хранилище загрузок: имя файла на диске — случайный идентификатор, настоящее имя только в базе. */
final class Files
{
    public function __construct(private readonly Config $cfg, private readonly Db $db)
    {
    }

    public static function validId(string $id): bool
    {
        return (bool)preg_match('/\A[0-9a-f]{32}\z/', $id);
    }

    public function path(string $id): string
    {
        if (!self::validId($id)) {
            throw new \InvalidArgumentException('bad file id');
        }
        return $this->cfg->uploadsDir . '/' . $id;
    }

    /** Тип по первым байтам, а не по заголовку или расширению, которые присылает клиент. */
    public static function sniff(string $head): ?string
    {
        return match (true) {
            str_starts_with($head, "\xff\xd8\xff") => 'image/jpeg',
            str_starts_with($head, "\x89PNG\r\n\x1a\n") => 'image/png',
            strlen($head) >= 12 && str_starts_with($head, 'RIFF') && substr($head, 8, 4) === 'WEBP' => 'image/webp',
            str_starts_with($head, '%PDF-') => 'application/pdf',
            default => null,
        };
    }

    /** Имя для показа и для Telegram: без путей, управляющих символов и кавычек. */
    public static function cleanName(string $raw): string
    {
        $name = rawurldecode($raw);
        $name = preg_replace('/[\x00-\x1f\x7f\/\\\\"<>|:*?]+/u', ' ', $name) ?? '';
        $name = trim(mb_substr($name, 0, 120));
        return $name === '' ? 'file' : $name;
    }

    public function usedBytes(): int
    {
        return (int)$this->db->val('SELECT COALESCE(SUM(size),0) FROM attachments WHERE path IS NOT NULL');
    }

    public function freeBytes(): int
    {
        $free = @disk_free_space($this->cfg->dataDir);
        return $free === false ? PHP_INT_MAX : (int)$free;
    }

    /** Удаляет файл с диска и помечает его в базе; повторный вызов безопасен. */
    public function remove(string $id): void
    {
        $this->db->run('UPDATE attachments SET path=NULL, deleted_at=? WHERE id=? AND path IS NOT NULL', [Clock::now(), $id]);
        $file = $this->path($id);
        if (is_file($file) && !@unlink($file)) {
            error_log('jaqaiym: не удалось удалить файл ' . $id);
        }
    }

    /** Удаляет с диска файлы, о которых база ничего не знает (прерванные загрузки), старше часа. */
    public function sweepUnknown(): int
    {
        $known = array_column($this->db->all('SELECT id FROM attachments WHERE path IS NOT NULL'), 'id');
        $removed = 0;
        foreach (scandir($this->cfg->uploadsDir) ?: [] as $name) {
            $file = $this->cfg->uploadsDir . '/' . $name;
            if ($name[0] === '.' || !is_file($file) || in_array($name, $known, true) || time() - (int)filemtime($file) < 3600) {
                continue;
            }
            $removed += @unlink($file) ? 1 : 0;
        }
        return $removed;
    }
}
