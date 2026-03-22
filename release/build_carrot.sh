#!/usr/bin/env bash
set -euo pipefail

SRC="/data/openpilot"
WORK_BASE="/data/tmp"
REPO_URL="https://github.com/ajouatom/openpilot.git"

BRANCH_NAME="${1:-prebuilt-$(date +%y%m%d-%H%M)}"
COMMIT_MSG="${2:-prebuilt: ${BRANCH_NAME}}"

WORK_DIR="${WORK_BASE}/${BRANCH_NAME}"

rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"

rsync -a \
  --exclude='.git' \
  --exclude='.gitignore' \
  "$SRC"/ "$WORK_DIR"/

cd "$WORK_DIR"

find . -name '__pycache__' -type d -prune -exec rm -rf {} +
find . -name '*.pyc' -delete
find . -name '*.pyo' -delete
find . -name '*.o' -delete
find . -name '*.os' -delete
find . -name '*.a' -delete
rm -rf .pytest_cache .mypy_cache .cache
rm -f .sconsign.dblite compile_commands.json

touch prebuilt

git init
git config user.name "ajouatom"
git config user.email "ajouatom@users.noreply.github.com"

git add -A
git commit -m "$COMMIT_MSG"
git branch -M "$BRANCH_NAME"
git remote add origin "$REPO_URL"
git push -f origin "$BRANCH_NAME"