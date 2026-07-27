#!/usr/bin/env bash
# `make verify` 의 실제 내용.
#
# Makefile 이 이 스크립트를 부른다. Windows 처럼 make 가 없는 환경에서도
# `bash scripts/verify.sh` 로 똑같이 돌릴 수 있도록 로직을 여기 둔다.
#
# 아직 붙지 않은 단계는 "skipped" 로 남기되 자리는 지운다 — 언제 무엇이
# 검증되지 않았는지가 보여야 하기 때문이다.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

FAILED=()
STEP=0

run_step() {
  local name="$1"; shift
  STEP=$(( STEP + 1 ))
  echo ""
  echo "───── [${STEP}] ${name}"
  if "$@"; then
    echo "      ✔ ${name}"
  else
    echo "      ✘ ${name}"
    FAILED+=("${name}")
  fi
}

skip_step() {
  local name="$1" why="$2"
  STEP=$(( STEP + 1 ))
  echo ""
  echo "───── [${STEP}] ${name}"
  echo "      — skipped (${why})"
}

echo "═════ make verify ═════"

# 1. lint
run_step "ruff check" uv run ruff check .
run_step "ruff format --check" uv run ruff format --check .

# 2. typecheck
run_step "mypy (strict)" uv run mypy

# 3. tests
run_step "pytest" uv run pytest

# 4. 마이그레이션 정합 — DB 없이 오프라인 렌더링으로 확인한다.
run_step "alembic 정합" bash -c \
  'uv run alembic -c server/infra/db/alembic.ini upgrade head --sql >/dev/null'

# 5. 서버 부팅 스모크
run_step "서버 부팅 스모크" uv run python -c \
  'from server.app.main import app; assert app.title == "AEGIS"'

# 6. 프론트 빌드
if [[ ! -f front/package.json ]]; then
  skip_step "프론트 빌드" "front/package.json 없음"
elif ! command -v npm >/dev/null 2>&1; then
  skip_step "프론트 빌드" "npm 없음"
else
  if [[ ! -d front/node_modules ]]; then
    echo "      · front/node_modules 없음 → npm ci"
    (cd front && npm ci --silent) || true
  fi
  run_step "프론트 빌드" bash -c '(cd front && npm run build --silent)'
fi

# 7. contracts → front 타입 생성 (M5 에서 붙인다)
skip_step "contracts 타입 정합" "make types 미구현 (M5)"

echo ""
echo "═══════════════════════"
if (( ${#FAILED[@]} == 0 )); then
  echo "✔ verify 통과 (${STEP} 단계)"
  exit 0
fi

echo "✘ verify 실패 — ${#FAILED[@]}건"
for name in "${FAILED[@]}"; do
  echo "   · ${name}"
done
exit 1
