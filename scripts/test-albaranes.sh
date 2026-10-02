#!/usr/bin/env bash

set -euo pipefail

ERP_URL="${ERP_URL:-http://127.0.0.1:9000}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

json_value() {
  local key="$1"
  "$PYTHON_BIN" -c 'import json, sys; value = json.load(sys.stdin); [value := value[part] for part in sys.argv[1].split(".")]; print(value)' "$key"
}

echo "Comprobando servicios…"
curl --silent --show-error --fail "$ERP_URL/health" >/dev/null
curl --silent --show-error --fail "$BACKEND_URL/health" >/dev/null
curl --silent --show-error --fail "$BACKEND_URL/ready" >/dev/null

echo "Restableciendo datos semilla…"
curl --silent --show-error --fail -X POST "$ERP_URL/api/v1/test/reset" \
  -H 'Content-Type: application/json' -d '{}' >/dev/null

echo "Enviando documento escaneado simulado…"
payload="$($PYTHON_BIN - <<'PY'
import base64
import json

print(json.dumps({
    "client_id": "CLI-001",
    "filename": "albaran-demo.txt",
    "content_type": "text/plain",
    "content_base64": base64.b64encode(b"ALBARAN: ALB-DEMO-001\\nSKU-001 x 2").decode(),
}))
PY
)"
intake_response="$(curl --silent --show-error --fail -X POST "$BACKEND_URL/api/intake/delivery-notes" \
  -H 'Content-Type: application/json' -d "$payload")"
if [[ "$(printf '%s' "$intake_response" | json_value status)" != "sent_to_erp" ]]; then
  echo "El documento no fue enviado al ERP." >&2
  exit 1
fi

if [[ "$(printf '%s' "$intake_response" | json_value client_copy.status)" != "prepared" ]]; then
  echo "No se preparó la copia para el cliente." >&2
  exit 1
fi

echo "Enviando documento inválido para comprobar el filtro…"
rejected_payload="$($PYTHON_BIN - <<'PY'
import base64
import json

print(json.dumps({
    "client_id": "CLI-001",
    "filename": "factura.txt",
    "content_type": "text/plain",
    "content_base64": base64.b64encode(b"FACTURA F-001").decode(),
}))
PY
)"
rejected_response="$(curl --silent --show-error --fail -X POST "$BACKEND_URL/api/intake/delivery-notes" \
  -H 'Content-Type: application/json' -d "$rejected_payload")"
if [[ "$(printf '%s' "$rejected_response" | json_value status)" != "rejected" ]]; then
  echo "El filtro no rechazó el documento inválido." >&2
  exit 1
fi

echo "OK: documento → object store local → OCR/reglas → ERP → copia cliente"
