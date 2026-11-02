<?php
declare(strict_types=1);

namespace Jq;

/** Хранение заявок. Заявка сохраняется в базе до любой отправки: сбой Telegram её не теряет. */
final class Leads
{
    public function __construct(private readonly Db $db, private readonly Summary $summary)
    {
    }

    /**
     * Повторная отправка с тем же submission_id возвращает уже созданную заявку.
     * @param array<string,mixed> $clean
     * @return array{0:int,1:bool} идентификатор заявки и признак повтора
     * @throws \DomainException файл не найден или уже прикреплён к другой заявке
     */
    public function create(array $clean): array
    {
        return $this->db->tx(function () use ($clean): array {
            $row = $this->db->one('SELECT id FROM leads WHERE submission_id=?', [$clean['submission_id']]);
            if ($row !== null) {
                return [(int)$row['id'], true];
            }
            $ids = $clean['project']['attachment_ids'] ?? [];
            foreach ($ids as $id) {
                $att = $this->db->one('SELECT lead_id FROM attachments WHERE id=? AND path IS NOT NULL', [$id]);
                if ($att === null || $att['lead_id'] !== null) {
                    throw new \DomainException('Файл не найден или уже прикреплён: повторите загрузку');
                }
            }
            $this->db->run(
                'INSERT INTO leads(submission_id,lead_type,status,created_at,payload,summary,phone) VALUES(?,?,?,?,?,?,?)',
                [$clean['submission_id'], $clean['lead_type'], 'new', Clock::now(),
                    json_encode($clean, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR),
                    $this->summary->make($clean), $clean['customer']['phone']],
            );
            $leadId = $this->db->lastId();
            foreach ($ids as $id) {
                $this->db->run('UPDATE attachments SET lead_id=? WHERE id=?', [$leadId, $id]);
            }
            return [$leadId, false];
        });
    }

    public function setStatus(int $id, string $status): void
    {
        $this->db->run('UPDATE leads SET status=?, updated_at=? WHERE id=?', [$status, Clock::now(), $id]);
    }

    /** @return list<array<string,mixed>> заявки с файлами, новые сверху (для админки) */
    public function rows(int $limit = 500): array
    {
        $leads = $this->db->all('SELECT * FROM leads ORDER BY id DESC LIMIT ?', [$limit]);
        $files = $this->db->all('SELECT id,filename,mime,size,lead_id,path IS NOT NULL AS on_disk,deleted_at FROM attachments WHERE lead_id IS NOT NULL');
        foreach ($leads as &$lead) {
            $lead['payload'] = json_decode((string)$lead['payload'], true) ?: [];
            $lead['files'] = array_values(array_filter($files, static fn($a) => (int)$a['lead_id'] === (int)$lead['id']));
        }
        return $leads;
    }
}
