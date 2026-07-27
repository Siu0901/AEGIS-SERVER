# AEGIS
#
# Windows 에는 make 가 기본 설치되어 있지 않다. 그 경우 각 타깃의 내용을
# 그대로 실행하면 된다 — 특히 verify 는 `bash scripts/verify.sh` 하나면 끝난다.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.ONESHELL:
.DEFAULT_GOAL := help

CASE ?= no_helmet_resolved
ALEMBIC := uv run alembic -c server/infra/db/alembic.ini

.PHONY: help verify fmt dev cams sim mcu migrate seed types

help:  ## 타깃 목록
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

verify:  ## lint + typecheck + pytest + 마이그레이션 + 스모크 + 프론트 빌드
	bash scripts/verify.sh

fmt:  ## 포매팅과 자동 수정
	uv run ruff format .
	uv run ruff check --fix .

dev:  ## docker-compose + 서버 + 프론트
	docker compose up -d
	@echo "postgres/redis/mosquitto/mediamtx 기동 완료"
	$(MAKE) migrate
	@echo "서버:  uv run uvicorn server.app.main:app --reload"
	@echo "프론트: cd front && npm run dev"

cams:  ## 가짜 RTSP 2채널 송출 (mediamtx + ffmpeg)
	bash deploy/fake_cams.sh $(VIDEO)

sim:  ## 가짜 엣지 실행 —  make sim CASE=<이름>
	uv run python -m sim.edge_sim.main --case $(CASE)

mcu:  ## 가짜 ESP32 실행
	uv run python -m sim.mcu_sim.main

migrate:  ## alembic upgrade head
	$(ALEMBIC) upgrade head
	uv run python -m scripts.seed_policies

seed:  ## policies 기본값 시드만 실행
	uv run python -m scripts.seed_policies

types:  ## contracts → front TypeScript 타입 생성
	@echo "skipped — M5 에서 구현한다 (front/src/types/ 에 생성 예정)"
