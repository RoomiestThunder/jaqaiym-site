#!/usr/bin/env python3
"""Печатает строку ADMIN_PATH для config.env: непубличный адрес админки вместо угадываемого /admin.

  python3 tools/make_admin_path.py

Ничего не читает и не записывает: адрес выводится на экран, вы сами добавляете строку в config.env на хостинге
(Plesk, менеджер файлов, папка jaqaiym-private). Без ADMIN_PATH админка не включается. Сохраните адрес в закладки
или менеджер паролей: кроме вас его знают только те, кому вы его передали, и участники чата Telegram со ссылками на заявки.
Сменить адрес можно повторным запуском (старый перестанет открываться).
"""
import secrets

BASE_URL = 'https://jaqaiym.kz'


def new_admin_path():
    """144 случайных бита: 24 символа из букв, цифр, - и _."""
    return '/admin/' + secrets.token_urlsafe(18)


def main():
    path = new_admin_path()
    print('1. Добавьте в КОНЕЦ файла config.env на хостинге (папка jaqaiym-private) строку:\n')
    print('   ADMIN_PATH=%s\n' % path)
    print('2. Новый адрес админки: %s%s' % (BASE_URL, path))
    print('   (стандартный /admin не открывается; ссылки на заявки в Telegram ведут на новый адрес автоматически).\n')
    print('Адрес нигде не сохранён. Закройте это окно, когда строка внесена.')


if __name__ == '__main__':
    main()
