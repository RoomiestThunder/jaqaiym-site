<?php
declare(strict_types=1);

namespace Jq;

/**
 * Доставка заявок в Telegram: текст, фото (альбомом) и PDF.
 *  - Заявка сохраняется в базе ДО отправки; сбой Telegram её не теряет.
 *  - Файлы лежат на диске только до успешной отправки всем получателям, затем удаляются.
 *  - Повтор после сбоя не дублирует то, что уже дошло (таблица tg_sent: заявка x чат x «text» или файл).
 *  - Одну заявку одновременно отправляет один процесс (блокировка файла), остальные пропускают.
 */
final class Notifier
{
    private const BATCH = 20;
    private const MAX_DELAY = 3600;

    public function __construct(
        private readonly Config $cfg,
        private readonly Db $db,
        private readonly Telegram $tg,
        private readonly Files $files,
        private readonly Summary $summary,
        private readonly Subscribers $subs,
    ) {
    }

    public function deliver(int $leadId): void
    {
        $lock = fopen($this->cfg->dataDir . '/locks/lead-' . $leadId . '.lock', 'c');
        if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
            return;
        }
        @set_time_limit(300);
        try {
            $this->run($leadId);
        } catch (\Throwable $e) {
            error_log('jaqaiym deliver ' . $leadId . ': ' . get_class($e) . ': ' . $e->getMessage());
            $this->fail($leadId, 'Внутренняя ошибка: ' . mb_substr($e->getMessage(), 0, 150), 0);
        } finally {
            flock($lock, LOCK_UN);
            fclose($lock);
        }
    }

    /** Заявки, которым пора повторить отправку (вызывается по расписанию и после новой подписки). */
    public function retryDue(): int
    {
        $ids = $this->db->all(
            'SELECT id FROM leads WHERE notified=0 AND notify_attempts<? AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY id LIMIT ?',
            [$this->cfg->maxAttempts, Clock::now(), self::BATCH],
        );
        foreach ($ids as $row) {
            $this->deliver((int)$row['id']);
        }
        return count($ids);
    }

    /** Кнопка «Повторить отправку»: дошедшее не дублируется, досылается только недостающее. */
    public function reset(int $leadId): void
    {
        $this->db->run('UPDATE leads SET notified=0, notify_attempts=0, next_attempt_at=NULL WHERE id=?', [$leadId]);
    }

    /** Удаляет загрузки без заявки и давно неотправленные файлы, а также «потерянные» файлы на диске. */
    public function cleanup(): int
    {
        $rows = $this->db->all(
            'SELECT id FROM attachments WHERE path IS NOT NULL AND ((lead_id IS NULL AND created_at<?) OR (lead_id IS NOT NULL AND created_at<?))',
            [Clock::before($this->cfg->orphanHours * 3600), Clock::before($this->cfg->unsentDays * 86400)],
        );
        foreach ($rows as $row) {
            $this->files->remove((string)$row['id']);
        }
        return count($rows) + $this->files->sweepUnknown();
    }

    // ---------- доставка одной заявки ----------

    private function run(int $leadId): void
    {
        $lead = $this->db->one('SELECT * FROM leads WHERE id=?', [$leadId]);
        if ($lead === null || (int)$lead['notified'] === 1) {
            return;
        }
        $atts = $this->attachments($leadId);
        $text = $this->summary->leadText($lead, count($atts));
        if (!$this->tg->enabled()) { // тестовый режим без Telegram: пишем в outbox.log, файлы ждут срока хранения
            $this->outbox($text, $atts);
            $this->done($leadId, 'outbox');
            return;
        }
        $targets = $this->targets($lead);
        if ($targets === []) {
            $this->fail($leadId, 'Нет получателей: подключите чат командой /join КОД или задайте TELEGRAM_CHAT_ID', 0);
            return;
        }
        [$targets, $errors, $wait] = $this->sendToAll($lead, $targets, $text, $atts);
        if ($errors) {
            $this->fail($leadId, implode('; ', array_unique($errors)), $wait);
            return;
        }
        if ($targets === []) {
            $this->fail($leadId, 'Все получатели недоступны: подключите чат командой /join КОД', 0);
            return;
        }
        foreach ($this->attachments($leadId) as $a) { // всё доставлено: оставшиеся файлы заявки больше не нужны
            if ($a['path'] !== null) {
                $this->files->remove((string)$a['id']);
            }
        }
        $this->done($leadId, 'telegram');
    }

    /**
     * @param array<string,mixed> $lead @param list<string> $targets @param list<array<string,mixed>> $atts
     * @return array{0:list<string>,1:list<string>,2:int} получатели после отключения недоступных, ошибки, пауза
     */
    private function sendToAll(array $lead, array $targets, string $text, array $atts): array
    {
        $errors = [];
        $wait = 0;
        foreach ($targets as $chat) {
            try {
                $this->deliverChat($lead, $chat, $text, $atts);
            } catch (TgError $e) {
                $wait = max($wait, $e->retryAfter);
                if ($e->migrateTo !== null) { // группу превратили в супергруппу: у неё новый id
                    $targets = array_map(static fn($t) => $t === $chat ? $e->migrateTo : $t, $targets);
                    $this->migrate((int)$lead['id'], $chat, $e->migrateTo, $targets);
                    $errors[] = 'чат перенесён, повтор';
                } elseif ($e->permanent() && $chat !== $this->cfg->chatId) {
                    error_log('jaqaiym: получатель ' . $chat . ' недоступен (' . $e->desc . '): отключён');
                    $this->subs->deactivate($chat);
                    $targets = array_values(array_filter($targets, static fn($t) => $t !== $chat));
                    $this->setTargets((int)$lead['id'], $targets);
                } else {
                    $errors[] = 'Telegram ' . $e->httpCode . ': ' . $e->desc;
                }
            }
        }
        return [$targets, $errors, $wait];
    }

    /** @param array<string,mixed> $lead @param list<array<string,mixed>> $atts */
    private function deliverChat(array $lead, string $chat, string $text, array $atts): void
    {
        $leadId = (int)$lead['id'];
        $sent = array_column($this->db->all('SELECT item FROM tg_sent WHERE lead_id=? AND chat_id=?', [$leadId, $chat]), 'item');
        if (!in_array('text', $sent, true)) {
            $this->tg->call('sendMessage', ['chat_id' => $chat, 'text' => mb_substr($text, 0, 4000), 'link_preview_options' => ['is_disabled' => true]], [], 30);
            $this->mark($leadId, $chat, 'text');
        }
        $pending = array_values(array_filter($atts, static fn($a) => $a['path'] !== null && $a['deleted_at'] === null && !in_array($a['id'], $sent, true)));
        $isImage = static fn($a) => str_starts_with((string)$a['mime'], 'image/');
        foreach (array_chunk(array_values(array_filter($pending, $isImage)), 10) as $group) {
            $this->sendImages($lead, $chat, $group);
        }
        foreach ($pending as $a) {
            if (!$isImage($a)) {
                $this->sendDoc($lead, $chat, $a);
            }
        }
    }

    /** @param array<string,mixed> $lead @param list<array<string,mixed>> $imgs */
    private function sendImages(array $lead, string $chat, array $imgs): void
    {
        $caption = 'Заявка №' . $lead['id'] . ': фото';
        try {
            if (count($imgs) === 1) {
                $this->tg->call('sendPhoto', ['chat_id' => $chat, 'caption' => $caption], [$this->filePart('photo', $imgs[0], 'photo')]);
            } else {
                $media = [];
                $parts = [];
                foreach ($imgs as $i => $a) {
                    $media[] = ['type' => 'photo', 'media' => 'attach://f' . $i] + ($i === 0 ? ['caption' => $caption] : []);
                    $parts[] = $this->filePart('f' . $i, $a, 'photo');
                }
                $this->tg->call('sendMediaGroup', ['chat_id' => $chat, 'media' => json_encode($media, JSON_UNESCAPED_UNICODE)], $parts);
            }
            foreach ($imgs as $a) {
                $this->mark((int)$lead['id'], $chat, (string)$a['id']);
            }
        } catch (TgError $e) {
            if ($e->httpCode !== 400 || $e->migrateTo !== null || $e->permanent()) {
                throw $e;
            }
            foreach ($imgs as $a) { // Telegram не принял как фото (размер, пропорции, формат): шлём файлом
                $this->sendDoc($lead, $chat, $a);
            }
        }
    }

    /** @param array<string,mixed> $lead @param array<string,mixed> $a */
    private function sendDoc(array $lead, string $chat, array $a): void
    {
        $caption = 'Заявка №' . $lead['id'] . ': ' . ($a['filename'] ?: 'файл');
        $this->tg->call('sendDocument', ['chat_id' => $chat, 'caption' => $caption], [$this->filePart('document', $a, 'file')]);
        $this->mark((int)$lead['id'], $chat, (string)$a['id']);
    }

    /** @param array<string,mixed> $a @return array{0:string,1:string,2:string,3:string} */
    private function filePart(string $field, array $a, string $fallbackName): array
    {
        return [$field, (string)($a['filename'] ?: $fallbackName), (string)$a['mime'], $this->files->path((string)$a['id'])];
    }

    // ---------- состояние заявки ----------

    /** @return list<array<string,mixed>> */
    private function attachments(int $leadId): array
    {
        return $this->db->all('SELECT * FROM attachments WHERE lead_id=? ORDER BY created_at, id', [$leadId]);
    }

    /** @param array<string,mixed> $lead @return list<string> */
    private function targets(array $lead): array
    {
        if (!empty($lead['tg_targets'])) {
            return array_map('strval', json_decode((string)$lead['tg_targets'], true) ?: []);
        }
        $targets = $this->cfg->chatId !== '' ? [$this->cfg->chatId] : [];
        foreach ($this->subs->all() as $s) {
            if (!in_array($s['chat_id'], $targets, true)) {
                $targets[] = (string)$s['chat_id'];
            }
        }
        if ($targets !== []) {
            $this->setTargets((int)$lead['id'], $targets);
        }
        return $targets;
    }

    /** @param list<string> $targets */
    private function setTargets(int $leadId, array $targets): void
    {
        $this->db->run('UPDATE leads SET tg_targets=? WHERE id=?', [json_encode(array_values($targets)), $leadId]);
    }

    /** @param list<string> $targets */
    private function migrate(int $leadId, string $old, string $new, array $targets): void
    {
        $this->setTargets($leadId, $targets);
        $this->db->run('UPDATE tg_sent SET chat_id=? WHERE lead_id=? AND chat_id=?', [$new, $leadId, $old]);
        $this->db->run('UPDATE tg_subscribers SET chat_id=? WHERE chat_id=?', [$new, $old]);
    }

    private function mark(int $leadId, string $chat, string $item): void
    {
        $this->db->run('INSERT OR IGNORE INTO tg_sent(lead_id,chat_id,item,sent_at) VALUES(?,?,?,?)', [$leadId, $chat, $item, Clock::now()]);
        if ($item !== 'text') {
            $this->release($leadId);
        }
    }

    /** Удаляет файлы заявки, которые уже дошли до всех её получателей. */
    private function release(int $leadId): void
    {
        $targets = array_map('strval', json_decode((string)$this->db->val('SELECT tg_targets FROM leads WHERE id=?', [$leadId]), true) ?: []);
        if ($targets === []) {
            return;
        }
        foreach ($this->attachments($leadId) as $a) {
            if ($a['path'] === null) {
                continue;
            }
            $got = array_column($this->db->all('SELECT chat_id FROM tg_sent WHERE lead_id=? AND item=?', [$leadId, $a['id']]), 'chat_id');
            if (array_diff($targets, $got) === []) {
                $this->files->remove((string)$a['id']);
            }
        }
    }

    private function fail(int $leadId, string $error, int $retryAfter): void
    {
        $n = (int)$this->db->val('SELECT notify_attempts FROM leads WHERE id=?', [$leadId]) + 1;
        $delay = max(min($this->cfg->retryBase * (2 ** ($n - 1)), self::MAX_DELAY), $retryAfter + 1);
        $this->db->run(
            'UPDATE leads SET notify_attempts=?, notify_error=?, next_attempt_at=? WHERE id=?',
            [$n, mb_substr($error, 0, 300), Clock::after($delay), $leadId],
        );
    }

    private function done(int $leadId, string $via): void
    {
        $this->db->run(
            'UPDATE leads SET notified=1, notified_via=?, notify_error=NULL, next_attempt_at=NULL, notify_attempts=notify_attempts+1 WHERE id=?',
            [$via, $leadId],
        );
    }

    /** @param list<array<string,mixed>> $atts */
    private function outbox(string $text, array $atts): void
    {
        $names = implode(', ', array_map(static fn($a) => sprintf('%s (%d КБ)', $a['filename'], (int)round(((int)$a['size']) / 1024)), $atts));
        $entry = sprintf("--- %s ---\n%s%s\n\n", Clock::now(), $text, $names !== '' ? "\nФайлы: " . $names : '');
        file_put_contents($this->cfg->dataDir . '/outbox.log', $entry, FILE_APPEND | LOCK_EX);
    }
}
