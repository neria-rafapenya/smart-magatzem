#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "No se encontró Python 3.11 o superior. Crea primero el entorno .venv." >&2
  exit 1
fi

ERP_PORT="${MOCK_ERP_PORT:-9000}"
BACKEND_PORT="${SMART_MAGATZEM_PORT:-8000}"
EXPO_PORT="${EXPO_PORT:-8081}"
EXPO_CLEAR_CACHE="${EXPO_CLEAR_CACHE:-0}"
SERVICE_BIND_HOST="${LOCAL_BIND_HOST:-127.0.0.1}"
ERP_URL="http://127.0.0.1:${ERP_PORT}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
EXPO_URL="http://127.0.0.1:${EXPO_PORT}"
EXPO_ERP_URL="${EXPO_PUBLIC_ERP_API_URL:-$ERP_URL}"
EXPO_BACKEND_URL="${EXPO_PUBLIC_BACKEND_API_URL:-$BACKEND_URL}"
DOCUMENT_CONNECTOR_NAME="${DOCUMENT_CONNECTOR:-mock_erp}"
AUTH_REQUIRED="${LOCAL_AUTH_REQUIRED:-0}"
AUTH_PROVIDER_NAME="${AUTH_PROVIDER:-local}"
AI_PROVIDER="${DOCUMENT_AI_PROVIDER:-local}"
START_MOCK_ERP="${START_MOCK_ERP:-1}"

if [[ "$AI_PROVIDER" != "local" && "$AI_PROVIDER" != "aws" ]]; then
  echo "DOCUMENT_AI_PROVIDER debe ser local o aws." >&2
  exit 1
fi
STARTED_PIDS=()

cleanup() {
  if ((${#STARTED_PIDS[@]} > 0)); then
    echo
    echo "Deteniendo servicios iniciados por este script…"
    for pid in "${STARTED_PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

is_healthy() {
  curl --silent --fail --max-time 1 "$1/health" >/dev/null 2>&1
}

is_current() {
  local service="$1"
  local url="$2"
  case "$service" in
    "Mock ERP")
      curl --silent --fail --max-time 1 "$url/openapi.json" >/dev/null 2>&1 && \
        curl --silent --fail --max-time 1 "$url/api/v1/suppliers" >/dev/null 2>&1 && \
        curl --silent --show-error --max-time 1 -D - -o /dev/null -X OPTIONS "$url/api/v1/delivery-notes" \
          -H 'Origin: http://localhost:8081' \
          -H 'Access-Control-Request-Method: GET' | grep -qi 'Access-Control-Allow-Origin'
      ;;
    "Backend")
      curl --silent --fail --max-time 1 "$url/ready" >/dev/null 2>&1 && \
        curl --silent --fail --max-time 1 "$url/health" | grep -q "\"ai_provider\"[[:space:]]*:[[:space:]]*\"${AI_PROVIDER}\"" && \
        curl --silent --fail --max-time 1 "$url/health" | grep -q '"image_quality_analysis"[[:space:]]*:[[:space:]]*true' && \
        curl --silent --fail --max-time 1 "$url/health" | grep -q '"quality_rules_version"[[:space:]]*:[[:space:]]*"local-v2"' && \
        curl --silent --fail --max-time 1 "$url/health" | grep -q '"thread_safe_local_auth"[[:space:]]*:[[:space:]]*true' && \
        [[ "$(curl --silent --max-time 1 -o /dev/null -w '%{http_code}' -X POST "$url/api/intake/delivery-notes/analyze" \
          -H 'Content-Type: application/json' -d '{}')" == "400" ]] && \
        [[ "$(curl --silent --max-time 1 -o /dev/null -w '%{http_code}' -X POST "$url/api/intake/documents/analyze" \
          -H 'Content-Type: application/json' -d '{}')" == "400" ]]
      ;;
    *) return 1 ;;
  esac
}

wait_for_health() {
  local url="$1"
  local service="$2"
  for _ in {1..30}; do
    if is_healthy "$url"; then
      echo "$service listo en $url"
      return 0
    fi
    sleep 1
  done
  echo "${service} no respondió en 30 segundos." >&2
  return 1
}

start_if_needed() {
  local service="$1"
  local url="$2"
  local module="$3"

  if is_healthy "$url" && is_current "$service" "$url"; then
    echo "$service ya estaba funcionando en $url"
    return 0
  fi

  if is_healthy "$url"; then
    echo "$service está activo, pero usa una versión anterior del código." >&2
    echo "Detén ese proceso y vuelve a ejecutar este script para cargar la versión actual." >&2
    return 1
  fi

  echo "Iniciando ${service}…"
  (
    cd "$ROOT_DIR"
    PYTHONPATH="$ROOT_DIR" PYTHONDONTWRITEBYTECODE=1 \
      AUTH_PROVIDER="$AUTH_PROVIDER_NAME" \
      MOCK_ERP_HOST="$SERVICE_BIND_HOST" MOCK_ERP_PORT="$ERP_PORT" \
      SMART_MAGATZEM_HOST="$SERVICE_BIND_HOST" SMART_MAGATZEM_PORT="$BACKEND_PORT" \
      exec "$PYTHON_BIN" -m "$module"
  ) &
  STARTED_PIDS+=("$!")
  wait_for_health "$url" "$service"
}

start_frontend() {
  if lsof -nP -iTCP:"$EXPO_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Frontend Expo ya parece estar funcionando en el puerto $EXPO_PORT"
    return 0
  fi

  echo "Iniciando frontend Expo en modo LAN…"
  expo_args=(--lan --port "$EXPO_PORT")
  if [[ "$EXPO_CLEAR_CACHE" == "1" ]]; then
    expo_args+=(--clear)
    echo "Limpiando la caché de Expo…"
  fi
  (
    cd "$ROOT_DIR/frontend"
    EXPO_PUBLIC_ERP_API_URL="$EXPO_ERP_URL" \
      EXPO_PUBLIC_BACKEND_API_URL="$EXPO_BACKEND_URL" \
      EXPO_PUBLIC_AUTH_PROVIDER="$AUTH_PROVIDER_NAME" \
      exec npx expo start "${expo_args[@]}"
  ) &
  STARTED_PIDS+=("$!")
  echo "Frontend Expo iniciado; usa el QR o abre Expo web desde la terminal."
}

echo "Smart Magatzem — entorno local"
echo "ERP mock: $ERP_URL"
echo "Backend:   $BACKEND_URL"
echo "Expo:      $EXPO_URL"
echo "Expo ERP:  $EXPO_ERP_URL"
echo "Expo API:  $EXPO_BACKEND_URL"
echo "Conector:  $DOCUMENT_CONNECTOR_NAME"
echo "Auth local: $AUTH_REQUIRED"
echo "Proveedor auth: $AUTH_PROVIDER_NAME"
echo "Procesado IA: $AI_PROVIDER"
echo

if [[ "$START_MOCK_ERP" == "1" ]]; then
  start_if_needed "Mock ERP" "$ERP_URL" "ERP.mock_erp"
else
  echo "Mock ERP: no se inicia (START_MOCK_ERP=$START_MOCK_ERP)"
fi
start_if_needed "Backend" "$BACKEND_URL" "backend"
start_frontend

echo
echo "Servicios locales activos. Pulsa Ctrl+C para detener los que inició este script."
if ((${#STARTED_PIDS[@]} == 0)); then
  echo "Todos los servicios ya estaban activos; no hay procesos que supervisar."
  exit 0
fi

while true; do
  for pid in "${STARTED_PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "Uno de los servicios locales terminó; cerrando el entorno." >&2
      exit 1
    fi
  done
  sleep 2
done
