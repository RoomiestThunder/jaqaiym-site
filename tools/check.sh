#!/usr/bin/env bash
# Все проверки проекта одной командой: bash tools/check.sh
# Те же шаги выполняет CI (.github/workflows/ci.yml), поэтому результат здесь и на GitHub совпадает.
# Нужны: php 8.1+ (curl, mbstring, pdo_sqlite), python3, node.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Синтаксис PHP, Python и JavaScript"
find php -name '*.php' -print0 | xargs -0 -n1 php -l | { grep -v '^No syntax errors' || true; }
python3 -m py_compile server.py notifier.py render.py tools/*.py
node --check public/js/common.js
node --check public/js/wizard.js

echo "== Файлы workflow разбираются как YAML (иначе GitHub не запустит CI)"
python3 - <<'PY'
import glob
try:
    import yaml
except ImportError:
    print('PyYAML не установлен: проверка пропущена')
else:
    for path in sorted(glob.glob('.github/workflows/*.yml')):
        yaml.safe_load(open(path, encoding='utf-8'))
        print('ок', path)
PY

echo "== Тексты (i18n) собраны из актуальных исходников"
python3 tools/gen_i18n.py
git diff --exit-code public/i18n

echo "== Тесты PHP-версии (приём, Telegram, повторы, очистка, правила схемы)"
python3 tools/test_php.py

echo "== Тесты безопасности PHP-версии"
python3 tools/test_php_security.py

echo "== Тесты версии на Python"
python3 tools/test_telegram.py

echo "Все проверки пройдены."
