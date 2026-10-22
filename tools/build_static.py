#!/usr/bin/env python3
"""Статическая сборка для GitHub Pages (демо без сервера заявок).

  python3 tools/build_static.py /jaqaiym-site docs

Первый аргумент — префикс сайта (для проектного сайта GitHub Pages это /<имя-репозитория>; для корня домена — пустая строка '').
Результат: docs/ (ru в корне, kk в /kk/). Страницы помечены noindex, анкета работает в демо-режиме: заявки не принимаются.
"""
import os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from render import render_page  # noqa: E402

PUBLIC = os.path.join(ROOT, 'public')
root = (sys.argv[1] if len(sys.argv) > 1 else '').rstrip('/')
out = os.path.join(ROOT, sys.argv[2] if len(sys.argv) > 2 else 'docs')

shutil.rmtree(out, ignore_errors=True)
os.makedirs(out)
for d in ('css', 'js'):
    shutil.copytree(os.path.join(PUBLIC, d), os.path.join(out, d))
shutil.copytree(os.path.join(PUBLIC, 'img'), os.path.join(out, 'img'), ignore=shutil.ignore_patterns('own'))  # свои неиспользуемые фото не публикуем
shutil.copy(os.path.join(PUBLIC, 'schema.json'), out)

pages = [('/', 'index.html', 'index.html'), ('/request', 'request/index.html', 'request/index.html'), ('/privacy.html', 'privacy.html', 'privacy.html')]
for lang in ('ru', 'kk'):
    for route, src, dst in pages:
        body = render_page(PUBLIC, src, lang, route, root=root, api='', demo=True, noindex=True, static=True)
        path = os.path.join(out, dst) if lang == 'ru' else os.path.join(out, 'kk', dst)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'wb').write(body)

open(os.path.join(out, '.nojekyll'), 'w').close()
open(os.path.join(out, '404.html'), 'w', encoding='utf-8').write(
    '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>JAQAIYM</title><meta http-equiv="refresh" content="0;url=%s/"><a href="%s/">JAQAIYM</a>' % (root, root))
size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(out) for f in fs)
print('готово: %s (%.1f МБ), префикс %r' % (out, size / 1e6, root))
