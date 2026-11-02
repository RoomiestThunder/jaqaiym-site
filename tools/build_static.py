#!/usr/bin/env python3
"""Статическая сборка сайта.

  python3 tools/build_static.py /jaqaiym-site docs        # демо для GitHub Pages (заявки не принимаются)

Первый аргумент — префикс сайта (для проектного сайта GitHub Pages это /<имя-репозитория>; для корня домена — пустая строка '').
Результат: docs/ (ru в корне, kk в /kk/). Страницы помечены noindex, анкета работает в демо-режиме.
Боевую сборку для хостинга с PHP делает tools/build_php.py: она использует build_site() отсюда.
"""
import base64, hashlib, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from render import render_page  # noqa: E402

PUBLIC = os.path.join(ROOT, 'public')
PAGES = [('/', 'index.html', 'index.html'), ('/request', 'request/index.html', 'request/index.html'), ('/privacy.html', 'privacy.html', 'privacy.html')]
INLINE_SCRIPT = re.compile(rb'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.S)


def csp_meta(html):
    """Политика безопасности страницы: скрипты только свои и встроенные с известным хешем (подставляется при сборке)."""
    hashes = sorted({"'sha256-%s'" % base64.b64encode(hashlib.sha256(m).digest()).decode() for m in INLINE_SCRIPT.findall(html)})
    policy = ("default-src 'self'; script-src 'self' %s; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; "
              "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'") % ' '.join(hashes)
    return '<meta http-equiv="Content-Security-Policy" content="%s">' % policy.replace('  ', ' ')


def build_site(out, root='', demo=True, noindex=True, csp=False):
    """Собирает ru-страницы в out/ и kk-страницы в out/kk/ вместе с css, js, шрифтами и картинками."""
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    for d in ('css', 'js', 'fonts'):  # шрифты свои, без обращения к Google (см. политику конфиденциальности)
        shutil.copytree(os.path.join(PUBLIC, d), os.path.join(out, d))
    shutil.copytree(os.path.join(PUBLIC, 'img'), os.path.join(out, 'img'), ignore=shutil.ignore_patterns('own'))  # свои неиспользуемые фото не публикуем
    shutil.copy(os.path.join(PUBLIC, 'schema.json'), out)
    for lang in ('ru', 'kk'):
        for route, src, dst in PAGES:
            body = render_page(PUBLIC, src, lang, route, root=root, api='', demo=demo, noindex=noindex, static=True)
            if csp:
                body = body.replace(b'<head>', b'<head>\n' + csp_meta(body).encode(), 1)
            path = os.path.join(out, dst) if lang == 'ru' else os.path.join(out, 'kk', dst)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'wb').write(body)


def folder_size(path):
    return sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(path) for f in fs)


def main():
    root = (sys.argv[1] if len(sys.argv) > 1 else '').rstrip('/')
    out = os.path.join(ROOT, sys.argv[2] if len(sys.argv) > 2 else 'docs')
    build_site(out, root=root, demo=True, noindex=True)
    open(os.path.join(out, '.nojekyll'), 'w').close()
    open(os.path.join(out, '404.html'), 'w', encoding='utf-8').write(
        '<!doctype html><meta charset="utf-8"><meta name="color-scheme" content="only light"><meta name="robots" content="noindex"><title>JAQAIYM</title><meta http-equiv="refresh" content="0;url=%s/"><a href="%s/">JAQAIYM</a>' % (root, root))
    print('готово: %s (%.1f МБ), префикс %r' % (out, folder_size(out) / 1e6, root))


if __name__ == '__main__':
    main()
