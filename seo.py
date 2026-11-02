"""Всё для поисковиков в одном месте: адреса страниц, теги в <head>, разметка schema.org, robots.txt и sitemap.xml.
Используется render.py (теги страниц) и tools/build_static.py (robots.txt и sitemap.xml боевой сборки)."""
import html, json
from xml.sax.saxutils import escape

LANG_TAGS = {'ru': 'ru_RU', 'kk': 'kk_KZ'}
# страницы, которые должны попадать в поиск (маршрут без языка). Анкета (/request) закрыта от индексации в самом шаблоне.
INDEXABLE = ('/', '/privacy.html')
OG_IMAGE = ('/img/brand/og.jpg', 1200, 630)
CITIES = ('Астана', 'Алматы')


def page_path(route, lang):
    """Путь страницы на сайте: русская в корне, казахская в /kk/."""
    route = '/' if route in ('/', '/index.html') else route
    return route if lang == 'ru' else '/kk' + route


def page_urls(site_url, route):
    """Адреса одной страницы на обоих языках (абсолютные, для canonical, hreflang и sitemap)."""
    return {lang: site_url + page_path(route, lang) for lang in LANG_TAGS}


def _attr(value):
    return html.escape(value, quote=True)


def _meta(prop, value, attr='property'):
    return '<meta %s="%s" content="%s">' % (attr, prop, _attr(value))


def demo_head(i18n, lang, root):
    """Для демо на GitHub Pages: прежние теги без абсолютных адресов (демо закрыто от индексации)."""
    return '\n'.join([
        _meta('og:title', i18n['meta.title']), _meta('og:description', i18n['meta.desc']), _meta('og:locale', LANG_TAGS[lang]),
        _meta('og:image', root + '/img/work/hero.jpg'),
        '<link rel="alternate" hreflang="ru" href="%s/">' % root, '<link rel="alternate" hreflang="kk" href="%s/kk/">' % root,
    ])


def structured_data(site, i18n, lang, site_url):
    graph = [
        {'@type': 'Organization', '@id': site_url + '/#organization', 'name': 'JAQAIYM', 'legalName': site['legal_name'], 'url': site_url + '/',
         'logo': site_url + '/img/brand/wordmark.png', 'description': i18n['meta.desc'],
         'areaServed': [{'@type': 'City', 'name': name} for name in CITIES]},
        {'@type': 'WebSite', '@id': site_url + '/#website', 'url': site_url + '/', 'name': 'JAQAIYM', 'inLanguage': lang,
         'publisher': {'@id': site_url + '/#organization'}},
    ]
    data = json.dumps({'@context': 'https://schema.org', '@graph': graph}, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    return '<script type="application/ld+json">%s</script>' % data


def head(site, i18n, lang, route, indexing):
    """Теги страницы для боевого сайта: адрес-эталон, языковые версии, карточки соцсетей, разметка, правило для роботов.
    indexing=False: сайт закрыт (до запуска), запрет индексации добавляет render.py, здесь остальные теги."""
    site_url = site['site_url'].rstrip('/')
    urls = page_urls(site_url, route)
    home = route in ('/', '/index.html')
    title, desc = (i18n['meta.title'], i18n['meta.desc']) if home else (i18n['priv.title'], i18n['priv.desc'])
    other = 'kk' if lang == 'ru' else 'ru'
    image = site_url + OG_IMAGE[0]
    tags = [
        '<link rel="canonical" href="%s">' % _attr(urls[lang]),
        '<link rel="alternate" hreflang="ru" href="%s">' % _attr(urls['ru']),
        '<link rel="alternate" hreflang="kk" href="%s">' % _attr(urls['kk']),
        '<link rel="alternate" hreflang="x-default" href="%s">' % _attr(urls['ru']),
        _meta('og:type', 'website'), _meta('og:site_name', 'JAQAIYM'), _meta('og:url', urls[lang]),
        _meta('og:title', title), _meta('og:description', desc),
        _meta('og:locale', LANG_TAGS[lang]), _meta('og:locale:alternate', LANG_TAGS[other]),
        _meta('og:image', image), _meta('og:image:width', str(OG_IMAGE[1])), _meta('og:image:height', str(OG_IMAGE[2])), _meta('og:image:alt', i18n['meta.title']),
        _meta('twitter:card', 'summary_large_image', 'name'), _meta('twitter:title', title, 'name'), _meta('twitter:description', desc, 'name'),
        _meta('twitter:image', image, 'name'),
    ]
    if indexing:
        tags.append('<meta name="robots" content="index, follow, max-image-preview:large">')
    if home:
        tags.append(structured_data(site, i18n, lang, site_url))
    return '\n'.join(tags)


def robots_txt(site_url, indexing):
    if not indexing:
        return 'User-agent: *\nDisallow: /\n'
    return 'User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: %s/sitemap.xml\n' % site_url


def sitemap_xml(site_url):
    rows = []
    for route in INDEXABLE:
        urls = page_urls(site_url, route)
        alternates = ''.join('<xhtml:link rel="alternate" hreflang="%s" href="%s"/>' % (hreflang, escape(href))
                             for hreflang, href in (('ru', urls['ru']), ('kk', urls['kk']), ('x-default', urls['ru'])))
        rows.extend('<url><loc>%s</loc>%s</url>' % (escape(urls[lang]), alternates) for lang in LANG_TAGS)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
            + '\n'.join(rows) + '\n</urlset>\n')
