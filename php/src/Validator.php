<?php
declare(strict_types=1);

namespace Jq;

/** Проверка и очистка заявки. Правила обязательных полей те же, что в анкете на сайте (wizard.js). */
final class Validator
{
    private const LANGS = ['ru', 'kk'];
    private const SOURCE_KEYS = ['page', 'project_id', 'utm', 'from'];
    private const PROJECT_KEYS = [
        'category', 'premise', 'city', 'layout', 'wardrobe_kind', 'business_scope', 'style_preferences', 'style_note',
        'features', 'dimensions_known', 'dimensions_mm', 'budget_range', 'timeframe', 'description', 'attachment_ids',
    ];
    /** поле проекта => группа допустимых значений в schema.json */
    private const PROJECT_GROUPS = [
        'premise' => 'premise', 'layout' => 'kitchen_layout', 'wardrobe_kind' => 'wardrobe_kind',
        'business_scope' => 'business_scope', 'budget_range' => 'budget', 'timeframe' => 'timeframe',
    ];
    private const FEATURE_LISTS = ['door_type' => 'doors', 'storage_priorities' => 'storage', 'purposes' => 'purpose'];

    public function __construct(private readonly Schema $schema)
    {
    }

    public static function normPhone(mixed $raw): ?string
    {
        $d = preg_replace('/\D/', '', is_scalar($raw) ? (string)$raw : '') ?? '';
        if (strlen($d) === 11 && ($d[0] === '7' || $d[0] === '8')) {
            $d = '7' . substr($d, 1);
        } elseif (strlen($d) === 10) {
            $d = '7' . $d;
        }
        return strlen($d) === 11 && $d[0] === '7' ? '+' . $d : null;
    }

    /** Обрезанная строка; не-скалярные значения превращаются в пустую строку. */
    public static function text(mixed $v, int $max): string
    {
        return is_scalar($v) ? mb_substr((string)$v, 0, $max) : '';
    }

    /** @return array{0: array<string,string>, 1: array<string,mixed>|null} ошибки и очищенная заявка */
    public function validate(mixed $d): array
    {
        if (!is_array($d) || array_is_list($d)) {
            return [['_' => 'Некорректный запрос'], null];
        }
        $s = $this->schema;
        $err = [];
        if (($d['schema_version'] ?? null) !== $s->version()) {
            $err['schema_version'] = 'Неподдерживаемая версия формы. Обновите страницу.';
        }
        $sid = self::text($d['submission_id'] ?? '', 200);
        if (!preg_match('/\A[0-9a-fA-F-]{16,64}\z/', $sid)) {
            $err['submission_id'] = 'Некорректный идентификатор заявки';
        }
        $lt = $d['lead_type'] ?? null;
        if ($lt !== 'project' && $lt !== 'quick') {
            $err['lead_type'] = 'Некорректный тип заявки';
        }
        $c = is_array($d['customer'] ?? null) ? $d['customer'] : [];
        $consent = is_array($d['consent'] ?? null) ? $d['consent'] : [];
        $phone = self::normPhone($c['phone'] ?? null);
        if ($phone === null) {
            $err['customer.phone'] = 'Укажите номер телефона Казахстана, например +7 700 000 00 00';
        }
        if (($consent['project_contact'] ?? null) !== true) {
            $err['consent'] = 'Нужно согласие на обработку данных';
        }
        if ($lt === 'project' && trim(self::text($c['name'] ?? '', 100)) === '') {
            $err['customer.name'] = 'Укажите имя';
        }
        $clean = [
            'schema_version' => 1, 'submission_id' => $sid, 'lead_type' => $lt,
            'locale' => in_array($d['locale'] ?? null, self::LANGS, true) ? $d['locale'] : 'ru',
            'source' => $this->source($d['source'] ?? null),
            'customer' => [
                'name' => self::text($c['name'] ?? '', 100) ?: null, 'phone' => $phone,
                'preferred_channel' => $s->has('channel', $c['preferred_channel'] ?? null) ? $c['preferred_channel'] : null,
                'preferred_time' => self::text($c['preferred_time'] ?? '', 100) ?: null,
                'email' => self::text($c['email'] ?? '', 150) ?: null,
                'company' => self::text($c['company'] ?? '', 150) ?: null,
                'role' => $s->has('role', $c['role'] ?? null) ? $c['role'] : null,
            ],
            'consent' => ['project_contact' => true, 'policy_version' => self::text($consent['policy_version'] ?? '', 40)],
        ];
        $email = $clean['customer']['email'];
        if ($email !== null && !preg_match('/\A[^@\s]+@[^@\s]+\.[^@\s]+\z/u', $email)) {
            $err['customer.email'] = 'Проверьте адрес электронной почты';
        }
        if ($lt === 'quick') {
            $q = is_array($d['quick'] ?? null) ? $d['quick'] : [];
            if (!$s->has('quick_type', $q['request_type'] ?? null)) {
                $err['quick.request_type'] = 'Выберите, чем помочь';
            }
            $clean['quick'] = [
                'request_type' => $s->has('quick_type', $q['request_type'] ?? null) ? $q['request_type'] : null,
                'message' => self::text($q['message'] ?? '', 1000) ?: null,
                'context' => self::text($q['context'] ?? '', 200) ?: null,
            ];
        } elseif ($lt === 'project') {
            [$projectErr, $clean['project']] = $this->project(is_array($d['project'] ?? null) ? $d['project'] : []);
            $err += $projectErr;
        }
        return [$err, $clean];
    }

