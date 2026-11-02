<?php
declare(strict_types=1);

namespace Jq;

/** Открытые адреса: приём заявки, загрузка файла, вебхук Telegram. */
final class PublicApi
{
    private const MAX_JSON = 200 * 1024;
    private const MAX_UPDATE = 100 * 1024;
    private const PART_SUFFIX = '.part';
    private const HEAD_BYTES = 16;

    public function __construct(private readonly Services $s)
    {
    }

    // ---------- заявка ----------

    public function leads(): void
    {
        $reject = $this->leadRejection((int)($_SERVER['CONTENT_LENGTH'] ?? 0));
        if ($reject !== null) {
            Http::json($reject[0], $reject[1]);
            return;
        }
        $raw = Http::body(self::MAX_JSON);
        $d = $raw === null ? null : json_decode($raw, true, 32);
        if ($d === null) {
            Http::json(400, ['error' => 'bad_json']);
            return;
        }
        if ($this->isTrapped($d)) { // антиспам-приманка: тихо отбрасываем
            Http::json(201, ['ok' => true, 'lead_id' => 0]);
            return;
        }
        [$err, $clean] = $this->s->validator->validate($d);
        if ($err) {
            Http::json(422, ['error' => 'validation', 'errors' => $err]);
            return;
        }
        $this->saveAndNotify($clean);
    }

    /** Отказ до чтения тела: размер, чужой Origin, частота. @return array{0:int,1:array<string,mixed>}|null */
    private function leadRejection(int $len): ?array
    {
        if ($len <= 0 || $len > self::MAX_JSON) {
            return [413, ['error' => 'too_large']];
        }
        if (!Http::originAllowed($this->s->cfg)) {
            return [403, ['error' => 'forbidden_origin']];
        }
        if (!$this->s->limiter->allow('lead', $this->s->limiter->who(Http::ip()), $this->s->cfg->rateLeads)) {
            return [429, ['error' => 'rate_limited', 'message' => 'Слишком много попыток. Попробуйте позже.']];
        }
        return null;
    }

    private function isTrapped(mixed $d): bool
    {
        $trap = is_array($d) ? ($d['hp'] ?? '') : '';
        return is_array($trap) || (is_scalar($trap) && trim((string)$trap) !== '');
    }

    /** @param array<string,mixed> $clean */
    private function saveAndNotify(array $clean): void
    {
        try {
            [$id, $dup] = $this->s->leads->create($clean);
        } catch (\DomainException $e) {
            Http::json(422, ['error' => 'validation', 'errors' => ['project.attachment_ids' => $e->getMessage()]]);
            return;
        } catch (\Throwable $e) {
            error_log('jaqaiym: не удалось сохранить заявку: ' . $e->getMessage());
            Http::json(500, ['error' => 'save_failed']);
            return;
        }
        Http::finish($dup ? 200 : 201, ['ok' => true, 'lead_id' => $id, 'duplicate' => $dup]);
        if (!$dup) {
            $this->s->notifier->deliver($id);
        }
        $this->s->maintenance->runIfDue();
    }

    // ---------- файл ----------

    public function upload(): void
    {
        $len = (int)($_SERVER['CONTENT_LENGTH'] ?? 0);
        $reject = $this->uploadRejection($len);
        if ($reject !== null) {
            Http::json($reject[0], $reject[1]);
            return;
        }
        $in = fopen('php://input', 'rb');
        $head = (string)fread($in, self::HEAD_BYTES);
        if ($head === '') { // PHP отбросил тело, потому что оно больше post_max_size сервера
            Http::json(...$this->tooLarge());
            return;
        }
        $mime = Files::sniff($head);
        if ($mime === null || !in_array($mime, $this->s->schema->limits()['file_types'], true)) {
            Http::json(415, ['error' => 'bad_type', 'message' => 'Допустимы JPG, PNG, WebP и PDF']);
            return;
        }
        $id = bin2hex(random_bytes(16));
        $size = $this->saveStream($in, $head, $this->s->files->path($id), $this->maxFileBytes());
        if ($size === null) {
            Http::json(...$this->tooLarge());
            return;
        }
        $name = Files::cleanName(Http::reqHeader('X-File-Name') ?: 'file');
        $this->s->db->run(
            'INSERT INTO attachments(id,filename,mime,size,path,created_at) VALUES(?,?,?,?,?,?)',
            [$id, $name, $mime, $size, $id, Clock::now()],
        );
        Http::json(201, ['id' => $id, 'name' => $name, 'size' => $size, 'mime' => $mime]);
    }

    private function maxFileBytes(): int
    {
        return (int)$this->s->schema->limits()['max_file_mb'] * 1048576;
    }

    /** @return array{0:int,1:array<string,mixed>} */
    private function tooLarge(): array
    {
        return [413, ['error' => 'too_large', 'message' => 'Файл больше ' . (int)$this->s->schema->limits()['max_file_mb'] . ' МБ']];
    }

    /** Отказ до чтения файла: размер, чужой Origin, частота, место на диске. @return array{0:int,1:array<string,mixed>}|null */
    private function uploadRejection(int $len): ?array
    {
        $cfg = $this->s->cfg;
        if ($len <= 0) {
            return [400, ['error' => 'empty']];
        }
        if ($len > $this->maxFileBytes()) {
            return $this->tooLarge();
        }
        if (!Http::originAllowed($cfg)) {
            return [403, ['error' => 'forbidden_origin']];
        }
        if (!$this->s->limiter->allow('upload', $this->s->limiter->who(Http::ip()), $cfg->rateUploads)) {
            return [429, ['error' => 'rate_limited', 'message' => 'Слишком много загрузок. Попробуйте позже.']];
        }
        if ($this->s->files->usedBytes() + $len > $cfg->quotaBytes || $this->s->files->freeBytes() - $len < $cfg->minFreeBytes) {
            return [507, ['error' => 'storage_full', 'message' => 'Загрузка файлов сейчас недоступна. Отправьте заявку без файлов: их можно показать при разговоре.']];
        }
        return null;
    }

    /** Пишет файл через временное имя; null, если он оказался больше лимита. */
    private function saveStream(mixed $in, string $head, string $final, int $max): ?int
    {
        $tmp = $final . self::PART_SUFFIX;
        $out = fopen($tmp, 'wb');
        chmod($tmp, 0600);
        fwrite($out, $head);
        $size = strlen($head) + (int)stream_copy_to_stream($in, $out, $max + 1 - strlen($head));
        fclose($out);
        if ($size > $max) {
            unlink($tmp);
            return null;
        }
        rename($tmp, $final);
        return $size;
    }

    // ---------- вебхук Telegram ----------

    public function webhook(): void
    {
        $cfg = $this->s->cfg;
        if (!$this->s->tg->enabled() || $cfg->webhookSecret === '') {
            Http::json(404, ['error' => 'not_found']);
            return;
        }
        if (!hash_equals($cfg->webhookSecret, Http::reqHeader('X-Telegram-Bot-Api-Secret-Token'))) {
            Http::json(403, ['error' => 'forbidden']);
            return;
        }
        $raw = Http::body(self::MAX_UPDATE);
        $update = $raw === null ? null : json_decode($raw, true, 16);
        Http::finish(200, ['ok' => true]); // Telegram повторяет запрос, пока не получит 200
        if (!is_array($update)) {
            return;
        }
        try {
            $this->s->subs->handleUpdate($update);
            $this->s->notifier->retryDue(); // после новой подписки ждущие заявки уходят сразу
        } catch (\Throwable $e) {
            error_log('jaqaiym webhook: ' . $e->getMessage());
        }
    }
}
