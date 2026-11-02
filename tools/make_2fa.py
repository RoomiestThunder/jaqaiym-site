#!/usr/bin/env python3
"""Печатает то, что нужно для двухфакторного входа и непубличного адреса админки: ключ для приложения-аутентификатора
и две строки для config.env на хостинге.

  python3 tools/make_2fa.py

Ничего не читает и не записывает: всё выводится на экран, чтобы вы сами добавили строки в config.env (Plesk, менеджер файлов)
и ввели ключ в приложение (Google Authenticator, Microsoft Authenticator, Aegis, 2FAS, Authy: «Ввести ключ вручную», тип «По времени»).
После этого закройте окно терминала: ключ нигде не сохраняется. Менять ключ можно повторным запуском (старый перестанет работать).
"""
import base64, os, secrets, urllib.parse

ISSUER = 'JAQAIYM'
ACCOUNT = 'admin'
BASE_URL = 'https://jaqaiym.kz'


def new_secret():
    """160 случайных бит в base32 (32 символа без дополняющих знаков)."""
    return base64.b32encode(os.urandom(20)).decode('ascii')


def new_admin_path():
    return '/admin/' + secrets.token_urlsafe(9)


def otpauth_uri(secret):
    label = urllib.parse.quote('%s:%s' % (ISSUER, ACCOUNT))
    return 'otpauth://totp/%s?secret=%s&issuer=%s&algorithm=SHA1&digits=6&period=30' % (label, secret, urllib.parse.quote(ISSUER))


def grouped(secret):
    return ' '.join(secret[i:i + 4] for i in range(0, len(secret), 4))


def main():
    secret, path = new_secret(), new_admin_path()
    print('1. Добавьте в КОНЕЦ файла config.env на хостинге (папка jaqaiym-private) две строки:\n')
    print('   ADMIN_TOTP_SECRET=%s' % secret)
    print('   ADMIN_PATH=%s\n' % path)
    print('2. В приложении-аутентификаторе добавьте аккаунт «Ввести ключ вручную»:')
    print('   название: %s, ключ: %s (тип «По времени», 6 цифр, 30 секунд)' % (ISSUER, grouped(secret)))
    print('   либо одной ссылкой: %s\n' % otpauth_uri(secret))
    print('3. Новый адрес админки: %s%s' % (BASE_URL, path))
    print('   (старый адрес /admin после этого перестанет открываться; ссылки в Telegram переходят на новый автоматически).\n')
    print('Строки и ключ нигде не сохранены. Закройте это окно, когда всё внесено.')


if __name__ == '__main__':
    main()