    /** @return array<string,mixed> */
    private function source(mixed $src): array
    {
        $out = [];
        foreach (is_array($src) ? $src : [] as $k => $v) {
            if (!in_array($k, self::SOURCE_KEYS, true)) {
                continue;
            }
            $out[$k] = is_array($v) ? $this->shortMap($v) : (is_scalar($v) ? self::text($v, 300) : null);
        }
        return $out;
    }

    /** @param array<mixed> $v @return array<string,string> */
    private function shortMap(array $v): array
    {
        $out = [];
        foreach (array_slice($v, 0, 10, true) as $k => $item) {
            if (is_scalar($item)) {
                $out[self::text($k, 40)] = self::text($item, 100);
            }
        }
        return $out;
    }

    /** @param array<string,mixed> $p @return array{0: array<string,string>, 1: array<string,mixed>} */
    private function project(array $p): array
    {
        $s = $this->schema;
        $err = [];
        if (!$s->has('category', $p['category'] ?? null)) {
            $err['project.category'] = 'Выберите, что хотите сделать';
        }
        if (!$s->has('city', $p['city'] ?? null)) {
            $err['project.city'] = 'Выберите город';
        }
        $pr = [];
        foreach (self::PROJECT_KEYS as $k) {
            if (array_key_exists($k, $p)) {
                $pr[$k] = $p[$k];
            }
        }
        foreach (self::PROJECT_GROUPS as $k => $group) {
            if (($pr[$k] ?? null) !== null && !$s->has($group, $pr[$k])) {
                $err['project.' . $k] = 'Недопустимое значение';
            }
        }
        $styles = is_array($pr['style_preferences'] ?? null) ? $pr['style_preferences'] : [];
        $pr['style_preferences'] = array_values(array_filter($styles, fn($x) => $s->has('style', $x)));
        [$pr['dimensions_known'], $pr['dimensions_mm'], $dimErr] = $this->dimensions($pr);
        $pr['description'] = self::text($pr['description'] ?? '', 2000) ?: null;
        $pr['style_note'] = self::text($pr['style_note'] ?? '', 500) ?: null;
        [$pr['attachment_ids'], $idErr] = $this->attachmentIds($pr['attachment_ids'] ?? []);
        $pr['features'] = $this->features($pr['features'] ?? []);
        $cat = $p['category'] ?? null;
        $required = $s->has('category', $cat) ? $this->required($pr, (string)$cat) : [];
        return [$err + $dimErr + $idErr + $required, $pr];
    }

    /** @param array<string,mixed> $pr @return array{0: bool, 1: array<string,int>|null, 2: array<string,string>} */
    private function dimensions(array $pr): array
    {
        $raw = $pr['dimensions_mm'] ?? null;
        if (empty($pr['dimensions_known']) || !is_array($raw) || array_is_list($raw)) {
            return [false, null, []];
        }
        $err = [];
        $dm = [];
        foreach ($raw as $k => $v) {
            if ($v === null || $v === '') {
                continue;
            }
            $key = self::text($k, 20);
            $n = self::toInt($v);
            if ($n === null) {
                $err['project.dimensions_mm.' . $key] = 'Размер должен быть числом';
                continue;
            }
            if ($n < 100 || $n > 30000) {
                $err['project.dimensions_mm.' . $key] = 'Размер вне допустимых пределов';
            }
            $dm[$key] = $n;
        }
        return [$dm !== [], $dm ?: null, $err];
    }

