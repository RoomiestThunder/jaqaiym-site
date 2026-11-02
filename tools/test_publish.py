#!/usr/bin/env python3
"""Проверка tools/publish_deploy.sh на временном репозитории: что и как попадает в ветку deploy, которую забирает Plesk.
Сеть не нужна: «GitHub» здесь обычный bare-репозиторий в папке."""
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'tools', 'publish_deploy.sh')
fails = []


def check(cond, name):
    print('  %s   %s' % ('ok  ' if cond else 'FAIL', name))
    if not cond:
        fails.append(name)


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def publish(dist, remote, message='deploy: тест'):
    return sh('bash', SCRIPT, dist, remote, 'deploy', message)


def files_in_branch(remote):
    out = sh('git', '--git-dir', remote, 'ls-tree', '-r', '-z', '--name-only', 'deploy').stdout  # -z: русские имена без экранирования
    return sorted(n for n in out.split('\0') if n)


def commits(remote):
    return sh('git', '--git-dir', remote, 'rev-list', '--count', 'deploy').stdout.strip()


def main():
    tmp = tempfile.mkdtemp(prefix='jq-publish-')
    try:
        dist, remote = os.path.join(tmp, 'dist'), os.path.join(tmp, 'remote.git')
        subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'build_php.py'), '--noindex', '--out', dist], check=True, stdout=subprocess.DEVNULL)
        sh('git', 'init', '--bare', '--quiet', '--initial-branch', 'main', remote)
        print('Публикация сборки в ветку deploy')

        r = publish(dist, remote)
        names = files_in_branch(remote)
        check(r.returncode == 0 and 'Выложено' in r.stdout, 'первая публикация создаёт ветку deploy ' + r.stderr.strip())
        check(any(n.startswith('httpdocs/') for n in names) and any(n.startswith('jaqaiym-private/src/') for n in names), 'в ветке папки httpdocs и jaqaiym-private/src')
        check('httpdocs/.htaccess' in names and 'httpdocs/api/index.php' in names and 'jaqaiym-private/.htaccess' in names, 'скрытые файлы (.htaccess) и точка входа api/index.php на месте')
        check(not [n for n in names if n.endswith(('config.env', '.db', '.log')) or '/data/' in n or '/uploads/' in n], 'в ветке нет секретов, баз, журналов и данных')
        check(not [n for n in names if n.split('/')[0] not in ('httpdocs', 'jaqaiym-private')], 'в корне ветки только httpdocs и jaqaiym-private (на хостинг не попадёт ничего лишнего)')

        r = publish(dist, remote)
        check(r.returncode == 0 and 'выкладывать нечего' in r.stdout and commits(remote) == '1', 'повтор без изменений: новый коммит не создаётся')

        os.remove(os.path.join(dist, 'httpdocs', 'privacy.html'))
        with open(os.path.join(dist, 'httpdocs', 'новое.txt'), 'w', encoding='utf-8') as f:
            f.write('x')
        r = publish(dist, remote, 'deploy: второе обновление')
        names = files_in_branch(remote)
        check(r.returncode == 0 and commits(remote) == '2', 'изменение сборки даёт второй коммит поверх первого (история сохраняется, pull на хостинге пройдёт без force)')
        check('httpdocs/privacy.html' not in names and 'httpdocs/новое.txt' in names, 'удалённый файл исчез из ветки, новый появился')

        for bad in ('jaqaiym-private/config.env', 'jaqaiym-private/data/leads.db'):
            path = os.path.join(dist, *bad.split('/'))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'w').close()
            r = publish(dist, remote, 'deploy: должно сорваться')
            check(r.returncode != 0 and 'которых там быть не должно' in r.stderr, 'сборка с «%s» отвергается' % bad)
            shutil.rmtree(os.path.join(dist, 'jaqaiym-private', 'data'), ignore_errors=True)
            if os.path.exists(path):
                os.remove(path)
        check(commits(remote) == '2', 'отвергнутые сборки в ветку не попали')

        r = publish(os.path.join(tmp, 'нет-такой-папки'), remote)
        check(r.returncode != 0 and 'это не сборка' in r.stderr, 'не сборка вместо папки dist: отказ с понятным сообщением')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('\nИтог: провалено проверок: %d' % len(fails) if fails else '\nИтог: все проверки публикации пройдены')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
