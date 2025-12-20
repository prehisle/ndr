.PHONY: help ps up down reset restart logs logs-app logs-db build \
	venv install migrate dev test test-db test-remote fmt lint typecheck check

APP_PORT ?= 9001
PG_PORT ?= 5541

help:
	@printf "%s\n" \
	"常用命令（支持同机多项目端口池）：" \
	"" \
	"  make up            # 启动（APP_PORT=$(APP_PORT), PG_PORT=$(PG_PORT)）" \
	"  make down          # 停止（保留数据卷）" \
	"  make reset         # 停止并删除数据卷（危险）" \
	"  make ps            # 查看容器状态" \
	"  make logs          # 跟随所有服务日志" \
	"  make logs-app      # 跟随 app 日志" \
	"  make logs-db       # 跟随 postgres 日志" \
	"" \
	"  make venv          # 初始化 .venv（若不存在）" \
	"  make install       # 安装 Python 依赖到 .venv" \
	"  make migrate       # 运行 Alembic 迁移（本地 DB_URL）" \
	"  make dev           # 本地启动（reload，端口 9001）" \
	"" \
	"  make test          # 跑测试（默认跳过远程 requests 用例）" \
	"  make test-remote   # 跑全部测试（包含远程 requests 用例，需要服务已启动）" \
	"  make fmt           # black + isort" \
	"  make lint          # ruff" \
	"  make typecheck     # mypy" \
	"  make check         # fmt + lint + typecheck + test"

ps:
	APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose ps

up:
	APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose up -d --build

down:
	APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose down

reset:
	APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose down -v

restart:
	APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose restart app

logs:
	APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose logs -f

logs-app:
	APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose logs -f app

logs-db:
	APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose logs -f postgres

build:
	APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose build

venv:
	@test -x .venv/bin/python || python3 -m venv .venv

install: venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements.txt

migrate:
	.venv/bin/alembic upgrade head

dev:
	APP_PORT=$(APP_PORT) DB_URL=$${DB_URL:-postgresql+psycopg2://ndr:ndr@localhost:$(PG_PORT)/ndr} \
		AUTO_APPLY_MIGRATIONS=true ENABLE_METRICS=true API_KEY_ENABLED=false \
		.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port $(APP_PORT)

test:
	TEST_DB_URL=$${TEST_DB_URL:-postgresql+psycopg2://ndr:ndr@localhost:$(PG_PORT)/ndr_test} \
		RUN_REMOTE_REQUESTS_TEST=false \
		.venv/bin/pytest

test-db:
	@APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose exec -T postgres \
		psql -U ndr -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='ndr_test'" \
		| tr -d '[:space:]' | grep -q "^1$$" \
		|| (APP_PORT=$(APP_PORT) PG_PORT=$(PG_PORT) docker compose exec -T postgres psql -U ndr -d postgres -c "CREATE DATABASE ndr_test")

test-remote:
	TEST_DB_URL=$${TEST_DB_URL:-postgresql+psycopg2://ndr:ndr@localhost:$(PG_PORT)/ndr_test} \
		NDR_BASE_URL=$${NDR_BASE_URL:-http://localhost:$(APP_PORT)} \
		RUN_REMOTE_REQUESTS_TEST=true \
		.venv/bin/pytest

fmt:
	.venv/bin/python -m black .
	.venv/bin/python -m isort .

lint:
	.venv/bin/python -m ruff check .

typecheck:
	.venv/bin/python -m mypy app

check: fmt lint typecheck test
