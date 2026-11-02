#!/usr/bin/env python3
"""Создаёт боевой config.env для сервера на PHP: новый пароль админки, новый код подписки и токен бота из локального .env.

  python3 tools/make_config.py [--env .env] [--out ~/Desktop/jaqaiym-production-config.env]

Значения на экран не выводятся. Файл создаётся с правами 600 и никогда не перезаписывает существующий.
Дальше вы сами загружаете его в папку jaqaiym-private на хостинге под именем config.env (см. README) и удаляете с компьютера.
"""
import argparse, os, secrets, stat, sys

DEFAULT_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
DEFAULT_OUT = '~/Desktop/jaqaiym-production-config.env'
BASE_URL = 'https://jaqaiym.kz'


def read_env(path):
    values = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"\'')
    return values


def build(bot_token):
    admin, code = secrets.token_urlsafe(32), secrets.token_urlsafe(12)
    return ('# Боевые настройки JAQAIYM. Загрузите в папку jaqaiym-private на хостинге под именем config.env,\n'
            '# затем удалите этот файл с компьютера. Пароль админки (ADMIN_TOKEN) сохраните в менеджере паролей.\n'
            'ADMIN_TOKEN=%s\nPUBLIC_BASE_URL=%s\nTELEGRAM_BOT_TOKEN=%s\nTELEGRAM_JOIN_CODE=%s\n' % (admin, BASE_URL, bot_token, code))


def write_new(path, body):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # O_EXCL: существующий файл не трогаем
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default=DEFAULT_ENV)
    ap.add_argument('--out', default=DEFAULT_OUT)
    args = ap.parse_args()
    out = os.path.expanduser(args.out)
    token = read_env(args.env).get('TELEGRAM_BOT_TOKEN', '') if os.path.isfile(args.env) else ''
    if not token:
        sys.exit('В %s нет TELEGRAM_BOT_TOKEN: сначала задайте токен бота.' % args.env)
    if os.path.exists(out):
        sys.exit('Файл уже существует, не перезаписываю: ' + out)
    body = build(token)
    write_new(out, body)
    names = [line.split('=', 1)[0] for line in body.splitlines() if line and not line.startswith('#')]
    print('Создан %s (права %s). Переменные: %s' % (out, oct(stat.S_IMODE(os.stat(out).st_mode)), ', '.join(names)))
    print('Значения не показаны. Откройте файл на своём компьютере, сохраните ADMIN_TOKEN в менеджере паролей.')
    print('Дальше запустите python3 tools/make_admin_path.py: без ADMIN_PATH админка не включится.')


if __name__ == '__main__':
    main()
