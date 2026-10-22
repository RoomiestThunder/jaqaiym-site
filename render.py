"""Сборка HTML-страниц из шаблонов public/*.html: подстановка {{ключей}} из i18n и site.json.
Используется и сервером (server.py), и статической сборкой (tools/build_static.py)."""
import json, os, re, sys

LANGS = ('ru', 'kk')
PAGES = {'/': 'index.html', '/index.html': 'index.html', '/request': 'request/index.html', '/request/': 'request/index.html', '/privacy.html': 'privacy.html'}


def load_i18n(public_dir, lang):
    return json.load(open(os.path.join(public_dir, 'i18n', lang + '.json'), encoding='utf-8'))


def split_lang(path):
    if path == '/kk' or path.startswith('/kk/'):
        return 'kk', (path[3:] or '/')
    return 'ru', path


def render_page(public_dir, fname, lang, route, root='', api='', demo=False, noindex=False, static=False):
    """root: префикс сайта (например /jaqaiym-site на GitHub Pages); api: адрес сервера заявок;
    demo: приём заявок не подключён; static: ссылки на /request оканчиваются слэшем (папки на статическом хостинге)."""
    site = json.load(open(os.path.join(public_dir, 'site.json'), encoding='utf-8'))
    i18n, ru = load_i18n(public_dir, lang), load_i18n(public_dir, 'ru')
    base = root + ('' if lang == 'ru' else '/kk')
    alt = (root + '/kk' + route) if lang == 'ru' else (root + (route or '/'))
    cfg = {'phoneDisplay': site['phone_display'], 'phoneTel': site['phone_tel'], 'whatsapp': site['whatsapp'],
           'policyVersion': site['policy_version'], 'policyUrl': base + '/privacy.html', 'base': base, 'root': root, 'api': api, 'demo': demo}
    boot = '<script>window.JQ_LANG=%s;window.JQ_CONFIG=%s;window.I18N=%s;</script>' % (
        json.dumps(lang), json.dumps(cfg, ensure_ascii=False), json.dumps(i18n, ensure_ascii=False).replace('</', '<\\/'))
    special = {'base': base, 'lang': lang, 'alt_href': alt, 'boot': boot, 'phone': site['phone_display'], 'phone_tel': site['phone_tel'], 'wa': site['whatsapp'],
               'og_locale': 'kk_KZ' if lang == 'kk' else 'ru_RU', 'alt_lang': 'ru' if lang == 'kk' else 'kk'}

    def sub(m):
        k = m.group(1)
        if k in special:
            return special[k]
        if k in i18n:
            return i18n[k]
        if k in ru:
            sys.stderr.write('i18n: нет перевода %s для %s\n' % (k, lang))
            return ru[k]
        sys.stderr.write('i18n: нет ключа %s\n' % k)
        return k

    src = open(os.path.join(public_dir, fname), encoding='utf-8').read()
    if root:  # префикс только для «живых» абсолютных путей шаблона (не для {{base}}, он уже с префиксом)
        src = re.sub(r'(\b(?:href|src|content)=")/(?!/)', lambda m: m.group(1) + root + '/', src)
    out = re.sub(r'\{\{([\w.\-]+)\}\}', sub, src)
    if static:
        out = re.sub(r'(/request)(?=[?"#])', r'\1/', out)
    if noindex and 'name="robots"' not in out:
        out = out.replace('<head>', '<head>\n<meta name="robots" content="noindex, nofollow">', 1)
    return out.encode('utf-8')
