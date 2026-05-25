#!/usr/bin/env bash
set -e

# ── Цвета ─────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[DataBridge]${NC} $1"; }
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WAIT]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; }

# ── Ждём пока сервис станет healthy ───────────────────
wait_healthy() {
  local name=$1
  local max=${2:-60}
  local i=0
  warn "Ожидаем $name..."
  until [ "$(docker inspect -f '{{.State.Health.Status}}' $name 2>/dev/null)" = "healthy" ]; do
    sleep 2
    i=$((i+2))
    if [ $i -ge $max ]; then
      err "$name не стал healthy за ${max}с"
      exit 1
    fi
  done
  ok "$name готов"
}

# ── Ждём завершения контейнера (для init-задач) ────────
wait_exit() {
  local name=$1
  local max=${2:-120}
  local i=0
  warn "Ожидаем завершения $name..."
  until [ "$(docker inspect -f '{{.State.Status}}' $name 2>/dev/null)" = "exited" ]; do
    sleep 2
    i=$((i+2))
    if [ $i -ge $max ]; then
      err "$name не завершился за ${max}с"
      exit 1
    fi
  done
  local code
  code=$(docker inspect -f '{{.State.ExitCode}}' $name)
  if [ "$code" != "0" ]; then
    err "$name завершился с кодом $code"
    docker logs $name --tail 20
    exit 1
  fi
  ok "$name завершился успешно"
}

# ══════════════════════════════════════════════════════
log "Запускаем DataBridge..."
echo ""

log "Шаг 1 — Базы данных (PostgreSQL + MySQL)"
docker-compose up -d postgres mysql

wait_healthy diploma_postgres 90
wait_healthy diploma_mysql    90

log "Шаг 2 — Airflow"
docker-compose up -d airflow-init
wait_exit diploma_airflow_init 120

log "Шаг 3 — superset etc"
docker-compose up -d
ok "Запуск успешен"

# ── Итог ──────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  DataBridge успешно запущен!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  DataBridge UI   →  ${CYAN}http://localhost:8000${NC}"
echo -e "  React frontend  →  ${CYAN}http://localhost:3000${NC}"
echo -e "  Superset        →  ${CYAN}http://localhost:8088${NC}  (admin / admin)"
echo -e "  Airflow         →  ${CYAN}http://localhost:8089${NC}  (admin / admin)"
echo -e "  Trino           →  ${CYAN}http://localhost:8080${NC}"
echo -e "  PostgreSQL      →  ${CYAN}localhost:5432${NC}         (pguser / pgpassword)"
echo -e "  MySQL           →  ${CYAN}localhost:3306${NC}         (mysqluser / mysqlpassword)"
echo ""
echo -e "  Остановить:  ${YELLOW}docker-compose down${NC}"
echo -e "  Логи:        ${YELLOW}docker-compose logs -f [сервис]${NC}"
echo ""
