<?php
declare(strict_types=1);

namespace Jq;

/** Тексты для команды: карточка заявки (одно поле в строке) и сообщение в Telegram. */
final class Summary
{
    private const DIMENSION_NAMES = ['a' => 'A', 'b' => 'B', 'c' => 'C', 'width' => 'ширина', 'height' => 'высота', 'depth' => 'глубина'];
    private const KITCHEN_ANSWERS = ['upper_cabinets' => 'Верхние шкафы', 'island' => 'Остров', 'built_in_appliances' => 'Встроенная техника'];

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

    /** @param list<array{0:string,1:mixed}> $pairs подпись и значение; пустые значения пропускаются */
    private static function format(array $pairs): string
    {
        $lines = [];
        foreach ($pairs as [$label, $value]) {
            $text = is_scalar($value) ? self::oneLine((string)$value) : '';
            if ($text !== '') {
                $lines[] = $label . ': ' . $text;
            }
        }
        return implode("\n", $lines);
    }

    /** @param array<string,mixed> $p очищенная заявка */
    public function make(array $p): string
    {
        return self::format(($p['lead_type'] ?? '') === 'quick' ? $this->quickPairs($p['quick'] ?? []) : $this->projectPairs($p['project'] ?? []));
    }

    /** @param array<string,mixed> $q @return list<array{0:string,1:mixed}> */
    private function quickPairs(array $q): array
    {
        return [
            ['Тип обращения', $this->schema->lab('quick_type', $q['request_type'] ?? null)],
            ['Сообщение', mb_substr((string)($q['message'] ?? ''), 0, 500)],
        ];
    }

    /** @param array<string,mixed> $pr @return list<array{0:string,1:mixed}> */
    private function projectPairs(array $pr): array
    {
        $f = $pr['features'] ?? [];
        $cat = $pr['category'] ?? '';
        $pairs = [
            ['Заказ', $this->label('category', $cat)], ['Помещение', $this->label('premise', $pr['premise'] ?? null)],
            ['Город', $this->label('city', $pr['city'] ?? null)], ['Планировка кухни', $this->label('kitchen_layout', $pr['layout'] ?? null)],
            ['Тип шкафа', $this->label('wardrobe_kind', $pr['wardrobe_kind'] ?? null)], ['Объекты', $this->label('business_scope', $pr['business_scope'] ?? null)],
            ['Стиль', $this->labels('style', $pr['style_preferences'] ?? [])], ['Комментарий к стилю', $pr['style_note'] ?? null],
        ];
        if ($cat === 'kitchen') {
            foreach (self::KITCHEN_ANSWERS as $key => $label) {
                $answer = $this->label('yes_no', $f[$key] ?? null);
                $pairs[] = [$label, $answer === null ? null : mb_strtolower($answer)];
            }
        }
        $timeframe = $this->label('timeframe', $pr['timeframe'] ?? null);
        return array_merge($pairs, [
            ['Двери', $this->labels('doors', $f['door_type'] ?? [])], ['Что хранить', $this->labels('storage', $f['storage_priorities'] ?? [])],
            ['Назначение', $this->labels('purpose', $f['purposes'] ?? [])], ['Объект', $f['object_type'] ?? null],
            ['Задача', $f['task'] ?? null], ['Количество', $f['quantity'] ?? null], $this->dimensionsPair($pr, (string)$cat),
            ['Бюджет', $this->label('budget', $pr['budget_range'] ?? null)], ['Срок', $timeframe === null ? null : mb_strtolower($timeframe)],
            ['Примечание', mb_substr((string)($pr['description'] ?? ''), 0, 500)],
        ]);
    }

    /** @param array<string,mixed> $pr @return array{0:string,1:mixed} */
    private function dimensionsPair(array $pr, string $cat): array
    {
        $dm = $pr['dimensions_mm'] ?? null;
        if (!empty($pr['dimensions_known']) && $dm) {
            $parts = [];
            foreach ($dm as $k => $v) {
                if ($v) {
                    $parts[] = (self::DIMENSION_NAMES[$k] ?? $k) . ' ' . (int)round($v / 10, 0, PHP_ROUND_HALF_EVEN);
                }
            }
            return ['Размеры, см', implode(', ', $parts)];
        }
        return ['Размеры', in_array($cat, ['business', 'other'], true) ? null : 'неизвестны, нужен замер'];
    }

    private function label(string $group, mixed $key): ?string
    {
        return ($key === null || $key === '') ? null : $this->schema->lab($group, $key);
    }

    /** Подписи списка значений через запятую, строчными. */
    private function labels(string $group, mixed $keys): string
    {
        return implode(', ', array_map(fn($k) => mb_strtolower($this->schema->lab($group, $k)), is_array($keys) ? $keys : []));
    }

    /**
     * Сообщение в Telegram: блоки через пустую строку, каждое поле с новой строки.
     * Ссылка на карточку без секретов: админка просит пароль и запоминает вход.
     * @param array<string,mixed> $lead строка таблицы leads
     */
    public function leadText(array $lead, int $files): string
    {
        $p = json_decode((string)$lead['payload'], true) ?: [];
        $quick = ($lead['lead_type'] ?? '') === 'quick';
        $blocks = [sprintf('Новая заявка №%d (%s)', $lead['id'], $quick ? 'быстрая' : 'проект'), $this->make($p), $this->contactBlock($p['customer'] ?? [])];
        if (!$quick) {
            $blocks[] = $files > 0 ? sprintf('Файлы: %d (придут следом в этот чат)', $files) : 'Файлы: не приложены';
        }
        $blocks[] = $this->sourceBlock($p['source'] ?? []);
        $blocks[] = sprintf('Карточка: %s/admin#lead-%d', $this->cfg->baseUrl, $lead['id']);
        return implode("\n\n", array_filter($blocks, static fn($b) => $b !== ''));
    }

    /** @param array<string,mixed> $c */
    private function contactBlock(array $c): string
    {
        $channel = empty($c['preferred_channel']) ? null : $this->schema->lab('channel', $c['preferred_channel']);
        $role = empty($c['role']) ? null : $this->schema->lab('role', $c['role']);
        return self::format([
            ['Клиент', $c['name'] ?? '—'], ['Телефон', $c['phone'] ?? ''], ['Связаться', $channel], ['Удобное время', $c['preferred_time'] ?? null],
            ['Email', $c['email'] ?? null], ['Компания', $c['company'] ?? null], ['Роль', $role],
        ]);
    }

    /** @param array<string,mixed> $src */
    private function sourceBlock(array $src): string
    {
        return self::format([
            ['Страница', is_string($src['page'] ?? null) ? $src['page'] : null],
            ['Понравился проект', is_string($src['project_id'] ?? null) ? $src['project_id'] : null],
        ]);
    }
}
