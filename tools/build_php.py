#!/usr/bin/env python3
"""Сборка для хостинга с PHP (ps.kz, Plesk).

  python3 tools/build_php.py [--noindex] [--out dist]

Результат в dist/ (его содержимое кладётся в корень домена, туда, где лежит папка httpdocs):
  httpdocs/            корень сайта: страницы ru/kk, css, js, шрифты, картинки, .htaccess, api/index.php
  jaqaiym-private/     код сервера (src/), задача по расписанию (bin/cron.php), пример настроек (config.env.example)
Папка jaqaiym-private должна лежать ВНЕ httpdocs: база заявок, загруженные файлы и config.env появятся в ней.
--noindex закрывает сайт от поисковиков (для проверки до запуска); без флага сайт открыт для индексации.
"""
import argparse, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from build_static import build_site, folder_size  # noqa: E402

PHP = os.path.join(ROOT, 'php')
SECRET_NAMES = ('.env', 'config.env')


def copy_overlay(out_httpdocs):
    """Точка входа и .htaccess поверх статического сайта."""
    shutil.copytree(os.path.join(PHP, 'httpdocs'), out_httpdocs, dirs_exist_ok=True)


def copy_private(out_private):
    os.makedirs(out_private)
    for name in ('src', 'bin'):
        shutil.copytree(os.path.join(PHP, name), os.path.join(out_private, name), ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy(os.path.join(PHP, 'config.env.example'), out_private)
    open(os.path.join(out_private, '.htaccess'), 'w').write('# если папку случайно положат в корень сайта: не отдавать ничего\nRequire all denied\n')


def assert_clean(out):
    """В сборке не должно быть секретов и лишнего исполняемого кода в корне сайта."""
    for dp, _, fs in os.walk(out):
        for f in fs:
            if f in SECRET_NAMES:
                raise SystemExit('в сборку попал секретный файл: ' + os.path.join(dp, f))
    php_in_web = [os.path.relpath(os.path.join(dp, f), out) for dp, _, fs in os.walk(os.path.join(out, 'httpdocs')) for f in fs if f.endswith('.php')]
    if php_in_web != [os.path.join('httpdocs', 'api', 'index.php')]:
        raise SystemExit('в корне сайта должен быть один PHP-файл api/index.php, а найдено: %s' % php_in_web)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='dist')
    ap.add_argument('--noindex', action='store_true')
    args = ap.parse_args()
    out = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    build_site(os.path.join(out, 'httpdocs'), root='', demo=False, noindex=args.noindex, csp=True)
    copy_overlay(os.path.join(out, 'httpdocs'))
    copy_private(os.path.join(out, 'jaqaiym-private'))
    assert_clean(out)
    print('готово: %s (%.1f МБ), индексация %s' % (out, folder_size(out) / 1e6, 'закрыта' if args.noindex else 'открыта'))


if __name__ == '__main__':
    main()
