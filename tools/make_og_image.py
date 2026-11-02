#!/usr/bin/env python3
"""Собирает превью для соцсетей и мессенджеров (public/img/brand/og.jpg, 1200x630): логотип слева, фото справа.

  python3 tools/make_og_image.py

Нужен Pillow (pip install pillow). Готовый og.jpg лежит в репозитории, так что запускать скрипт нужно только при смене фото или логотипа:
остальные инструменты проекта Pillow не требуют.
"""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, 'public', 'img')
SIZE = (1200, 630)
BACKGROUND = (251, 243, 228)  # #fbf3e4, цвет страниц сайта
PHOTO_WIDTH = 540
LOGO_WIDTH = 480


def main():
    card = Image.new('RGB', SIZE, BACKGROUND)
    photo = Image.open(os.path.join(IMG, 'work', 'hero.jpg')).convert('RGB')
    scaled = photo.resize((PHOTO_WIDTH, round(photo.height * PHOTO_WIDTH / photo.width)), Image.LANCZOS)
    top = (scaled.height - SIZE[1]) // 2
    card.paste(scaled.crop((0, top, PHOTO_WIDTH, top + SIZE[1])), (SIZE[0] - PHOTO_WIDTH, 0))
    logo = Image.open(os.path.join(IMG, 'brand', 'wordmark.png')).convert('RGBA')
    logo = logo.resize((LOGO_WIDTH, round(logo.height * LOGO_WIDTH / logo.width)), Image.LANCZOS)
    card.paste(logo, ((SIZE[0] - PHOTO_WIDTH - LOGO_WIDTH) // 2, (SIZE[1] - logo.height) // 2), logo)
    out = os.path.join(IMG, 'brand', 'og.jpg')
    card.save(out, quality=88, optimize=True, progressive=True)
    print('готово: %s (%d КБ)' % (out, os.path.getsize(out) // 1024))


if __name__ == '__main__':
    main()
