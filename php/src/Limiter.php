<?php
declare(strict_types=1);

namespace Jq;

/** Ограничение частоты запросов. IP в базе хранится только в виде необратимого хеша и живёт не дольше окна. */
final class Limiter
{
    public function __construct(private readonly Db $db, private readonly Config $cfg)
    {
    }

    public function who(string $ip): string
    {
        return substr(hash_hmac('sha256', $ip, $this->cfg->key('ip')), 0, 24);
    }

    /** Засчитывает обращение; false, если в окне уже достигнут лимит. */
    public function allow(string $bucket, string $who, int $limit, int $window = 600): bool
    {
        $now = time();
        return (bool)$this->db->tx(function () use ($bucket, $who, $limit, $window, $now): bool {
            $this->db->run('DELETE FROM rate_hits WHERE bucket=? AND who=? AND ts<?', [$bucket, $who, $now - $window]);
            $count = (int)$this->db->val('SELECT COUNT(*) FROM rate_hits WHERE bucket=? AND who=?', [$bucket, $who]);
            if ($count >= $limit) {
                return false;
            }
            $this->db->run('INSERT INTO rate_hits(bucket,who,ts) VALUES(?,?,?)', [$bucket, $who, $now]);
            return true;
        });
    }

    /** Достигнут ли лимит записей, ничего не засчитывая (для счёта только неудач). */
    public function blocked(string $bucket, string $who, int $limit, int $window = 600): bool
    {
        return (int)$this->db->val('SELECT COUNT(*) FROM rate_hits WHERE bucket=? AND who=? AND ts>=?', [$bucket, $who, time() - $window]) >= $limit;
    }

    public function record(string $bucket, string $who): void
    {
        $this->db->run('INSERT INTO rate_hits(bucket,who,ts) VALUES(?,?,?)', [$bucket, $who, time()]);
    }

    public function prune(int $olderThan = 86400): void
    {
        $this->db->run('DELETE FROM rate_hits WHERE ts<?', [time() - $olderThan]);
    }
}
