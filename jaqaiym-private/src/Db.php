<?php
declare(strict_types=1);

namespace Jq;

use PDO;

/** SQLite через PDO: только подготовленные запросы. */
final class Db
{
    private const TABLES = <<<'SQL'
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id TEXT UNIQUE NOT NULL,
  lead_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL,
  payload TEXT NOT NULL, summary TEXT NOT NULL, phone TEXT,
  notified INTEGER NOT NULL DEFAULT 0, notify_attempts INTEGER NOT NULL DEFAULT 0, notify_error TEXT,
  tg_targets TEXT, next_attempt_at TEXT, notified_via TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS attachments(
  id TEXT PRIMARY KEY, filename TEXT, mime TEXT, size INTEGER, path TEXT,
  created_at TEXT, lead_id INTEGER, deleted_at TEXT);
CREATE TABLE IF NOT EXISTS tg_subscribers(
  chat_id TEXT PRIMARY KEY, title TEXT, kind TEXT, joined_at TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS tg_sent(
  lead_id INTEGER NOT NULL, chat_id TEXT NOT NULL, item TEXT NOT NULL, sent_at TEXT, PRIMARY KEY(lead_id, chat_id, item));
CREATE TABLE IF NOT EXISTS rate_hits(bucket TEXT NOT NULL, who TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS rate_hits_idx ON rate_hits(bucket, who, ts);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
SQL;

    /** Колонки, которых могло не быть в базе, созданной раньше. */
    private const ADDED = [
        ['leads', 'tg_targets', 'TEXT'], ['leads', 'next_attempt_at', 'TEXT'], ['leads', 'notified_via', 'TEXT'],
        ['leads', 'updated_at', 'TEXT'], ['attachments', 'deleted_at', 'TEXT'],
    ];

    private function __construct(private readonly PDO $pdo)
    {
    }

    public static function open(string $file): self
    {
        $pdo = new PDO('sqlite:' . $file, null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        $pdo->exec('PRAGMA busy_timeout = 8000');
        $db = new self($pdo);
        $db->migrate();
        @chmod($file, 0600);
        return $db;
    }

    private function migrate(): void
    {
        $this->pdo->exec(self::TABLES);
        foreach (self::ADDED as [$table, $column, $type]) {
            $have = array_column($this->all("PRAGMA table_info($table)"), 'name');
            if (!in_array($column, $have, true)) {
                $this->pdo->exec("ALTER TABLE $table ADD COLUMN $column $type");
            }
        }
    }

    /** @param array<int|string,mixed> $params */
    public function run(string $sql, array $params = []): int
    {
        $st = $this->pdo->prepare($sql);
        $st->execute($params);
        return $st->rowCount();
    }

    /** @param array<int|string,mixed> $params @return list<array<string,mixed>> */
    public function all(string $sql, array $params = []): array
    {
        $st = $this->pdo->prepare($sql);
        $st->execute($params);
        return $st->fetchAll();
    }

    /** @param array<int|string,mixed> $params @return array<string,mixed>|null */
    public function one(string $sql, array $params = []): ?array
    {
        return $this->all($sql, $params)[0] ?? null;
    }

    /** @param array<int|string,mixed> $params */
    public function val(string $sql, array $params = []): mixed
    {
        $row = $this->one($sql, $params);
        return $row === null ? null : reset($row);
    }

    public function lastId(): int
    {
        return (int)$this->pdo->lastInsertId();
    }

    /** Транзакция с немедленной блокировкой записи: две заявки не обгоняют друг друга. */
    public function tx(callable $fn): mixed
    {
        $this->pdo->exec('BEGIN IMMEDIATE');
        try {
            $result = $fn();
            $this->pdo->exec('COMMIT');
            return $result;
        } catch (\Throwable $e) {
            $this->pdo->exec('ROLLBACK');
            throw $e;
        }
    }
}
