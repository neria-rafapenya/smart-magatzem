"""Configuración local por tenant para la conexión con el ERP.

En AWS, los secretos de este almacén se sustituirán por AWS Secrets Manager.
Este fichero solo existe para poder revisar el flujo completo en localhost.
"""

from __future__ import annotations

import json
import os
import base64
import binascii
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock


class TenantConfigError(Exception):
    pass


class LocalTenantConfigStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("LOCAL_TENANT_CONFIG", "data/local-secrets/tenant-config.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.template_root = Path(os.getenv("LOCAL_TENANT_TEMPLATES", "data/local-tenant-templates"))
        self.template_root.mkdir(parents=True, exist_ok=True)
        self._ensure_defaults("TEN-001")

    DEFAULT_FIELDS: list[dict[str, object]] = [
        {"key": "document_number", "label": "Número de documento", "type": "text", "required": True, "source": "header"},
        {"key": "document_date", "label": "Fecha", "type": "date", "required": True, "source": "header"},
        {"key": "expected_delivery_date", "label": "Entrega prevista", "type": "date", "required": False, "source": "header"},
        {"key": "document_direction", "label": "Dirección", "type": "enum", "required": True, "values": ["inbound", "outbound"], "source": "header"},
        {"key": "counterparty_name", "label": "Cliente / proveedor", "type": "text", "required": True, "source": "counterparty"},
        {"key": "counterparty_tax_id", "label": "ID / CIF", "type": "text", "required": False, "source": "counterparty"},
        {"key": "counterparty_email", "label": "Email", "type": "email", "required": False, "source": "counterparty"},
        {"key": "counterparty_address", "label": "Dirección del cliente/proveedor", "type": "text", "required": False, "source": "counterparty"},
        {"key": "lines.sku", "label": "SKU", "type": "text", "required": True, "repeatable": True, "source": "line"},
        {"key": "lines.description", "label": "Descripción", "type": "text", "required": False, "repeatable": True, "source": "line"},
        {"key": "lines.quantity", "label": "Cantidad", "type": "number", "required": True, "repeatable": True, "source": "line"},
        {"key": "lines.unit", "label": "Unidad", "type": "text", "required": False, "repeatable": True, "source": "line"},
        {"key": "lines.observations", "label": "Observaciones de línea", "type": "text", "required": False, "repeatable": True, "source": "line"},
        {"key": "notes", "label": "Observaciones y condiciones", "type": "text", "required": False, "source": "footer"},
        {"key": "signatures.counterparty", "label": "Firma cliente / proveedor", "type": "signature", "required": False, "source": "footer"},
        {"key": "signatures.company", "label": "Firma Smart Magatzem", "type": "signature", "required": False, "source": "footer"},
    ]

    DEFAULT_VALIDATION_RULES: dict[str, object] = {
        "delivery_note_against_order": {
            "enabled": True,
            "quantity_tolerance_percent": 0.0,
            "price_tolerance_percent": 0.0,
            "on_mismatch": "human_review",
        },
        "invoice_against_delivery_note": {
            "enabled": True,
            "quantity_tolerance_percent": 0.0,
            "price_tolerance_percent": 0.0,
            "on_mismatch": "human_review",
        },
        "duplicate_policy": "block",
        "enable_batch_documents": False,
        "max_pages_per_document": 20,
        "deca_native_required": True,
    }

    DEFAULT_CAPTURE_SETTINGS: dict[str, object] = {
        "guided_capture": True,
        "quality_gate": True,
        "torch_default": False,
        "enable_multipage": False,
        "enable_burst": False,
        "max_pages_per_document": 20,
        "max_file_size_mb": 2,
        "remember_last_selection": True,
        "offline_queue": True,
        "confidence_threshold": 0.85,
    }

    def _read(self) -> dict[str, object]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write(self, value: dict[str, object]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _ensure_defaults(self, tenant_id: str) -> None:
        with self.lock:
            data = self._read()
            entry = data.get(tenant_id)
            if not isinstance(entry, dict):
                entry = {}
            changed = False
            if "fields" not in entry:
                entry["fields"] = self.DEFAULT_FIELDS
                changed = True
            if "validation_rules" not in entry:
                entry["validation_rules"] = self.DEFAULT_VALIDATION_RULES
                changed = True
            if "capture_settings" not in entry:
                entry["capture_settings"] = self.DEFAULT_CAPTURE_SETTINGS
                changed = True
            if "erp_connection" not in entry:
                legacy_connection = {
                    key: entry.pop(key)
                    for key in ("provider", "base_url", "auth_type", "username", "secret", "status", "last_checked_at", "updated_at")
                    if key in entry
                }
                entry["erp_connection"] = legacy_connection or {
                    "provider": "mock_erp",
                    "base_url": "http://127.0.0.1:9000",
                    "auth_type": "none",
                    "username": "",
                    "secret": "",
                    "status": "configured",
                    "last_checked_at": None,
                }
                changed = True
            templates = entry.get("templates")
            if not isinstance(templates, list):
                templates = []
            template_path = self.template_root / tenant_id / "08-plantilla-pedido-en-blanco.pdf"
            if template_path.exists() and not any(
                isinstance(item, dict) and item.get("path") == str(template_path)
                for item in templates
            ):
                templates.append({
                    "id": "TPL-TEN-001-PEDIDO",
                    "document_type": "order",
                    "scope": "general",
                    "filename": template_path.name,
                    "path": str(template_path),
                    "uploaded_at": datetime.now(UTC).isoformat(),
                })
                changed = True
            if "templates" not in entry or entry.get("templates") != templates:
                entry["templates"] = templates
                changed = True
            data[tenant_id] = entry
            if changed:
                self._write(data)

    def get_erp_connection(self, tenant_id: str) -> dict[str, object]:
        with self.lock:
            entry = self._read().get(tenant_id)
            if not isinstance(entry, dict):
                return {
                    "tenant_id": tenant_id,
                    "provider": "mock_erp",
                    "base_url": "http://127.0.0.1:9000",
                    "auth_type": "none",
                    "username": "",
                    "secret_configured": False,
                    "status": "configured",
                    "last_checked_at": None,
                }
            return self._public_connection(tenant_id, self._connection_entry(entry))

    @staticmethod
    def _connection_entry(entry: dict[str, object]) -> dict[str, object]:
        nested = entry.get("erp_connection")
        return nested if isinstance(nested, dict) else entry

    def save_erp_connection(self, tenant_id: str, payload: dict[str, object]) -> dict[str, object]:
        provider = str(payload.get("provider", "generic_rest")).strip().lower() or "generic_rest"
        auth_type = str(payload.get("auth_type", "api_key")).strip().lower() or "api_key"
        base_url = str(payload.get("base_url", "")).strip().rstrip("/")
        username = str(payload.get("username", "")).strip()
        secret = str(payload.get("secret", ""))
        if not base_url:
            raise TenantConfigError("El endpoint del ERP es obligatorio.")
        if provider not in {"mock_erp", "generic_rest"}:
            raise TenantConfigError("Proveedor ERP no soportado en la demo local.")
        if auth_type not in {"none", "api_key", "bearer", "basic", "oauth2_client_credentials"}:
            raise TenantConfigError("Tipo de autenticación no soportado.")

        with self.lock:
            data = self._read()
            previous = data.get(tenant_id)
            previous = previous if isinstance(previous, dict) else {}
            entry: dict[str, object] = {
                "provider": provider,
                "base_url": base_url,
                "auth_type": auth_type,
                "username": username,
                "secret": secret or previous.get("secret", ""),
                "status": "saved",
                "last_checked_at": previous.get("last_checked_at"),
                "updated_at": datetime.now(UTC).isoformat(),
            }
            previous["erp_connection"] = entry
            data[tenant_id] = previous
            self._write(data)
            return self._public_connection(tenant_id, entry)

    def mark_check(self, tenant_id: str, status: str) -> dict[str, object]:
        with self.lock:
            data = self._read()
            entry = data.get(tenant_id)
            if not isinstance(entry, dict):
                raise TenantConfigError("Primero guarda la conexión del ERP.")
            connection = self._connection_entry(entry)
            connection["status"] = status
            connection["last_checked_at"] = datetime.now(UTC).isoformat()
            entry["erp_connection"] = connection
            data[tenant_id] = entry
            self._write(data)
            return self._public_connection(tenant_id, connection)

    def get_fields(self, tenant_id: str) -> list[dict[str, object]]:
        with self.lock:
            entry = self._read().get(tenant_id, {})
            fields = entry.get("fields") if isinstance(entry, dict) else None
            return [dict(item) for item in fields if isinstance(item, dict)] if isinstance(fields, list) else list(self.DEFAULT_FIELDS)

    def save_fields(self, tenant_id: str, fields: object) -> list[dict[str, object]]:
        if not isinstance(fields, list) or not all(isinstance(item, dict) for item in fields):
            raise TenantConfigError("fields debe ser una lista de campos")
        cleaned: list[dict[str, object]] = []
        for item in fields:
            key = str(item.get("key", "")).strip()
            label = str(item.get("label", "")).strip()
            if not key or not label or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", key):
                raise TenantConfigError("Cada campo necesita una clave y un nombre válidos")
            cleaned.append({**item, "key": key, "label": label, "required": bool(item.get("required", False))})
        with self.lock:
            data = self._read()
            entry = data.setdefault(tenant_id, {})
            if not isinstance(entry, dict):
                entry = {}
                data[tenant_id] = entry
            entry["fields"] = cleaned
            self._write(data)
        return cleaned

    def get_validation_rules(self, tenant_id: str) -> dict[str, object]:
        with self.lock:
            entry = self._read().get(tenant_id, {})
            configured = entry.get("validation_rules") if isinstance(entry, dict) else None
            if not isinstance(configured, dict):
                return json.loads(json.dumps(self.DEFAULT_VALIDATION_RULES))
            merged = json.loads(json.dumps(self.DEFAULT_VALIDATION_RULES))
            for key, value in configured.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
            return merged

    def get_capture_settings(self, tenant_id: str) -> dict[str, object]:
        with self.lock:
            entry = self._read().get(tenant_id, {})
            configured = entry.get("capture_settings") if isinstance(entry, dict) else None
            merged = json.loads(json.dumps(self.DEFAULT_CAPTURE_SETTINGS))
            if isinstance(configured, dict):
                merged.update(configured)
            return merged

    def save_capture_settings(self, tenant_id: str, settings: object) -> dict[str, object]:
        if not isinstance(settings, dict):
            raise TenantConfigError("capture_settings debe ser un objeto")
        merged = self.get_capture_settings(tenant_id)
        boolean_keys = {
            "guided_capture", "quality_gate", "torch_default", "enable_multipage",
            "enable_burst", "remember_last_selection", "offline_queue",
        }
        for key in boolean_keys:
            if key in settings:
                merged[key] = bool(settings[key])
        for key, minimum, maximum in (
            ("max_pages_per_document", 1, 100),
            ("max_file_size_mb", 1, 20),
        ):
            if key in settings:
                try:
                    value = int(settings[key])
                except (TypeError, ValueError) as error:
                    raise TenantConfigError(f"{key} debe ser entero") from error
                if value < minimum or value > maximum:
                    raise TenantConfigError(f"{key} debe estar entre {minimum} y {maximum}")
                merged[key] = value
        if "confidence_threshold" in settings:
            try:
                threshold = float(settings["confidence_threshold"])
            except (TypeError, ValueError) as error:
                raise TenantConfigError("confidence_threshold debe ser numérico") from error
            if threshold < 0 or threshold > 1:
                raise TenantConfigError("confidence_threshold debe estar entre 0 y 1")
            merged["confidence_threshold"] = threshold
        with self.lock:
            data = self._read()
            entry = data.setdefault(tenant_id, {})
            if not isinstance(entry, dict):
                entry = {}
                data[tenant_id] = entry
            entry["capture_settings"] = merged
            self._write(data)
        return merged

    def save_validation_rules(self, tenant_id: str, rules: object) -> dict[str, object]:
        if not isinstance(rules, dict):
            raise TenantConfigError("validation_rules debe ser un objeto")
        merged = self.get_validation_rules(tenant_id)
        for key in ("delivery_note_against_order", "invoice_against_delivery_note"):
            section = rules.get(key)
            if section is None:
                continue
            if not isinstance(section, dict):
                raise TenantConfigError(f"{key} debe ser un objeto")
            current = merged[key]
            assert isinstance(current, dict)
            for field in ("enabled", "quantity_tolerance_percent", "price_tolerance_percent", "on_mismatch"):
                if field not in section:
                    continue
                value = section[field]
                if field == "enabled":
                    current[field] = bool(value)
                elif field.endswith("percent"):
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError) as error:
                        raise TenantConfigError(f"{key}.{field} debe ser numérico") from error
                    if numeric < 0 or numeric > 100:
                        raise TenantConfigError(f"{key}.{field} debe estar entre 0 y 100")
                    current[field] = numeric
                elif field == "on_mismatch":
                    if str(value) not in {"human_review", "block", "warning"}:
                        raise TenantConfigError(f"{key}.on_mismatch no es válido")
                    current[field] = str(value)
        if "duplicate_policy" in rules:
            policy = str(rules["duplicate_policy"])
            if policy not in {"block", "warning", "allow"}:
                raise TenantConfigError("duplicate_policy no es válido")
            merged["duplicate_policy"] = policy
        if "enable_batch_documents" in rules:
            merged["enable_batch_documents"] = bool(rules["enable_batch_documents"])
        if "max_pages_per_document" in rules:
            try:
                max_pages = int(rules["max_pages_per_document"])
            except (TypeError, ValueError) as error:
                raise TenantConfigError("max_pages_per_document debe ser entero") from error
            if max_pages < 1 or max_pages > 100:
                raise TenantConfigError("max_pages_per_document debe estar entre 1 y 100")
            merged["max_pages_per_document"] = max_pages
        if "deca_native_required" in rules:
            merged["deca_native_required"] = bool(rules["deca_native_required"])
        with self.lock:
            data = self._read()
            entry = data.setdefault(tenant_id, {})
            if not isinstance(entry, dict):
                entry = {}
                data[tenant_id] = entry
            entry["validation_rules"] = merged
            self._write(data)
        return merged

    def list_templates(self, tenant_id: str) -> list[dict[str, object]]:
        with self.lock:
            entry = self._read().get(tenant_id, {})
            templates = entry.get("templates") if isinstance(entry, dict) else None
            return [dict(item) for item in templates if isinstance(item, dict)] if isinstance(templates, list) else []

    def save_template(self, tenant_id: str, filename: str, content_base64: str, document_type: str = "order") -> dict[str, object]:
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "template.pdf"
        try:
            content = base64.b64decode(content_base64.split(",", 1)[-1], validate=True)
        except (binascii.Error, ValueError) as error:
            raise TenantConfigError("El contenido de la plantilla no es válido") from error
        if len(content) > 10 * 1024 * 1024:
            raise TenantConfigError("La plantilla supera el límite de 10 MB")
        target_dir = self.template_root / tenant_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_name
        target.write_bytes(content)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        template = {
            "id": f"TPL-{tenant_id}-{uuid.uuid4().hex[:8].upper()}",
            "document_type": document_type,
            "scope": "general",
            "filename": safe_name,
            "path": str(target),
            "uploaded_at": datetime.now(UTC).isoformat(),
        }
        with self.lock:
            data = self._read()
            entry = data.setdefault(tenant_id, {})
            if not isinstance(entry, dict):
                entry = {}
                data[tenant_id] = entry
            templates = entry.setdefault("templates", [])
            if not isinstance(templates, list):
                templates = []
                entry["templates"] = templates
            templates.append(template)
            self._write(data)
        return template

    @staticmethod
    def _public_connection(tenant_id: str, entry: dict[str, object]) -> dict[str, object]:
        secret = str(entry.get("secret", ""))
        return {
            "tenant_id": tenant_id,
            "provider": str(entry.get("provider", "generic_rest")),
            "base_url": str(entry.get("base_url", "")),
            "auth_type": str(entry.get("auth_type", "api_key")),
            "username": str(entry.get("username", "")),
            "secret_configured": bool(secret),
            "status": str(entry.get("status", "not_configured")),
            "last_checked_at": entry.get("last_checked_at"),
            "updated_at": entry.get("updated_at"),
        }
