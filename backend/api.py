"""API HTTP local del ERP, sin dependencias externas."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .auth import LocalAuthError, LocalAuthProvider, has_permission
from .connectors import build_document_connector
from .erp_client import ERPClient, ERPClientError, ERPUnavailableError
from .intake import DeliveryNoteIntake, IntakeError
from .tenant_config import LocalTenantConfigStore, TenantConfigError
from .usage import build_usage_snapshot


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    erp_url: str | None = None,
):
    erp = ERPClient(erp_url or os.getenv("ERP_BASE_URL", "http://127.0.0.1:9000"))
    connector = build_document_connector(
        erp,
        os.getenv("DOCUMENT_CONNECTOR", "mock_erp"),
        os.getenv("LOCAL_FILE_CONNECTOR_DIR", "data/connectors/files"),
    )
    ai_provider = os.getenv("DOCUMENT_AI_PROVIDER", "local").strip().lower() or "local"
    if ai_provider not in {"local", "aws"}:
        raise ValueError("DOCUMENT_AI_PROVIDER debe ser local o aws")
    if ai_provider == "aws":
        raise RuntimeError(
            "DOCUMENT_AI_PROVIDER=aws está reservado para el adaptador Bedrock/Textract; "
            "todavía no se conecta a AWS en la fase local"
        )
    tenant_config = LocalTenantConfigStore()
    intake = DeliveryNoteIntake(
        erp,
        connector=connector,
        validation_rules_provider=tenant_config.get_validation_rules,
    )
    auth = LocalAuthProvider(os.getenv("LOCAL_DEV_PASSWORD", "demo1234"))
    auth_required = os.getenv("LOCAL_AUTH_REQUIRED", "0").lower() in {"1", "true", "yes"}

    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "smart-magatzem-backend",
                        "ai_provider": ai_provider,
                        "quality_rules_version": "local-v2",
                        "features": {
                            "intake_analysis": True,
                            "pdf_text_extraction": True,
                            "document_type_detection": True,
                            "order_intake": True,
                            "packing_list_intake": True,
                            "transport_document_intake": True,
                            "invoice_intake": True,
                            "customer_match_validation": True,
                            "image_quality_analysis": True,
                            "provider_contracts": True,
                            "aws_usage_estimation": True,
                            "local_auth": True,
                            "thread_safe_local_auth": True,
                            "file_connector": True,
                            "duplicate_detection": True,
                            "cross_document_validation": True,
                            "native_xml_pdf_reading": True,
                            "multipage_contract": True,
                        },
                        "document_connector": connector.name,
                        "auth_provider": auth.name,
                    },
                )
                return
            if parsed.path == "/ready":
                try:
                    connector_health = connector.health()
                    self._send(HTTPStatus.OK, {"status": "ready", "connector": connector.name, "connector_health": connector_health})
                except ERPUnavailableError as error:
                    self._send(error.status_code, {"status": "not_ready", "error": str(error)})
                return
            try:
                if parsed.path == "/api/auth/me":
                    identity = self._identity(required=True)
                    self._send(HTTPStatus.OK, {"user": identity})
                    return
                if parsed.path == "/api/tenants":
                    identity = self._identity(required=True)
                    self._send(HTTPStatus.OK, {"data": auth.list_tenants(identity["user_id"])})
                    return
                if parsed.path == "/api/admin/erp-connection":
                    identity = self._require_permission("tenant.configure")
                    self._send(HTTPStatus.OK, tenant_config.get_erp_connection(identity["tenant_id"]))
                    return
                if parsed.path == "/api/admin/document-config":
                    identity = self._require_permission("tenant.configure")
                    self._send(
                        HTTPStatus.OK,
                        {
                            "tenant_id": identity["tenant_id"],
                            "fields": tenant_config.get_fields(identity["tenant_id"]),
                            "templates": tenant_config.list_templates(identity["tenant_id"]),
                            "validation_rules": tenant_config.get_validation_rules(identity["tenant_id"]),
                            "capture_settings": tenant_config.get_capture_settings(identity["tenant_id"]),
                        },
                    )
                    return
                if parsed.path == "/api/tenant/capture-settings":
                    identity = self._require_permission("document.read")
                    self._send(HTTPStatus.OK, {
                        "tenant_id": identity["tenant_id"],
                        "capture_settings": tenant_config.get_capture_settings(identity["tenant_id"]),
                    })
                    return
                if parsed.path == "/api/connectors":
                    self._send(HTTPStatus.OK, {"active": connector.name, "data": [connector.health(), {"provider": "file", "status": "available"}]})
                    return
                if parsed.path == "/api/usage/aws":
                    identity = self._require_permission("document.read")
                    self._send(HTTPStatus.OK, build_usage_snapshot(intake.list_records(identity["tenant_id"]), ai_provider))
                    return
                if parsed.path in {"/api/intake/delivery-notes", "/api/intake/documents"}:
                    identity = self._require_permission("document.read")
                    self._send(HTTPStatus.OK, {"data": intake.list_records(identity["tenant_id"])})
                    return
                intake_prefix = next(
                    (prefix for prefix in ("/api/intake/delivery-notes/", "/api/intake/documents/") if parsed.path.startswith(prefix)),
                    None,
                )
                if intake_prefix and parsed.path.endswith("/document"):
                    identity = self._require_permission("document.read")
                    record_id = unquote(parsed.path.removeprefix(intake_prefix).removesuffix("/document")).strip("/")
                    source_document = intake.get_source_document(record_id, identity["tenant_id"])
                    if source_document is None:
                        self._send(HTTPStatus.NOT_FOUND, {"error": "evidencia no encontrada"})
                        return
                    content, content_type, filename = source_document
                    self._send_file(HTTPStatus.OK, content, content_type, filename)
                    return
                if intake_prefix:
                    identity = self._require_permission("document.read")
                    record_id = unquote(parsed.path.removeprefix(intake_prefix)).strip("/")
                    record = intake.get_record(record_id, identity["tenant_id"])
                    self._send(HTTPStatus.OK if record else HTTPStatus.NOT_FOUND, record or {"error": "documento no encontrado"})
                    return
                if parsed.path == "/api/customers":
                    self._send(HTTPStatus.OK, erp.list_customers(parse_qs(parsed.query).get("q", [""])[0]))
                    return
                if parsed.path == "/api/suppliers":
                    self._send(HTTPStatus.OK, erp.list_suppliers(parse_qs(parsed.query).get("q", [""])[0]))
                    return
                if parsed.path == "/api/delivery-notes":
                    self._send(HTTPStatus.OK, erp.list_delivery_notes(parse_qs(parsed.query).get("status", [""])[0]))
                    return
                if parsed.path.startswith("/api/delivery-notes/"):
                    note_id = unquote(parsed.path.removeprefix("/api/delivery-notes/"))
                    self._send(HTTPStatus.OK, erp.get_delivery_note(note_id))
                    return
            except ERPClientError as error:
                self._send(error.status_code, {"error": str(error)})
                return
            except LocalAuthError as error:
                self._send(HTTPStatus.UNAUTHORIZED, {"error": str(error)})
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "ruta no encontrada"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
                if parsed.path == "/api/auth/login":
                    result = auth.login(
                        str(payload.get("email", "")),
                        str(payload.get("password", "")),
                        str(payload.get("tenant_id", "")).strip() or None,
                    )
                    self._send(HTTPStatus.OK, result)
                    return
                if parsed.path == "/api/tenants":
                    identity = self._require_permission("tenant.configure")
                    tenant = auth.store.create_tenant(
                        identity["user_id"],
                        str(payload.get("id", "")),
                        str(payload.get("name", "")),
                    )
                    self._send(HTTPStatus.CREATED, tenant)
                    return
                if parsed.path == "/api/admin/erp-connection":
                    identity = self._require_permission("tenant.configure")
                    saved = tenant_config.save_erp_connection(identity["tenant_id"], payload)
                    self._send(HTTPStatus.OK, saved)
                    return
                if parsed.path == "/api/admin/erp-connection/test":
                    identity = self._require_permission("tenant.configure")
                    connection = tenant_config.get_erp_connection(identity["tenant_id"])
                    try:
                        result = ERPClient(str(connection["base_url"])).health()
                        saved = tenant_config.mark_check(identity["tenant_id"], "connected")
                        self._send(HTTPStatus.OK, {"status": "connected", "connection": saved, "response": result})
                    except ERPClientError as error:
                        tenant_config.mark_check(identity["tenant_id"], "error")
                        self._send(error.status_code, {"status": "error", "error": str(error)})
                    return
                if parsed.path == "/api/admin/document-config/fields":
                    identity = self._require_permission("tenant.configure")
                    fields = tenant_config.save_fields(identity["tenant_id"], payload.get("fields"))
                    self._send(HTTPStatus.OK, {"fields": fields})
                    return
                if parsed.path == "/api/admin/document-config/validation-rules":
                    identity = self._require_permission("tenant.configure")
                    rules = tenant_config.save_validation_rules(identity["tenant_id"], payload.get("validation_rules", payload))
                    self._send(HTTPStatus.OK, {"validation_rules": rules})
                    return
                if parsed.path == "/api/admin/document-config/capture-settings":
                    identity = self._require_permission("tenant.configure")
                    settings = tenant_config.save_capture_settings(identity["tenant_id"], payload.get("capture_settings", payload))
                    self._send(HTTPStatus.OK, {"capture_settings": settings})
                    return
                if parsed.path == "/api/admin/document-config/templates":
                    identity = self._require_permission("tenant.configure")
                    template = tenant_config.save_template(
                        identity["tenant_id"],
                        str(payload.get("filename", "template.pdf")),
                        str(payload.get("content_base64", "")),
                        str(payload.get("document_type", "order")),
                    )
                    self._send(HTTPStatus.CREATED, template)
                    return
                if parsed.path in {"/api/intake/delivery-notes/analyze", "/api/intake/documents/analyze"}:
                    identity = self._require_permission("document.capture")
                    payload["tenant_id"] = identity["tenant_id"]
                    self._send(HTTPStatus.OK, intake.analyze(payload))
                    return
                if parsed.path in {"/api/intake/delivery-notes", "/api/intake/documents"}:
                    identity = self._require_permission("document.send")
                    payload["tenant_id"] = identity["tenant_id"]
                    self._send(HTTPStatus.ACCEPTED, intake.process(payload))
                    return
                if parsed.path == "/api/delivery-notes":
                    self._send(HTTPStatus.CREATED, erp.create_delivery_note(payload))
                    return
                if parsed.path.startswith("/api/delivery-notes/"):
                    suffix = parsed.path.removeprefix("/api/delivery-notes/")
                    note_id, separator, action = suffix.rpartition("/")
                    if separator and action in {"confirm", "deliver", "cancel"}:
                        self._send(HTTPStatus.OK, erp.transition_delivery_note(unquote(note_id), action))
                        return
                if parsed.path.startswith("/api/orders/") and parsed.path.endswith("/delivery-note"):
                    order_id = unquote(parsed.path.removeprefix("/api/orders/").removesuffix("/delivery-note")).strip("/")
                    self._send(HTTPStatus.CREATED, erp.create_delivery_note_from_order(order_id, payload))
                    return
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            except KeyError as error:
                self._send(HTTPStatus.NOT_FOUND, {"error": str(error).strip("'")})
                return
            except ERPClientError as error:
                self._send(error.status_code, {"error": str(error)})
                return
            except IntakeError as error:
                self._send(error.status_code, {"error": str(error)})
                return
            except TenantConfigError as error:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            except LocalAuthError as error:
                self._send(HTTPStatus.UNAUTHORIZED, {"error": str(error)})
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "ruta no encontrada"})

        def log_message(self, *_args) -> None:
            return

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("el cuerpo debe ser un objeto JSON")
            return value

        def _send(self, status: HTTPStatus, body: dict[str, object]) -> None:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_file(self, status: HTTPStatus, content: bytes, content_type: str, filename: str) -> None:
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _identity(self, required: bool = False):
            authorization = self.headers.get("Authorization", "")
            token = authorization.removeprefix("Bearer ").strip() if authorization else ""
            identity = auth.authenticate(token) if token else None
            if required and identity is None:
                raise LocalAuthError("se requiere autenticación")
            requested_tenant = self.headers.get("X-Tenant-Id", "").strip()
            if identity and requested_tenant and requested_tenant != identity["tenant_id"]:
                switched = auth.store.identity_for_user(identity["user_id"], requested_tenant)
                if switched is None:
                    raise LocalAuthError("el usuario no pertenece a ese tenant")
                identity = switched
            return identity

        def _require_permission(self, permission: str):
            # La configuración de tenant nunca se expone sin identidad, incluso
            # cuando el modo local mantiene relajados los permisos documentales.
            enforce = auth_required or permission == "tenant.configure"
            identity = self._identity(required=enforce)
            if not enforce:
                return identity or {
                    "user_id": "local-dev",
                    "tenant_id": os.getenv("DEFAULT_TENANT_ID", "TEN-LOCAL"),
                    "permissions": ["*"],
                }
            if not has_permission(identity, permission):
                raise LocalAuthError(f"permiso insuficiente: {permission}")
            return identity

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Tenant-Id")

    server = ThreadingHTTPServer((host, port), Handler)
    return server
