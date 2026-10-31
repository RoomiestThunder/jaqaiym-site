#!/usr/bin/env python3
"""Скачивает шрифты Manrope и Playfair Display с Google Fonts один раз и кладёт в public/fonts,
чтобы сайт не обращался к серверам Google (меньше передачи данных за границу, быстрее, работает без доступа к Google).
Запуск: python3 tools/fetch_fonts.py"""
import os, re, urllib.request, hashlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'public', 'fonts')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
URL = 'https://fonts.googleapis.com/css2?family=Manrope:wght@400..800&family=Playfair+Display:wght@400..600&display=swap'
css = urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': UA})).read().decode()
files = {}; out = ['/* Сгенерировано tools/fetch_fonts.py. Шрифты Manrope и Playfair Display (SIL Open Font License). */']
for sub, body in re.findall(r'/\* ([\w-]+) \*/\s*@font-face \{(.*?)\}', css, re.S):
    if sub not in ('cyrillic', 'cyrillic-ext', 'latin', 'latin-ext'): continue
    fam = re.search(r"font-family: '([^']+)'", body).group(1)
    wt = re.search(r'font-weight: ([\d ]+);', body).group(1).strip()
    url = re.search(r'url\((.*?)\)', body).group(1)
    rng = re.search(r'unicode-range: (.*?);', body).group(1)
    name = '%s-%s.woff2' % (fam.lower().replace(' ', '-'), sub)
    if url not in files:
        data = urllib.request.urlopen(url).read(); open(os.path.join(OUT, name), 'wb').write(data); files[url] = (name, len(data))
    out.append("@font-face{font-family:'%s';font-style:normal;font-weight:%s;font-display:swap;src:url(../fonts/%s) format('woff2');unicode-range:%s}" % (fam, wt, files[url][0], rng))
open(os.path.join(ROOT, 'public', 'css', 'fonts.css'), 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print(len(files), 'файлов,', sum(v[1] for v in files.values()) // 1024, 'КБ'); [print(' ', v[0], v[1] // 1024, 'КБ') for v in files.values()]
