<?php
declare(strict_types=1);

namespace Jq;

/**
 * Фоновые задачи: повтор неудавшихся отправок, очистка временных файлов, срок хранения заявок.
 * Основной запуск — по расписанию (bin/cron.php, раз в минуту); если расписание не настроено,
 * то же самое выполняется после очередного запроса, но не чаще раза в несколько минут.
 */
final class Maintenance
{
    private const KEY = 'maintenance_at';
    private const MAX_LOG_BYTES = 1048576;

    public function __construct(
        private readonly Config $cfg,
        private readonly Db $db,
        private readonly Notifier $notifier,
        private readonly Files $files,
        private readonly Limiter $limiter,
    ) {
    }

    /** @return array<string,int> */
    public function run(): array
    {
        $done = [
            'retried' => $this->notifier->retryDue(),
            'files_removed' => $this->notifier->cleanup(),
            'leads_purged' => $this->purgeExpired(),
        ];
        $this->limiter->prune();
        $this->rotateLog();
        $this->db->run('INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)', [self::KEY, (string)time()]);
        return $done;
    }

    /** Журнал ошибок PHP не растёт без предела: больше 1 МБ — прошлый уходит в php-error.log.1, начинается новый. */
    private function rotateLog(): void
    {
        $log = $this->cfg->dataDir . '/php-error.log';
        if (is_file($log) && filesize($log) > self::MAX_LOG_BYTES) {
            rename($log, $log . '.1');
        }
    }

    public function runIfDue(int $everySeconds = 300): void
    {
        $last = (int)$this->db->val('SELECT v FROM kv WHERE k=?', [self::KEY]);
        if (time() - $last >= $everySeconds) {
            $this->run();
        }
    }

    /**
     * Политика: заявки без договора хранятся 1 год после последнего контакта (смена статуса считается контактом).
     * Заявки со статусом «Договор» автоматически не удаляются.
     */
    public function purgeExpired(): int
    {
        $before = Clock::before($this->cfg->retentionDays * 86400);
        $ids = array_column($this->db->all(
            "SELECT id FROM leads WHERE status<>'won' AND COALESCE(updated_at, created_at) < ?", [$before],
        ), 'id');
        foreach ($ids as $id) {
            foreach ($this->db->all('SELECT id FROM attachments WHERE lead_id=? AND path IS NOT NULL', [$id]) as $a) {
                $this->files->remove((string)$a['id']);
            }
            $this->db->run('DELETE FROM attachments WHERE lead_id=?', [$id]);
            $this->db->run('DELETE FROM tg_sent WHERE lead_id=?', [$id]);
            $this->db->run('DELETE FROM leads WHERE id=?', [$id]);
        }
        return count($ids);
    }
}
