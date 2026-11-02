<?php
declare(strict_types=1);

namespace Jq;

/** Тексты для команды: карточка заявки (одно поле в строке) и сообщение в Telegram. */
final class Summary
{
    public function __construct(private readonly Schema $schema, private readonly Config $cfg)
    {
    }

    /**
     * Текст клиента в сообщении команде — одной строкой: перенос строки не должен подделывать служебные строки
     * (например, «Карточка: https://…»).
     */
    public static function oneLine(string $s): string
    {
        return trim((string)preg_replace('/[\p{Z}\s\p{Cc}]+/u', ' ', $s));
    }

    /** @param array<string,mixed> $p очищенная заявка */
    public function make(array $p): string
    {
        $lines = [];
        $add = static function (string $label, mixed $value) use (&$lines): void {
            $text = is_scalar($value) ? self::oneLine((string)$value) : '';
            if ($text !== '') {
                $lines[] = $label . ': ' . $text;
            }
        };
        if (($p['lead_type'] ?? '') === 'quick') {
            $q = $p['quick'] ?? [];
            $add('Тип обращения', $this->schema->lab('quick_type', $q['request_type'] ?? null));
            $add('Сообщение', mb_substr((string)($q['message'] ?? ''), 0, 500));
            return implode("\n", $lines);
        }
        $pr = $p['project'];
        $f = $pr['features'] ?? [];
        $cat = $pr['category'] ?? '';
        $lab = fn(string $g, mixed $k): ?string => ($k === null || $k === '') ? null : $this->schema->lab($g, $k);
        $low = fn(string $g, mixed $keys): string => implode(', ', array_map(
            fn($k) => mb_strtolower($this->schema->lab($g, $k)), is_array($keys) ? $keys : [],
        ));
        $add('Заказ', $lab('category', $cat));
        $add('Помещение', $lab('premise', $pr['premise'] ?? null));
        $add('Город', $lab('city', $pr['city'] ?? null));
        $add('Планировка кухни', $lab('kitchen_layout', $pr['layout'] ?? null));
        $add('Тип шкафа', $lab('wardrobe_kind', $pr['wardrobe_kind'] ?? null));
        $add('Объекты', $lab('business_scope', $pr['business_scope'] ?? null));
        $add('Стиль', $low('style', $pr['style_preferences'] ?? []));
        $add('Комментарий к стилю', $pr['style_note'] ?? null);
        if ($cat === 'kitchen') {
            foreach (['upper_cabinets' => 'Верхние шкафы', 'island' => 'Остров', 'built_in_appliances' => 'Встроенная техника'] as $key => $label) {
                $v = $lab('yes_no', $f[$key] ?? null);
                $add($label, $v === null ? null : mb_strtolower($v));
            }
        }
        $add('Двери', $low('doors', $f['door_type'] ?? []));
        $add('Что хранить', $low('storage', $f['storage_priorities'] ?? []));
        $add('Назначение', $low('purpose', $f['purposes'] ?? []));
        $add('Объект', $f['object_type'] ?? null);
        $add('Задача', $f['task'] ?? null);
        $add('Количество', $f['quantity'] ?? null);
        $dm = $pr['dimensions_mm'] ?? null;
        if (!empty($pr['dimensions_known']) && $dm) {
            $names = ['a' => 'A', 'b' => 'B', 'c' => 'C', 'width' => 'ширина', 'height' => 'высота', 'depth' => 'глубина'];
            $parts = [];
            foreach ($dm as $k => $v) {
                if ($v) {
                    $parts[] = ($names[$k] ?? $k) . ' ' . (int)round($v / 10, 0, PHP_ROUND_HALF_EVEN);
                }
            }
            $add('Размеры, см', implode(', ', $parts));
        } elseif (!in_array($cat, ['business', 'other'], true)) {
            $add('Размеры', 'неизвестны, нужен замер');
        }
        $add('Бюджет', $lab('budget', $pr['budget_range'] ?? null));
        $timeframe = $lab('timeframe', $pr['timeframe'] ?? null);
        $add('Срок', $timeframe === null ? null : mb_strtolower($timeframe));
        $add('Примечание', mb_substr((string)($pr['description'] ?? ''), 0, 500));
        return implode("\n", $lines);
    }

    /**
     * Сообщение в Telegram: блоки через пустую строку, каждое поле с новой строки.
     * Ссылка на карточку без секретов: админка просит пароль и запоминает вход.
     * @param array<string,mixed> $lead строка таблицы leads
     */
    public function leadText(array $lead, int $files): string
    {
        $p = json_decode((string)$lead['payload'], true) ?: [];
        $c = $p['customer'] ?? [];
        $src = $p['source'] ?? [];
        $quick = ($lead['lead_type'] ?? '') === 'quick';
        $contact = [];
        $rows = [
            ['Клиент', $c['name'] ?? '—'], ['Телефон', $c['phone'] ?? ''],
            ['Связаться', empty($c['preferred_channel']) ? null : $this->schema->lab('channel', $c['preferred_channel'])],
            ['Удобное время', $c['preferred_time'] ?? null], ['Email', $c['email'] ?? null], ['Компания', $c['company'] ?? null],
            ['Роль', empty($c['role']) ? null : $this->schema->lab('role', $c['role'])],
        ];
        foreach ($rows as [$label, $value]) {
            $text = is_scalar($value) ? self::oneLine((string)$value) : '';
            if ($text !== '') {
                $contact[] = $label . ': ' . $text;
            }
        }
        $where = [];
        if (!empty($src['page']) && is_string($src['page'])) {
            $where[] = 'Страница: ' . self::oneLine($src['page']);
        }
        if (!empty($src['project_id']) && is_string($src['project_id'])) {
            $where[] = 'Понравился проект: ' . self::oneLine($src['project_id']);
        }
        $blocks = [sprintf('Новая заявка №%d (%s)', $lead['id'], $quick ? 'быстрая' : 'проект'), $this->make($p), implode("\n", $contact)];
        if (!$quick) {
            $blocks[] = $files > 0 ? sprintf('Файлы: %d (придут следом в этот чат)', $files) : 'Файлы: не приложены';
        }
        if ($where) {
            $blocks[] = implode("\n", $where);
        }
        $blocks[] = sprintf('Карточка: %s/admin#lead-%d', $this->cfg->baseUrl, $lead['id']);
        return implode("\n\n", array_filter($blocks, static fn($b) => $b !== ''));
    }
}
