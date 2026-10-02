#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build/aws-lambda"
PACKAGE="$ROOT_DIR/build/aws-lambda.zip"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
"$PYTHON_BIN" -m pip install --disable-pip-version-check -q -r "$ROOT_DIR/requirements-aws.txt" -t "$BUILD_DIR"
cp -R "$ROOT_DIR/backend" "$BUILD_DIR/backend"
cp -R "$ROOT_DIR/ERP" "$BUILD_DIR/ERP"
find "$BUILD_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
(
  cd "$BUILD_DIR"
  zip -qr "$PACKAGE" .
)
echo "Paquete Lambda creado en $PACKAGE"
