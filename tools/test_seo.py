#!/usr/bin/env python3
"""Проверки для поисковиков: теги страниц, разметка, robots.txt и sitemap.xml в трёх режимах сборки
(сайт открыт, сайт закрыт до запуска, демо для GitHub Pages).

  python3 tools/test_seo.py
"""
import json, os, re, shutil, struct, subprocess, sys, tempfile
import xml.dom.minidom

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import seo  # noqa: E402
from build_static import build_site  # noqa: E402

SITE = json.load(open(os.path.join(ROOT, 'public', 'site.json'), encoding='utf-8'))
URL = SITE['site_url'].rstrip('/')
fails = []
PAGES = {'ru': ('index.html', 'privacy.html', 'request/index.html'), 'kk': ('kk/index.html', 'kk/privacy.html', 'kk/request/index.html')}
TITLE_MAX, DESC_MIN, DESC_MAX = 65, 70, 160


def check(cond, name):
    print('  %s   %s' % ('ok  ' if cond else 'FAIL', name))
    if not cond:
        fails.append(name)


def read(base, rel):
    return open(os.path.join(base, rel), encoding='utf-8').read()


def tag(html, pattern):
    return re.findall(pattern, html)


def jpeg_size(path):
    """Размер JPEG из заголовка (без сторонних библиотек)."""
    data = open(path, 'rb').read()
    i = 2
    while i < len(data):
        marker = data[i + 1]
        length = struct.unpack('>H', data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack('>HH', data[i + 5:i + 9])
            return width, height
        i += 2 + length
    return None


def build(out, noindex):
    subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'build_php.py'), '--out', out] + (['--noindex'] if noindex else []), check=True, stdout=subprocess.DEVNULL)
    return os.path.join(out, 'httpdocs')


def section_open(web):
    print('Сайт открыт для индексации')
    for lang, (home, privacy, request) in PAGES.items():
        h, p, r = read(web, home), read(web, privacy), read(web, request)
        title = tag(h, r'<title>(.*?)</title>')[0]
        desc = tag(h, r'<meta name="description" content="([^"]*)"')[0]
        check(len(title) <= TITLE_MAX and 'JAQAIYM' in title, '%s: заголовок главной до %d знаков и с названием бренда (%d)' % (lang, TITLE_MAX, len(title)))
        check(DESC_MIN <= len(desc) <= DESC_MAX, '%s: описание главной %d-%d знаков, поисковик не обрежет (%d)' % (lang, DESC_MIN, DESC_MAX, len(desc)))
        check(h.count('<h1') == 1, '%s: на главной ровно один заголовок h1' % lang)
        check(tag(h, r'<html lang="(\w+)"') == [lang], '%s: язык страницы в <html lang>' % lang)
        route = '/' if lang == 'ru' else '/kk/'
        check(tag(h, r'<link rel="canonical" href="([^"]*)"') == [URL + route], '%s: canonical главной ведёт на себя (%s)' % (lang, URL + route))
        langs = dict(tag(h, r'<link rel="alternate" hreflang="([\w-]+)" href="([^"]*)"'))
        check(langs == {'ru': URL + '/', 'kk': URL + '/kk/', 'x-default': URL + '/'}, '%s: hreflang ru, kk и x-default с абсолютными адресами' % lang)
        check(tag(h, r'<meta name="robots" content="([^"]*)"') == ['index, follow, max-image-preview:large'] and 'noindex' not in h, '%s: главная явно открыта для роботов, noindex нет' % lang)
        check(tag(h, r'property="og:url" content="([^"]*)"') == [URL + route] and tag(h, r'property="og:image" content="([^"]*)"') == [URL + '/img/brand/og.jpg'],
              '%s: og:url и og:image абсолютные' % lang)
        check(tag(h, r'property="og:locale" content="(\w+)"') == [seo.LANG_TAGS[lang]] and 'twitter:card" content="summary_large_image"' in h, '%s: язык карточки и тип twitter:card' % lang)
        blocks = tag(h, r'<script type="application/ld\+json">(.*?)</script>')
        data = json.loads(blocks[0]) if len(blocks) == 1 else {}
        graph = {node.get('@type'): node for node in data.get('@graph', [])}
        org = graph.get('Organization', {})
        check(set(graph) == {'Organization', 'WebSite'} and org.get('legalName') == SITE['legal_name'] and org.get('url') == URL + '/', '%s: разметка schema.org (Organization и WebSite) разбирается' % lang)
        check({c['name'] for c in org.get('areaServed', [])} == set(seo.CITIES), '%s: в разметке города работы: Астана и Алматы' % lang)
        check(not ({'telephone', 'address', 'email', 'taxID', 'vatID'} & set(org)), '%s: в разметке нет телефона, адреса, почты и БИН (их нельзя подтвердить)' % lang)
        pdesc = tag(p, r'<meta name="description" content="([^"]*)"')
        check(len(pdesc) == 1 and DESC_MIN <= len(pdesc[0]) <= DESC_MAX and tag(p, r'<link rel="canonical" href="([^"]*)"') == [URL + seo.page_path('/privacy.html', lang)],
              '%s: у политики есть описание и canonical' % lang)
        check('noindex' in r and 'rel="canonical"' not in r, '%s: анкета закрыта от индексации (noindex) и без canonical' % lang)
    size = jpeg_size(os.path.join(web, 'img', 'brand', 'og.jpg'))
    check(size == (seo.OG_IMAGE[1], seo.OG_IMAGE[2]), 'картинка превью og.jpg есть и имеет заявленный размер %s: %s' % ((seo.OG_IMAGE[1], seo.OG_IMAGE[2]), size))
    check(os.path.getsize(os.path.join(web, 'img', 'brand', 'og.jpg')) < 300 * 1024, 'og.jpg легче 300 КБ (мессенджеры не показывают тяжёлые превью)')
    robots = read(web, 'robots.txt')
    check('Allow: /' in robots and 'Disallow: /api/' in robots and ('Sitemap: %s/sitemap.xml' % URL) in robots and not re.search(r'^Disallow: /$', robots, re.M),
          'robots.txt открывает сайт, закрывает /api/ и указывает sitemap.xml')
    check('admin' not in robots.lower(), 'robots.txt не упоминает админку')
    doc = xml.dom.minidom.parseString(read(web, 'sitemap.xml').encode('utf-8'))
    locs = [n.firstChild.data for n in doc.getElementsByTagName('loc')]
    check(locs == [URL + '/', URL + '/kk/', URL + '/privacy.html', URL + '/kk/privacy.html'], 'sitemap.xml: 4 страницы (главная и политика на двух языках), анкеты в нём нет')
    check(all(os.path.exists(os.path.join(web, loc[len(URL) + 1:] or 'index.html')) or os.path.exists(os.path.join(web, loc[len(URL) + 1:], 'index.html')) for loc in locs),
          'sitemap.xml: каждый адрес соответствует существующей странице')
    check(all(len(n.getElementsByTagName('xhtml:link')) == 3 for n in doc.getElementsByTagName('url')), 'sitemap.xml: у каждой страницы три языковые ссылки (ru, kk, x-default)')
    token = SITE['yandex_verification']
    homes = [read(web, 'index.html'), read(web, 'kk/index.html')]
    others = [read(web, p) for p in ('privacy.html', 'kk/privacy.html', 'request/index.html')]
    check(all(tag(h, r'<meta name="yandex-verification" content="([^"]*)"') == [token] for h in homes) and not any('yandex-verification' in o for o in others),
          'метатег подтверждения Яндекс Вебмастера только на главных страницах')
    ht = open(os.path.join(ROOT, 'php', 'httpdocs', '.htaccess'), encoding='utf-8').read()
    check('RewriteCond %{HTTP_HOST} ^www\\.(.+)$ [NC]' in ht and 'R=301' in ht, '.htaccess: адрес с www ведёт на основной домен постоянным перенаправлением')