    private static function toInt(mixed $v): ?int
    {
        if (is_int($v)) {
            return $v;
        }
        if (is_float($v)) {
            return is_finite($v) ? (int)max(-1.0e12, min(1.0e12, $v)) : null; // огромные числа уходят за допустимые пределы, а не ломают приведение типа
        }
        return is_string($v) && preg_match('/\A\s*-?\d{1,9}\s*\z/', $v) ? (int)$v : null;
    }

    /** @return array{0: list<string>, 1: array<string,string>} */
    private function attachmentIds(mixed $ids): array
    {
        $max = (int)$this->schema->limits()['max_files'];
        if (!is_array($ids) || count($ids) > $max) {
            return [[], ['project.attachment_ids' => 'Слишком много файлов']];
        }
        $out = [];
        foreach ($ids as $id) {
            if (!is_string($id) || !preg_match('/\A[0-9a-f]{32}\z/', $id)) {
                return [[], ['project.attachment_ids' => 'Некорректный файл: повторите загрузку']];
            }
            $out[] = $id;
        }
        return [$out, []];
    }

    /** @return array<string,mixed> */
    private function features(mixed $f): array
    {
        $s = $this->schema;
        $out = [];
        foreach (is_array($f) ? $f : [] as $k => $v) {
            $out[self::text($k, 40)] = $this->featureValue($v);
        }
        foreach (['object_type', 'task', 'quantity'] as $k) {
            if (is_string($out[$k] ?? null)) {
                $out[$k] = trim(mb_substr($out[$k], 0, 500)) ?: null;
            }
        }
        foreach (self::FEATURE_LISTS as $k => $group) {
            if (($out[$k] ?? null) !== null) {
                $list = is_array($out[$k]) ? $out[$k] : [];
                $out[$k] = array_values(array_filter($list, fn($x) => $s->has($group, $x)));
            }
        }
        return $out;
    }

    private function featureValue(mixed $v): mixed
    {
        if (is_string($v)) {
            return mb_substr($v, 0, 500);
        }
        if (is_int($v) || is_bool($v) || $v === null) {
            return $v;
        }
        if (is_array($v) && array_is_list($v)) {
            return array_values(array_map(
                static fn($x) => is_string($x) ? mb_substr($x, 0, 100) : (is_int($x) ? $x : null),
                array_slice($v, 0, 30),
            ));
        }
        return null;
    }

    /**
     * Без этих ответов заявка «полупустая».
     * @param array<string,mixed> $pr @return array<string,string>
     */
    private function required(array $pr, string $cat): array
    {
        $s = $this->schema;
        $f = $pr['features'];
        $e = [];
        $need = function (string $key, bool $ok, string $msg) use (&$e): void {
            if (!$ok) {
                $e['project.' . $key] = $msg;
            }
        };
        $need('premise', $s->has('premise', $pr['premise'] ?? null), 'Укажите, где будет стоять мебель');
        $need('style_preferences', $pr['style_preferences'] !== [], 'Выберите внешний вид');
        if ($cat === 'kitchen') {
            $need('layout', $s->has('kitchen_layout', $pr['layout'] ?? null), 'Укажите планировку кухни');
            foreach (['upper_cabinets', 'island', 'built_in_appliances'] as $k) {
                $need('features.' . $k, $s->has('yes_no', $f[$k] ?? null), 'Ответьте про ' . $k);
            }
        } elseif ($cat === 'wardrobe') {
            $need('wardrobe_kind', $s->has('wardrobe_kind', $pr['wardrobe_kind'] ?? null), 'Укажите, какой шкаф нужен');
            $need('features.door_type', !empty($f['door_type']), 'Выберите тип дверей');
            $need('features.storage_priorities', !empty($f['storage_priorities']), 'Выберите, что хранить внутри');
        } elseif ($cat === 'other_furniture') {
            $need('features.purposes', !empty($f['purposes']), 'Укажите назначение мебели');
        } elseif ($cat === 'business') {
            $need('business_scope', $s->has('business_scope', $pr['business_scope'] ?? null), 'Укажите, сколько объектов');
            $need('features.object_type', !empty($f['object_type']), 'Укажите тип объекта');
            $need('features.task', !empty($f['task']), 'Опишите задачу');
            $need('features.quantity', !empty($f['quantity']), 'Укажите количество');
        } else {
            $need('description', mb_strlen(trim((string)($pr['description'] ?? ''))) >= 5, 'Опишите, что вы хотите сделать');
        }
        return $e;
    }
}
