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
        private readonly Leads $leads,
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
            $this->leads->erase((int)$id);
        }
        return count($ids);
    }
}
