<?php
declare(strict_types=1);

namespace Jq;

/** Получатели заявок: чаты, которые сами подписались командой /join КОД (или перешли по ссылке из админки). */
final class Subscribers
{
    private const WRONG_CODE_LIMIT = 5;
    private const COMMAND = '~^/(start|join|leave|stop|help)(?:@\w+)?(?:\s+(.*))?$~su';

    public function __construct(
        private readonly Config $cfg,
        private readonly Db $db,
        private readonly Telegram $tg,
        private readonly Limiter $limiter,
    ) {
    }

    /** @return list<array<string,mixed>> */
    public function all(bool $onlyActive = true): array
    {
        return $this->db->all('SELECT * FROM tg_subscribers' . ($onlyActive ? ' WHERE active=1' : '') . ' ORDER BY joined_at');
    }

    public function deactivate(string $chatId): void
    {
        $this->db->run('UPDATE tg_subscribers SET active=0 WHERE chat_id=?', [$chatId]);
    }

    private function upsert(string $chatId, string $title, string $kind): void
    {
        $this->db->run(
            'INSERT INTO tg_subscribers(chat_id,title,kind,joined_at,active) VALUES(?,?,?,?,1) '
            . 'ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, kind=excluded.kind, active=1',
            [$chatId, $title, $kind, Clock::now()],
        );
        // заявки, которые ждали получателя, отправляются сразу, без долгой паузы
        $this->db->run('UPDATE leads SET next_attempt_at=NULL, notify_attempts=0 WHERE notified=0 AND tg_targets IS NULL');
    }

    private function say(string $chatId, string $text): void
    {
        try {
            $this->tg->call('sendMessage', ['chat_id' => $chatId, 'text' => $text, 'link_preview_options' => ['is_disabled' => true]], [], 15);
        } catch (TgError) {
            // ответ необязателен: подписка от него не зависит
        }
    }

    /** @param array<string,mixed> $u обновление Telegram (message или my_chat_member) */
    public function handleUpdate(array $u): void
    {
        $member = $u['my_chat_member'] ?? null;
        if (is_array($member) && in_array($member['new_chat_member']['status'] ?? '', ['left', 'kicked'], true)) {
            if (isset($member['chat']['id'])) {
                $this->deactivate((string)$member['chat']['id']);
            }
            return;
        }
        $msg = is_array($u['message'] ?? null) ? $u['message'] : [];
        $chat = is_array($msg['chat'] ?? null) ? $msg['chat'] : [];
        $text = is_string($msg['text'] ?? null) ? trim($msg['text']) : '';
        $id = $chat['id'] ?? null;
        if ((!is_int($id) && !is_string($id)) || !preg_match(self::COMMAND, $text, $m)) {
            return;
        }
        $cmd = $m[1];
        $arg = trim($m[2] ?? '');
        $cid = (string)$id;
        if ($cmd === 'leave' || $cmd === 'stop') {
            $this->deactivate($cid);
            $this->say($cid, 'Подписка отключена: новые заявки сюда больше приходить не будут. Подключиться снова: /join КОД');
            return;
        }
        if (($cmd === 'join' || $cmd === 'start') && $arg !== '' && $this->cfg->joinCode !== '') {
            $this->tryJoin($cid, $arg, $chat);
            return;
        }
        if (($chat['type'] ?? '') === 'private' || $cmd === 'join') {
            $this->say($cid, 'Это бот заявок JAQAIYM. Чтобы получать заявки, отправьте /join КОД (код выдаёт администратор сайта).');
        }
    }

    /** @param array<string,mixed> $chat */
    private function tryJoin(string $cid, string $code, array $chat): void
    {
        $who = $this->limiter->who('tg:' . $cid);
        if ($this->limiter->blocked('joinfail', $who, self::WRONG_CODE_LIMIT)) {
            return; // слишком много неверных кодов: молчим
        }
        if (!hash_equals($this->cfg->joinCode, $code)) {
            $this->limiter->record('joinfail', $who);
            $this->say($cid, 'Неверный код. Попросите актуальный код у администратора сайта.');
            return;
        }
        $title = (string)($chat['title'] ?? '');
        if ($title === '') {
            $title = trim(($chat['first_name'] ?? '') . ' ' . ($chat['last_name'] ?? ''));
        }
        $title = $title !== '' ? $title : (string)($chat['username'] ?? $cid);
        $this->upsert($cid, mb_substr($title, 0, 120), (string)($chat['type'] ?? ''));
        $this->say($cid, 'Готово: этот чат подписан на заявки JAQAIYM. Отписаться: /leave');
    }
}