def section_closed(web):
    print('Сайт закрыт до запуска (--noindex)')
    pages = [p for group in PAGES.values() for p in group]
    check(all('name="robots" content="noindex' in read(web, p) for p in pages), 'все 6 страниц с noindex')
    check(all('index, follow' not in read(web, p) for p in pages), 'ни на одной странице нет разрешения индексировать')
    check(read(web, 'robots.txt') == 'User-agent: *\nDisallow: /\n', 'robots.txt запрещает роботам всё')
    check(not os.path.exists(os.path.join(web, 'sitemap.xml')), 'sitemap.xml не публикуется')


def section_demo(tmp):
    print('Демо для GitHub Pages')
    out = os.path.join(tmp, 'demo')
    build_site(out, root='/jaqaiym-site', demo=True, noindex=True)
    pages = [p for group in PAGES.values() for p in group]
    check(all('name="robots" content="noindex' in read(out, p) for p in pages), 'все страницы демо с noindex')
    heads = [read(out, p).split('</head>')[0] for p in pages]
    check(all('rel="canonical"' not in h and 'application/ld+json' not in h and URL not in h for h in heads),
          'в <head> демо нет canonical, разметки и адресов боевого домена (демо не должно конкурировать с сайтом)')
    check(not os.path.exists(os.path.join(out, 'robots.txt')) and not os.path.exists(os.path.join(out, 'sitemap.xml')), 'в демо нет robots.txt и sitemap.xml')
    check(not any('yandex-verification' in read(out, p) for p in pages), 'в демо нет метатега подтверждения прав (он только на боевом домене)')


def main():
    tmp = tempfile.mkdtemp(prefix='jq-seo-')
    try:
        section_open(build(os.path.join(tmp, 'open'), noindex=False))
        section_closed(build(os.path.join(tmp, 'closed'), noindex=True))
        section_demo(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('\nИтог: провалено проверок: %d' % len(fails) if fails else '\nИтог: все проверки для поисковиков пройдены')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
