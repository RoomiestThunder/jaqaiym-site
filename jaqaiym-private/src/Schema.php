<?php
declare(strict_types=1);

namespace Jq;

/** Общий словарь значений (public/schema.json): его же читает анкета на сайте. */
final class Schema
{
    /** @param array<string,mixed> $data */
    private function __construct(private readonly array $data)
    {
    }

    public static function load(string $file): self
    {
        $raw = is_file($file) ? file_get_contents($file) : false;
        $data = $raw === false ? null : json_decode($raw, true);
        if (!is_array($data)) {
            throw new \RuntimeException('Не удалось прочитать schema.json');
        }
        return new self($data);
    }

    public function version(): int
    {
        return (int)$this->data['schema_version'];
    }

    /** @return array<string,mixed> */
    public function limits(): array
    {
        return $this->data['limits'];
    }

    /**
     * Обязательные ответы по типам заказа (общие для сервера и анкеты).
     * @return array{by_category: array<string,list<string>>, fields: array<string,array<string,mixed>>}
     */
    public function required(): array
    {
        $r = is_array($this->data['required'] ?? null) ? $this->data['required'] : [];
        return ['by_category' => $r['by_category'] ?? [], 'fields' => $r['fields'] ?? []];
    }

    /** @return array<string,string> */
    public function group(string $name): array
    {
        $g = $this->data[$name] ?? [];
        return is_array($g) ? $g : [];
    }

    /** Допустимо ли значение в группе. Значения не строки и не числа (массивы и т. п.) не допускаются. */
    public function has(string $group, mixed $key): bool
    {
        return (is_string($key) || is_int($key)) && isset($this->group($group)[$key]);
    }

    /** Подпись значения по-русски; неизвестное значение возвращается как есть. */
    public function lab(string $group, mixed $key): string
    {
        $label = (is_string($key) || is_int($key)) ? ($this->group($group)[$key] ?? null) : null;
        return is_string($label) ? $label : (is_scalar($key) ? (string)$key : '');
    }
}
