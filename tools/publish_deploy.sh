#!/usr/bin/env bash
# Выкладывает готовую сборку (папки httpdocs и jaqaiym-private из tools/build_php.py) в ветку deploy репозитория.
# Эту ветку забирает Plesk (Git, автоматический режим), поэтому в ней только то, что должно оказаться на хостинге.
#
#   bash tools/publish_deploy.sh <папка сборки> <адрес репозитория> [ветка=deploy] [сообщение коммита]
#
# История ветки сохраняется (обычный коммит и push без --force): Plesk делает pull, а не перезапись.
# Если сборка не изменилась, коммита нет и хостинг не дёргается.
set -euo pipefail

dist=${1:?нужна папка сборки}
remote=${2:?нужен адрес репозитория}
branch=${3:-deploy}
message=${4:-"deploy: сборка сайта"}

if [ ! -d "$dist/httpdocs" ] || [ ! -d "$dist/jaqaiym-private" ]; then
    echo "В $dist нет папок httpdocs и jaqaiym-private: это не сборка tools/build_php.py." >&2
    exit 1
fi
# Последняя защита: секреты, базы и загруженные файлы в ветку попасть не должны никогда.
leaks=$(find "$dist" \( -name '*.env' -o -name '*.db' -o -name '*.db-*' -o -name '*.log' -o -name data -o -name uploads -o -name locks \) -print)
if [ -n "$leaks" ]; then
    echo "В сборке найдены файлы, которых там быть не должно:" >&2
    echo "$leaks" >&2
    exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
repo="$work/repo"

if git ls-remote --exit-code --heads "$remote" "$branch" >/dev/null 2>&1; then
    git clone --quiet --depth 1 --branch "$branch" "$remote" "$repo"
else
    git init --quiet --initial-branch "$branch" "$repo"
    git -C "$repo" remote add origin "$remote"
fi

# ветка должна совпадать со сборкой полностью: удалённые файлы исчезают и с хостинга
find "$repo" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -a "$dist/." "$repo/"

cd "$repo"
git add -A
if git diff --cached --quiet; then
    echo "Сборка не изменилась: выкладывать нечего."
    exit 0
fi
git -c user.name="${GIT_AUTHOR_NAME:-github-actions[bot]}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}" \
    commit --quiet -m "$message"
git push --quiet origin "$branch"
echo "Выложено в ветку $branch: $(git rev-parse --short HEAD)"
