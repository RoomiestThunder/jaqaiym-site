#!/usr/bin/env python3
"""Проверка Telegram-бота и поиск chat_id общего чата. Только стандартная библиотека.

  python3 tools/telegram_setup.py           бот отвечает? какие чаты он видит (id для TELEGRAM_CHAT_ID)
  python3 tools/telegram_setup.py --test    тестовое сообщение в чат TELEGRAM_CHAT_ID

Токен берётся из переменной TELEGRAM_BOT_TOKEN и нигде не печатается и не сохраняется.
Как найти chat_id группы: добавьте бота в группу и напишите в ней /start@имя_бота (в группе бот по умолчанию видит только команды),
затем запустите скрипт без аргументов. Telegram хранит такие события около суток: если прошло больше, напишите команду ещё раз.
"""
import json, os, sys, urllib.request, urllib.error

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT = os.environ.get('TELEGRAM_CHAT_ID')


def call(method, payload=None):
    req = urllib.request.Request('https://api.telegram.org/bot%s/%s' % (TOKEN, method),
                                 data=json.dumps(payload or {}).encode(), headers={'Content-Type': 'application/json'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=15).read())['result']
    except urllib.error.HTTPError as e:
        try: why = json.loads(e.read()).get('description')
        except Exception: why = e.reason
        sys.exit('Ошибка Telegram %d: %s' % (e.code, why))
    except urllib.error.URLError as e:
        sys.exit('Нет связи с Telegram: %s' % e.reason)


if not TOKEN:
    sys.exit('Задайте токен бота в переменной TELEGRAM_BOT_TOKEN (его выдаёт @BotFather).')

print('Бот: @%s' % call('getMe')['username'])

if '--test' in sys.argv:
    if not CHAT:
        sys.exit('Задайте id чата в переменной TELEGRAM_CHAT_ID.')
    call('sendMessage', {'chat_id': CHAT, 'text': 'Проверка связи: бот JAQAIYM подключён.'})
    print('Тестовое сообщение отправлено в чат %s' % CHAT)
else:
    chats = {}
    for u in call('getUpdates'):
        for part in u.values():
            if isinstance(part, dict) and isinstance(part.get('chat'), dict):
                c = part['chat']
                chats[c['id']] = '%s: %s' % (c.get('type'), c.get('title') or c.get('username') or c.get('first_name') or '')
    if not chats:
        print('Чатов пока не видно. Добавьте бота в группу, напишите там /start@имя_бота и запустите скрипт снова.')
    for cid, name in chats.items():
        print('chat_id %s  (%s)' % (cid, name))
