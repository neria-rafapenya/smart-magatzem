"""Runtime AWS mínimo para API Gateway + Cognito + S3/DynamoDB.

API Gateway verifica el JWT de Cognito antes de invocar esta función. El handler
usa los claims ya validados para aplicar tenant y rol; la app móvil no recibe
credenciales AWS ni accede directamente a DynamoDB o S3.
"""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import os
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from xml.etree import ElementTree

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from .pricing import annotate_event, pricing_config, sum_token_cost


MAX_PERSISTED_IMAGE_BYTES = 2 * 1024 * 1024

AWS_DEFAULT_FIELDS: list[dict[str, object]] = [
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


def _response(status: int, body: dict[str, object]) -> dict[str, object]:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
            "access-control-allow-origin": "*",
            "access-control-allow-methods": "GET,POST,PUT,OPTIONS",
            "access-control-allow-headers": "Authorization,Content-Type,Accept,X-Tenant-Id",
        },
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def _redirect(location: str) -> dict[str, object]:
    return {"statusCode": 302, "headers": {"location": location, "cache-control": "no-store"}, "body": ""}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _claims(event: dict[str, object]) -> dict[str, object]:
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") if isinstance(request_context, dict) else {}
    jwt = authorizer.get("jwt") if isinstance(authorizer, dict) else {}
    claims = jwt.get("claims") if isinstance(jwt, dict) else {}
    return claims if isinstance(claims, dict) else {}


def _identity(event: dict[str, object]) -> dict[str, object]:
    claims = _claims(event)
    groups_value = claims.get("cognito:groups", "")
    groups = groups_value if isinstance(groups_value, list) else str(groups_value).split(",")
    groups = [str(group) for group in groups if group]
    user_id = str(claims.get("sub", ""))
    tenant_id = str(claims.get("custom:tenant_id", ""))
    mapped_role = ""
    if not tenant_id and user_id and os.getenv("CORE_TABLE"):
        table = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "eu-west-1")).Table(os.environ["CORE_TABLE"])
        mapping = table.get_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE"}).get("Item", {})
        tenant_id = str(mapping.get("tenant_id", ""))
        mapped_role = str(mapping.get("role", ""))
    elif user_id and os.getenv("CORE_TABLE"):
        table = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "eu-west-1")).Table(os.environ["CORE_TABLE"])
        mapping = table.get_item(Key={"pk": f"USER#{user_id}", "sk": "PROFILE"}).get("Item", {})
        mapped_role = str(mapping.get("role", ""))
    if not tenant_id:
        tenant_id = os.getenv("DEFAULT_TENANT_ID", "")
    if not tenant_id:
        raise ValueError("el usuario no tiene un tenant asociado")
    if mapped_role in {"admin", "guest"}:
        groups = [mapped_role]
    groups = groups or ["guest"]
    return {
        "user_id": user_id,
        "email": str(claims.get("email", "")),
        "tenant_id": tenant_id,
        "roles": groups,
        "permissions": ["*"] if "admin" in groups else ["document.read"],
    }


def _requested_identity(event: dict[str, object], identity: dict[str, object]) -> dict[str, object]:
    """Aplica el tenant solicitado solo si el usuario tiene una membresía AWS."""
    headers = event.get("headers") or {}
    normalized = {str(key).lower(): str(value) for key, value in headers.items()} if isinstance(headers, dict) else {}
    requested = normalized.get("x-tenant-id", "").strip()
    current = str(identity["tenant_id"])
    if not requested or requested == current:
        return identity
    user_id = str(identity.get("user_id", ""))
    table_name = os.getenv("CORE_TABLE")
    if not user_id or not table_name:
        raise PermissionError("no tienes acceso a ese tenant")
    table = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "eu-west-1")).Table(table_name)
    memberships = table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("MEMBERSHIP#")
    ).get("Items", [])
    allowed = {str(item.get("tenant_id", "")) for item in memberships}
    if requested not in allowed:
        raise PermissionError("no tienes acceso a ese tenant")
    return {**identity, "tenant_id": requested}


def _body(event: dict[str, object]) -> dict[str, object]:
    raw = str(event.get("body") or "{}")
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("el cuerpo debe ser un objeto JSON")
    return parsed


def _content(payload: dict[str, object]) -> bytes:
    encoded = str(payload.get("content_base64", ""))
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    if not encoded:
        return b""
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("content_base64 no es válido") from error


def _native_text(content: bytes, content_type: str, filename: str) -> str:
    suffix = os.path.splitext(filename)[1].lower()
    if content_type in {"application/xml", "text/xml"} or suffix == ".xml":
        try:
            root = ElementTree.fromstring(content)
        except (ElementTree.ParseError, ValueError):
            return ""
        values = []
        for element in root.iter():
            value = " ".join((element.text or "").split())
            if value:
                values.append(f"{element.tag.rsplit('}', 1)[-1]}: {value}")
        return "\n".join(values)
    if content_type == "application/pdf" or suffix == ".pdf":
        try:
            from pypdf import PdfReader

            return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages).strip()
        except (ImportError, OSError, ValueError):
            return ""
    return ""


def _clients(query: str = "") -> list[dict[str, object]]:
    names = [
        "Ferretería Neria", "Construcciones Delta", "Suministros García", "Obras y Reformas Martínez",
        "Materiales López", "Ferretería El Roble", "Distribuciones Sánchez", "Instalaciones Romero",
        "Construcciones La Plaza", "Suministros Hernández", "Maderas Fernández", "Reformas Costa Azul",
        "Materiales Sancho", "Ferretería La Marina", "Obras Castellana", "Suministros del Norte",
        "Instalaciones Pardo", "Construcciones Soler", "Ferretería Santa Ana", "Materiales García y Asociados",
    ]
    clients = [
        {"id": f"CLI-{index:03d}", "name": name, "tax_id": f"B{index:07d}", "email": f"cliente{index:03d}@demo.smart-magatzem.local"}
        for index, name in enumerate(names, 1)
    ]
    term = query.strip().casefold()
    return [item for item in clients if not term or term in str(item["id"]).casefold() or term in str(item["name"]).casefold()]


def _suppliers(query: str = "") -> list[dict[str, object]]:
    names = [
        "Distribuciones Ibéricas", "Logística del Ebro", "Recambios Levante",
        "Embalajes del Mediterráneo", "Transportes Soler", "Suministros Industriales Ruiz",
        "Materiales Costa Brava", "Palets y Cargas García", "Ferretería Mayorista Centro",
        "Proveedores del Norte",
    ]
    suppliers = [
        {"id": f"SUP-{index:03d}", "name": name, "tax_id": f"B{index + 40_123_455:08d}", "email": f"proveedor{index:03d}@demo.smart-magatzem.local"}
        for index, name in enumerate(names, 1)
    ]
    term = query.strip().casefold()
    return [item for item in suppliers if not term or term in str(item["id"]).casefold() or term in str(item["name"]).casefold()]


class AwsRuntime:
    def __init__(self) -> None:
        self.region = os.getenv("AWS_REGION", "eu-west-1")
        self.bucket = os.environ["DOCUMENTS_BUCKET"]
        self.table = boto3.resource("dynamodb", region_name=self.region).Table(os.environ["CORE_TABLE"])
        self.s3 = boto3.client("s3", region_name=self.region)
        self.textract = boto3.client("textract", region_name=self.region)
        self.bedrock = boto3.client("bedrock-runtime", region_name=self.region)
        self.ses = boto3.client("ses", region_name=self.region)
        self.vision_issue = ""

    @staticmethod
    def _tenant_name(tenant_id: str) -> str:
        return "Smart Magatzem Demo" if tenant_id == "TEN-DEMO" else tenant_id

    def _tenant_metadata(self, tenant_id: str) -> dict[str, object]:
        item = self.table.get_item(Key={"pk": f"TENANT#{tenant_id}", "sk": "META"}).get("Item")
        if item:
            return {
                "id": str(item.get("id", tenant_id)),
                "name": str(item.get("name", self._tenant_name(tenant_id))),
                "status": str(item.get("status", "active")),
            }
        return {"id": tenant_id, "name": self._tenant_name(tenant_id), "status": "active"}

    def list_tenants(self, user_id: str, current_tenant_id: str) -> list[dict[str, object]]:
        memberships = self.table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("MEMBERSHIP#")
        ).get("Items", [])
        tenant_ids = {str(item.get("tenant_id", "")) for item in memberships if item.get("tenant_id")}
        tenant_ids.add(current_tenant_id)
        return [self._tenant_metadata(tenant_id) for tenant_id in sorted(tenant_ids)]

    def create_tenant(self, user_id: str, tenant_id: str, name: str) -> dict[str, object]:
        tenant_id = tenant_id.strip().upper()
        name = name.strip()
        if not tenant_id or not name:
            raise ValueError("El identificador y el nombre del tenant son obligatorios")
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,63}", tenant_id):
            raise ValueError("El identificador del tenant solo puede contener letras, números, guiones y guiones bajos")
        try:
            self.table.put_item(
                Item={"pk": f"TENANT#{tenant_id}", "sk": "META", "id": tenant_id, "name": name, "status": "active"},
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ValueError("El tenant ya existe") from error
            raise
        self.table.put_item(
            Item={
                "pk": f"USER#{user_id}",
                "sk": f"MEMBERSHIP#{tenant_id}",
                "tenant_id": tenant_id,
                "role": "admin",
            }
        )
        return {"id": tenant_id, "name": name, "status": "active"}

    def _config_json(self, tenant_id: str, config_name: str, default: object) -> object:
        item = self.table.get_item(Key={"pk": f"TENANT#{tenant_id}", "sk": f"CONFIG#{config_name}"}).get("Item")
        if not item:
            return json.loads(json.dumps(default))
        try:
            value = json.loads(str(item.get("payload", "")))
        except json.JSONDecodeError:
            return json.loads(json.dumps(default))
        return value

    def _put_config_json(self, tenant_id: str, config_name: str, value: object) -> object:
        self.table.put_item(Item={
            "pk": f"TENANT#{tenant_id}",
            "sk": f"CONFIG#{config_name}",
            "payload": json.dumps(value, ensure_ascii=False),
            "updated_at": _now(),
        })
        return value

    def document_fields(self, tenant_id: str) -> list[dict[str, object]]:
        value = self._config_json(tenant_id, "FIELDS", AWS_DEFAULT_FIELDS)
        return [dict(item) for item in value] if isinstance(value, list) and all(isinstance(item, dict) for item in value) else list(AWS_DEFAULT_FIELDS)

    def save_document_fields(self, tenant_id: str, fields: object) -> list[dict[str, object]]:
        if not isinstance(fields, list):
            raise ValueError("fields debe ser una lista de campos")
        cleaned: list[dict[str, object]] = []
        for item in fields:
            if not isinstance(item, dict):
                raise ValueError("Cada campo debe ser un objeto")
            key = str(item.get("key", "")).strip()
            label = str(item.get("label", "")).strip()
            if not key or not label or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", key):
                raise ValueError("Cada campo necesita una clave y un nombre válidos")
            cleaned.append({**item, "key": key, "label": label, "required": bool(item.get("required", False))})
        return self._put_config_json(tenant_id, "FIELDS", cleaned)

    def erp_connection(self, tenant_id: str) -> dict[str, object]:
        value = self._config_json(tenant_id, "ERP", {
            "provider": "mock_erp", "base_url": "http://127.0.0.1:9000", "auth_type": "none",
            "username": "", "secret": "", "status": "configured", "last_checked_at": None,
        })
        value = value if isinstance(value, dict) else {}
        return {
            "tenant_id": tenant_id,
            "provider": str(value.get("provider", "mock_erp")),
            "base_url": str(value.get("base_url", "")),
            "auth_type": str(value.get("auth_type", "none")),
            "username": str(value.get("username", "")),
            "secret_configured": bool(value.get("secret", "")),
            "status": str(value.get("status", "not_configured")),
            "last_checked_at": value.get("last_checked_at"),
            "updated_at": value.get("updated_at"),
        }

    def save_erp_connection(self, tenant_id: str, payload: dict[str, object]) -> dict[str, object]:
        provider = str(payload.get("provider", "generic_rest")).strip().lower() or "generic_rest"
        auth_type = str(payload.get("auth_type", "api_key")).strip().lower() or "api_key"
        base_url = str(payload.get("base_url", "")).strip().rstrip("/")
        if not base_url:
            raise ValueError("El endpoint del ERP es obligatorio")
        if provider not in {"mock_erp", "generic_rest"}:
            raise ValueError("Proveedor ERP no soportado")
        if auth_type not in {"none", "api_key", "bearer", "basic", "oauth2_client_credentials"}:
            raise ValueError("Tipo de autenticación no soportado")
        previous = self._config_json(tenant_id, "ERP", {})
        previous = previous if isinstance(previous, dict) else {}
        saved = {
            "provider": provider,
            "base_url": base_url,
            "auth_type": auth_type,
            "username": str(payload.get("username", "")).strip(),
            "secret": str(payload.get("secret", "")) or str(previous.get("secret", "")),
            "status": "saved",
            "last_checked_at": previous.get("last_checked_at"),
            "updated_at": _now(),
        }
        self._put_config_json(tenant_id, "ERP", saved)
        return self.erp_connection(tenant_id)

    def mark_erp_check(self, tenant_id: str, status: str) -> dict[str, object]:
        current = self._config_json(tenant_id, "ERP", {})
        if not isinstance(current, dict) or not current.get("base_url"):
            raise ValueError("Primero guarda la conexión del ERP")
        current["status"] = status
        current["last_checked_at"] = _now()
        self._put_config_json(tenant_id, "ERP", current)
        return self.erp_connection(tenant_id)

    def templates(self, tenant_id: str) -> list[dict[str, object]]:
        value = self._config_json(tenant_id, "TEMPLATES", [])
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            return []
        templates: list[dict[str, object]] = []
        for item in value:
            template = dict(item)
            key = str(template.get("path", ""))
            if key:
                template["url"] = self.s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=900,
                )
            templates.append(template)
        return templates

    def save_template(self, tenant_id: str, filename: str, content_base64: str, document_type: str) -> dict[str, object]:
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(filename)) or "template.pdf"
        encoded = content_base64.split(",", 1)[-1]
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("El contenido de la plantilla no es válido") from error
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("La plantilla supera el límite de 10 MB")
        template_id = f"TPL-{tenant_id}-{uuid.uuid4().hex[:8].upper()}"
        key = f"tenant-config/{tenant_id}/{template_id}-{safe_name}"
        content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        if content_type not in {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"}:
            content_type = "application/octet-stream"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)
        template = {"id": template_id, "document_type": document_type or "order", "scope": "general", "filename": safe_name, "path": key, "uploaded_at": _now()}
        stored_templates = self._config_json(tenant_id, "TEMPLATES", [])
        stored_templates = stored_templates if isinstance(stored_templates, list) else []
        self._put_config_json(tenant_id, "TEMPLATES", [*stored_templates, template])
        return self.templates(tenant_id)[-1]

    def validation_rules(self, tenant_id: str) -> dict[str, object]:
        default = {
            "delivery_note_against_order": {"enabled": True, "quantity_tolerance_percent": 0.0, "price_tolerance_percent": 0.0, "on_mismatch": "human_review"},
            "invoice_against_delivery_note": {"enabled": True, "quantity_tolerance_percent": 0.0, "price_tolerance_percent": 0.0, "on_mismatch": "human_review"},
            "duplicate_policy": "block",
            "enable_batch_documents": False,
            "max_pages_per_document": int(os.getenv("MAX_PAGES_PER_DOCUMENT", "20")),
            "deca_native_required": True,
        }
        item = self.table.get_item(Key={"pk": f"TENANT#{tenant_id}", "sk": "CONFIG#VALIDATION"}).get("Item")
        if not item:
            return default
        try:
            stored = json.loads(str(item.get("payload", "{}")))
        except json.JSONDecodeError:
            return default
        if not isinstance(stored, dict):
            return default
        return {**default, **stored}

    def capture_settings(self, tenant_id: str) -> dict[str, object]:
        default = {
            "guided_capture": True,
            "quality_gate": True,
            "torch_default": False,
            "enable_multipage": False,
            "enable_burst": False,
            "max_pages_per_document": int(os.getenv("MAX_PAGES_PER_DOCUMENT", "20")),
            "max_file_size_mb": 2,
            "remember_last_selection": True,
            "offline_queue": True,
            "confidence_threshold": 0.85,
        }
        item = self.table.get_item(Key={"pk": f"TENANT#{tenant_id}", "sk": "CONFIG#CAPTURE"}).get("Item")
        if not item:
            return default
        try:
            stored = json.loads(str(item.get("payload", "{}")))
        except json.JSONDecodeError:
            return default
        return {**default, **stored} if isinstance(stored, dict) else default

    def save_capture_settings(self, tenant_id: str, settings: dict[str, object]) -> dict[str, object]:
        current = self.capture_settings(tenant_id)
        for key in {
            "guided_capture", "quality_gate", "torch_default", "enable_multipage",
            "enable_burst", "remember_last_selection", "offline_queue",
            "max_pages_per_document", "max_file_size_mb", "confidence_threshold",
        }:
            if key in settings:
                current[key] = settings[key]
        self.table.put_item(Item={"pk": f"TENANT#{tenant_id}", "sk": "CONFIG#CAPTURE", "payload": json.dumps(current, ensure_ascii=False)})
        return current

    def save_validation_rules(self, tenant_id: str, rules: dict[str, object]) -> dict[str, object]:
        current = self.validation_rules(tenant_id)
        for section_name in ("delivery_note_against_order", "invoice_against_delivery_note"):
            section = rules.get(section_name)
            if isinstance(section, dict) and isinstance(current.get(section_name), dict):
                current[section_name] = {**current[section_name], **section}
        for key in ("duplicate_policy", "enable_batch_documents", "max_pages_per_document", "deca_native_required"):
            if key in rules:
                current[key] = rules[key]
        self.table.put_item(Item={"pk": f"TENANT#{tenant_id}", "sk": "CONFIG#VALIDATION", "payload": json.dumps(current, ensure_ascii=False)})
        return current

    def usage(self, tenant_id: str, document_id: str, service: str, operation: str, **metrics: int) -> None:
        self.table.put_item(Item={
            "pk": f"TENANT#{tenant_id}",
            "sk": f"USAGE#{_now()}#{uuid.uuid4().hex[:8]}",
            "document_id": document_id,
            "service": service,
            "operation": operation,
            "mode": "observed",
            "created_at": _now(),
            **{key: Decimal(str(value)) for key, value in metrics.items()},
        })

    def ocr(self, content: bytes, content_type: str, document_id: str, tenant_id: str) -> str:
        if content_type.startswith("text/"):
            return content.decode("utf-8", errors="ignore").strip()
        native = _native_text(content, content_type, "document")
        if native:
            return native
        result = self.textract.analyze_document(Document={"Bytes": content}, FeatureTypes=["TABLES", "FORMS"])
        self.usage(tenant_id, document_id, "Textract", "AnalyzeDocument", requests=1, pages=1)
        return "\n".join(
            str(block.get("Text", ""))
            for block in result.get("Blocks", [])
            if block.get("BlockType") == "LINE" and block.get("Text")
        ).strip()

    def vision(self, content: bytes, content_type: str, ocr_text: str, document_id: str, tenant_id: str) -> str:
        model_id = os.getenv("BEDROCK_MODEL_ID", "")
        if not model_id:
            return ""
        prompt = (
            "Interpreta este documento comercial con máxima precisión. Lee texto impreso y manuscrito, "
            "incluidas casillas marcadas. Devuelve exclusivamente un objeto JSON válido con las claves "
            "document_type (order, delivery_note, packing_list, transport_document, invoice o deca), "
            "document_number, document_direction (inbound, outbound o unknown), "
            "direction_conflict (boolean), lines [{sku, quantity}] y confidence. "
            "Si un dato no se puede leer con seguridad usa null, [], unknown o false según corresponda. "
            "Si una casilla manuscrita contradice un texto impreso, no elijas una dirección: usa unknown "
            "y direction_conflict=true.\n"
            f"Texto OCR auxiliar:\n{ocr_text}"
        )
        content_blocks: list[dict[str, object]] = [{"text": prompt}]
        if content_type in {"image/jpeg", "image/png", "image/webp", "image/gif"} and content:
            image_format = content_type.removeprefix("image/")
            content_blocks.append({"image": {"format": image_format, "source": {"bytes": content}}})
        try:
            result = self.bedrock.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": content_blocks}],
                inferenceConfig={"maxTokens": 1200, "temperature": 0},
            )
        except ClientError as error:
            error_code = str(error.response.get("Error", {}).get("Code", ""))
            error_message = str(error.response.get("Error", {}).get("Message", ""))
            if error_code == "AccessDeniedException" and "currently being verified" in error_message:
                self.vision_issue = "AWS Bedrock está pendiente de verificación de la cuenta."
            else:
                self.vision_issue = "No se ha podido utilizar el lector IA de AWS."
            return ""
        usage = result.get("usage", {})
        self.usage(
            tenant_id,
            document_id,
            "Bedrock",
            "Converse",
            requests=1,
            input_tokens=int(usage.get("inputTokens", 0)),
            output_tokens=int(usage.get("outputTokens", 0)),
        )
        return "".join(str(item.get("text", "")) for item in result.get("output", {}).get("message", {}).get("content", []))

    @staticmethod
    def _extract_model_json(text: str) -> dict[str, object] | None:
        """Extrae el primer objeto JSON aunque el modelo lo envuelva en markdown."""
        decoder = json.JSONDecoder()
        cleaned = text.replace("```json", "").replace("```JSON", "").replace("```", "")
        for index, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _normalise_document_type(value: object) -> str:
        aliases = {
            "pedido": "order",
            "pedido de compra": "order",
            "pedido de venta": "order",
            "albaran": "delivery_note",
            "albarán": "delivery_note",
            "factura": "invoice",
            "packing list": "packing_list",
            "lista de bultos": "packing_list",
            "transporte": "transport_document",
            "cmr": "transport_document",
            "deca": "deca",
            "documento electrónico": "deca",
        }
        normalised = str(value or "").strip().lower()
        return aliases.get(normalised, normalised)

    @staticmethod
    def _normalise_direction(value: object) -> str:
        aliases = {
            "entrada": "inbound",
            "inbound": "inbound",
            "compra": "inbound",
            "salida": "outbound",
            "outbound": "outbound",
            "venta": "outbound",
            "unknown": "unknown",
            "ambiguous": "unknown",
            "conflict": "unknown",
        }
        return aliases.get(str(value or "").strip().lower(), "unknown")

    @staticmethod
    def interpret(text: str, payload: dict[str, object], client_id: str) -> dict[str, object]:
        manual = payload.get("manual_data")
        model_direction_conflict = False
        if isinstance(manual, dict):
            document_type = str(manual.get("document_type", payload.get("document_type", "unknown")))
            document_number = str(manual.get("document_number", "")) or None
            direction = str(manual.get("document_direction", payload.get("document_direction", "unknown")))
            lines = manual.get("lines", []) if isinstance(manual.get("lines"), list) else []
        else:
            upper = text.upper()
            model_data = AwsRuntime._extract_model_json(text)
            if model_data:
                document_type = AwsRuntime._normalise_document_type(model_data.get("document_type"))
                document_number = str(model_data.get("document_number") or "").strip() or None
                direction = AwsRuntime._normalise_direction(model_data.get("document_direction"))
                raw_lines = model_data.get("lines") if isinstance(model_data.get("lines"), list) else []
                lines = [
                    {"sku": str(line.get("sku", "")).strip(), "quantity": line.get("quantity")}
                    for line in raw_lines
                    if isinstance(line, dict) and str(line.get("sku", "")).strip()
                ]
                model_direction_conflict = bool(model_data.get("direction_conflict"))
                if model_direction_conflict:
                    direction = "unknown"
            else:
                document_type = (
                    "invoice" if re.search(r"\bFACTURA\b|\bINVOICE\b", upper)
                    else "delivery_note" if re.search(r"\bALBAR", upper)
                    else "order" if re.search(r"\bPEDIDO\b|\bPED(?:IDO)?(?:[-_/]\d{2,})+\b", upper)
                    else "unknown"
                )
                number_match = re.search(
                    r"\b(?:PED(?:IDO)?|ALB(?:AR[AÁ]N)?|FAC(?:TURA)?|PCK|CMR|DECA)(?:[-_/]\d{2,})+\b",
                    upper,
                )
                if number_match:
                    document_number = number_match.group(0)
                else:
                    labeled_match = re.search(
                        r"(?:FACTURA|ALBAR[AÁ]N|PEDIDO|CMR|PACKING LIST|DECA)[ \t]*[:#-]?[ \t]*([A-Z0-9/_-]{3,})",
                        upper,
                    )
                    document_number = labeled_match.group(1) if labeled_match else None
                direction = str(payload.get("document_direction", "auto"))
                if direction == "auto":
                    explicit_inbound = bool(re.search(r"\bINBOUND\b|PEDIDO\s+DE\s+COMPRA|PURCHASE\s+ORDER|\bCOMPRA\b", upper))
                    explicit_outbound = bool(re.search(r"\bOUTBOUND\b|PEDIDO\s+DE\s+VENTA|SALES\s+ORDER|\bVENTA\b", upper))
                    direction = "inbound" if explicit_inbound and not explicit_outbound else "outbound" if explicit_outbound and not explicit_inbound else "unknown"
                lines = [{"sku": sku.replace(" ", "-"), "quantity": int(quantity)} for sku, quantity in re.findall(r"(SKU[- ]\d+)\s*[X×]?\s*(\d+)", upper)]
        requested_type = str(payload.get("document_type", "auto")).strip().lower()
        if requested_type and requested_type != "auto":
            document_type = requested_type
        reasons: list[str] = []
        if document_type == "unknown": reasons.append("tipo de documento")
        if not document_number: reasons.append("número de documento")
        if direction not in {"inbound", "outbound"}:
            reasons.append(
                "la dirección manuscrita y la impresa no coinciden"
                if not isinstance(manual, dict) and model_direction_conflict
                else "dirección de entrada o salida"
            )
        if not lines: reasons.append("líneas de producto")
        details: dict[str, object] = {}
        order_reference = re.search(r"\bPED(?:IDO)?[-_/]\d{2,}(?:[-_/]\d+)*\b", (text or "").upper())
        delivery_reference = re.search(r"\bALB(?:AR[AÁ]N)?[-_/]\d{2,}(?:[-_/]\d+)*\b", (text or "").upper())
        if order_reference:
            details["related_order_number"] = order_reference.group(0)
        if delivery_reference:
            details["related_delivery_note_number"] = delivery_reference.group(0)
        return {
            "rules_version": "aws-v1",
            "client_id": client_id,
            "requested_document_type": payload.get("document_type", "auto"),
            "document_type": document_type,
            "document_direction": direction,
            "order_kind": "purchase" if direction == "inbound" and document_type == "order" else "sales" if direction == "outbound" and document_type == "order" else "unknown",
            "details": details,
            "document_number": document_number,
            "document_customer": {"id": client_id, "name": None, "tax_id": None},
            "selected_customer": {"id": client_id, "name": None, "tax_id": None},
            "customer_match": {"status": "matched", "reason": "cliente seleccionado por el operador"},
            "lines": lines,
            "field_confidence": {
                "document_number": 0.95 if document_number else 0.0,
                "document_type": 0.92 if document_type != "unknown" else 0.0,
                "document_direction": 0.9 if direction in {"inbound", "outbound"} else 0.0,
                "customer": 0.96,
                "lines": 0.88 if lines else 0.0,
            },
            "reasons": reasons,
            "missing_fields": reasons,
        }

    def analyze(self, payload: dict[str, object], identity: dict[str, object]) -> dict[str, object]:
        document_id = f"AWS-{uuid.uuid4().hex[:10].upper()}"
        filename = str(payload.get("filename", "document.bin"))
        content_type = str(payload.get("content_type", "application/octet-stream"))
        content = _content(payload)
        tenant_id = str(identity["tenant_id"])
        page_contents: list[tuple[bytes, str, str]] = []
        if payload.get("pages") is not None:
            enabled = os.getenv("ENABLE_BATCH_DOCUMENTS", "").strip().lower() in {"1", "true", "yes"}
            validation_rules = self.validation_rules(tenant_id)
            enabled = enabled or bool(validation_rules.get("enable_batch_documents", False))
            max_pages = int(validation_rules.get("max_pages_per_document", os.getenv("MAX_PAGES_PER_DOCUMENT", "20")))
            if not enabled or not isinstance(payload.get("pages"), list) or not payload.get("pages") or len(payload["pages"]) > max_pages:
                return {
                    "id": document_id,
                    "filename": filename,
                    "client_id": payload.get("client_id", ""),
                    "client_email": payload.get("client_email", ""),
                    "content_type": content_type,
                    "source_object_key": "",
                    "tenant_id": tenant_id,
                    "input_mode": "document",
                    "quality": "needs_review",
                    "quality_report": {"status": "review", "decision": "review", "provider": "aws", "reasons": ["la subida multipágina está desactivada"]},
                    "ocr": {"status": "empty", "text": ""},
                    "missing_fields": ["activar ENABLE_BATCH_DOCUMENTS" if not enabled else f"máximo de {max_pages} páginas"],
                    "interpretation": {"reasons": ["la subida multipágina está desactivada" if not enabled else f"el documento supera el límite de {max_pages} páginas"], "missing_fields": ["activar ENABLE_BATCH_DOCUMENTS" if not enabled else f"máximo de {max_pages} páginas"]},
                    "can_send": False,
                    "status": "blocked",
                }
            for page in payload["pages"]:
                if not isinstance(page, dict):
                    continue
                page_content = _content(page)
                if page_content:
                    page_contents.append((page_content, str(page.get("content_type", content_type)), str(page.get("filename", "page"))))
            if page_contents:
                content = page_contents[0][0]
        ocr_text = "\n\n".join(
            self.ocr(page_content, page_type, document_id, tenant_id)
            for page_content, page_type, _page_name in (page_contents or [(content, content_type, filename)])
            if page_content
        ).strip()
        native_source_text = _native_text(content, content_type, filename)
        vision_text = "" if native_source_text else self.vision(content, content_type, ocr_text, document_id, tenant_id)
        interpretation = self.interpret(vision_text or ocr_text, payload, str(payload.get("client_id", "")))
        reference_text = ocr_text.upper()
        interpretation_details = interpretation.get("details") if isinstance(interpretation.get("details"), dict) else {}
        order_reference = re.search(r"\bPED(?:IDO)?[-_/]\d{2,}(?:[-_/]\d+)*\b", reference_text)
        delivery_reference = re.search(r"\bALB(?:AR[AÁ]N)?[-_/]\d{2,}(?:[-_/]\d+)*\b", reference_text)
        if order_reference:
            interpretation_details["related_order_number"] = order_reference.group(0)
        if delivery_reference:
            interpretation_details["related_delivery_note_number"] = delivery_reference.group(0)
        interpretation["details"] = interpretation_details
        import hashlib
        fingerprint = hashlib.sha256(content).hexdigest() if content else None
        duplicate = self._find_duplicate(tenant_id, fingerprint, interpretation)
        if duplicate["status"] == "duplicate":
            interpretation["reasons"].insert(0, "el documento ya se ha procesado anteriormente")
            interpretation["missing_fields"].insert(0, "documento no duplicado")
        cross_validation = self._cross_validate(tenant_id, interpretation)
        if cross_validation.get("status") == "blocked":
            interpretation["reasons"].extend(cross_validation.get("reasons", []))
            interpretation["missing_fields"].extend(cross_validation.get("missing_fields", []))
        native_text = native_source_text
        requested_type = str(payload.get("document_type", "auto"))
        native_reading = {
            "format": "xml" if content_type in {"application/xml", "text/xml"} or filename.lower().endswith(".xml") else "pdf" if content_type == "application/pdf" or filename.lower().endswith(".pdf") else "other",
            "is_native": bool(native_text),
            "ocr_used": bool(content) and not bool(native_text),
            "text_available": bool(native_text),
            "required": requested_type == "deca",
        }
        if requested_type == "deca" and not native_reading["is_native"]:
            interpretation["reasons"].append("DeCA requiere un PDF o XML nativo; no se acepta una foto o un escaneo")
            interpretation["missing_fields"].append("documento DeCA nativo")
        if str(payload.get("document_direction", "auto")) == "auto" and payload.get("manual_data") is None:
            pass
        ai_reasons = [self.vision_issue] if self.vision_issue else []
        can_send = not interpretation["reasons"] and not ai_reasons
        analysis = {
            "id": document_id,
            "filename": filename,
            "client_id": payload.get("client_id", ""),
            "client_email": payload.get("client_email", ""),
            "content_type": content_type,
            # El documento se mantiene temporalmente en memoria durante el
            # análisis. Solo process() lo persiste tras can_send=True.
            "source_object_key": "",
            "content_fingerprint": fingerprint,
            "duplicate_check": duplicate,
            "cross_validation": cross_validation,
            "native_reading": native_reading,
            "pages_count": len(page_contents) or 1,
            "tenant_id": tenant_id,
            "input_mode": "manual" if isinstance(payload.get("manual_data"), dict) else "document",
            "quality": "good" if can_send else "needs_review",
            "quality_report": {
                "status": "degraded" if ai_reasons else "aws",
                "score": 1.0 if not ai_reasons else 0.0,
                "decision": "pass" if can_send else "review",
                "provider": "textract" if ai_reasons else "bedrock+textract",
                "reasons": ai_reasons,
            },
            "ocr": {"status": "completed" if ocr_text else "empty", "text": ocr_text},
            "missing_fields": interpretation["missing_fields"],
            "interpretation": interpretation,
            "can_send": can_send,
            "status": "ready" if can_send else "blocked",
        }
        self.table.put_item(Item={"pk": f"TENANT#{tenant_id}", "sk": f"ANALYSIS#{document_id}", "payload": json.dumps(analysis, ensure_ascii=False)})
        return analysis

    def _find_duplicate(self, tenant_id: str, fingerprint: str | None, interpretation: dict[str, object]) -> dict[str, object]:
        response = self.table.query(KeyConditionExpression=Key("pk").eq(f"TENANT#{tenant_id}") & Key("sk").begins_with("DOCUMENT#"))
        for item in response.get("Items", []):
            try:
                record = json.loads(str(item.get("payload", "{}")))
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if fingerprint and record.get("content_fingerprint") == fingerprint:
                return {"status": "duplicate", "kind": "exact", "existing_record_id": record.get("id")}
            existing = record.get("interpretation")
            if isinstance(existing, dict) and record.get("client_id") == interpretation.get("client_id") and existing.get("document_type") == interpretation.get("document_type") and existing.get("document_number") and existing.get("document_number") == interpretation.get("document_number"):
                return {"status": "duplicate", "kind": "business_key", "existing_record_id": record.get("id")}
        return {"status": "new", "kind": None, "existing_record_id": None}

    def _cross_validate(self, tenant_id: str, interpretation: dict[str, object]) -> dict[str, object]:
        document_type = str(interpretation.get("document_type", ""))
        expected_type = "order" if document_type == "delivery_note" else "delivery_note" if document_type == "invoice" else ""
        if not expected_type:
            return {"status": "not_applicable", "reasons": [], "missing_fields": []}
        rules = self.validation_rules(tenant_id)
        rule_key = "delivery_note_against_order" if document_type == "delivery_note" else "invoice_against_delivery_note"
        rule = rules.get(rule_key) if isinstance(rules.get(rule_key), dict) else {}
        if not bool(rule.get("enabled", True)):
            return {"status": "disabled", "reasons": [], "missing_fields": []}
        details = interpretation.get("details") if isinstance(interpretation.get("details"), dict) else {}
        relation_key = "related_order_number" if document_type == "delivery_note" else "related_delivery_note_number"
        reference = str(details.get(relation_key) or "").strip()
        if not reference:
            return {"status": "warning", "reference": None, "reasons": [], "missing_fields": []}
        response = self.table.query(KeyConditionExpression=Key("pk").eq(f"TENANT#{tenant_id}") & Key("sk").begins_with("DOCUMENT#"))
        for item in response.get("Items", []):
            try:
                record = json.loads(str(item.get("payload", "{}")))
            except json.JSONDecodeError:
                continue
            existing = record.get("interpretation") if isinstance(record, dict) else None
            if not isinstance(existing, dict) or existing.get("document_type") != expected_type or existing.get("document_number") != reference:
                continue
            if str(record.get("client_id")) != str(interpretation.get("client_id")):
                return {"status": "blocked", "reference": reference, "reasons": ["el documento relacionado pertenece a otro cliente"], "missing_fields": ["cliente relacionado"]}
            related_lines = existing.get("lines", []) if isinstance(existing.get("lines"), list) else []
            current_lines = interpretation.get("lines", []) if isinstance(interpretation.get("lines"), list) else []
            expected_by_sku = {str(line.get("sku")): line for line in related_lines if isinstance(line, dict)}
            mismatches = []
            quantity_tolerance = float(rule.get("quantity_tolerance_percent", 0) or 0)
            for line in current_lines:
                if not isinstance(line, dict) or str(line.get("sku")) not in expected_by_sku:
                    continue
                expected_line = expected_by_sku[str(line.get("sku"))]
                try:
                    actual_quantity = float(line.get("quantity", 0))
                    expected_quantity = float(expected_line.get("quantity", 0))
                except (TypeError, ValueError):
                    continue
                if abs(actual_quantity - expected_quantity) > abs(expected_quantity) * quantity_tolerance / 100:
                    mismatches.append({"sku": line.get("sku"), "field": "quantity", "expected": expected_quantity, "actual": actual_quantity, "tolerance_percent": quantity_tolerance})
            if mismatches:
                return {"status": "blocked", "reference": reference, "reasons": ["las cantidades no coinciden con el documento relacionado"], "missing_fields": ["validación de cantidades"], "mismatches": mismatches}
            return {"status": "passed", "reference": reference, "reasons": [], "missing_fields": []}
        return {"status": "warning", "reference": reference, "reasons": ["no se ha encontrado el documento relacionado en el historial del tenant"], "missing_fields": []}

    def process(self, payload: dict[str, object], identity: dict[str, object]) -> dict[str, object]:
        analysis = self.analyze(payload, identity)
        tenant_id = str(identity["tenant_id"])
        if not analysis["can_send"]:
            return {**analysis, "status": "rejected"}
        document_id = str(analysis["id"])
        erp_id = f"ERP-AWS-{uuid.uuid4().hex[:8].upper()}"
        erp = {"id": erp_id, "status": "received", "document_number": analysis["interpretation"]["document_number"]}
        content = _content(payload)
        if str(analysis["content_type"]).startswith("image/") and len(content) > MAX_PERSISTED_IMAGE_BYTES:
            return {
                **analysis,
                "can_send": False,
                "status": "rejected",
                "quality_report": {
                    **dict(analysis["quality_report"]),
                    "decision": "review",
                    "reasons": ["la imagen supera el límite de 2 MB después de la compresión"],
                },
                "missing_fields": ["imagen inferior a 2 MB"],
            }
        client_email = str(payload.get("client_email", "")).strip()
        recipient_override = os.getenv("EMAIL_RECIPIENT_OVERRIDE", "").strip()
        recipient = recipient_override or client_email
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", str(analysis["filename"]))
        source_key = f"incoming/{tenant_id}/{document_id}/{safe_name}"
        page_entries = payload.get("pages") if isinstance(payload.get("pages"), list) else []
        source_keys = []
        if page_entries:
            for index, page in enumerate(page_entries, 1):
                if not isinstance(page, dict):
                    continue
                page_content = _content(page)
                page_name = re.sub(r"[^A-Za-z0-9._-]", "_", str(page.get("filename", f"page-{index}")))
                page_key = f"incoming/{tenant_id}/{document_id}/pages/{index:03d}-{page_name}"
                self.s3.put_object(Bucket=self.bucket, Key=page_key, Body=page_content, ContentType=str(page.get("content_type", analysis["content_type"])))
                source_keys.append(page_key)
                self.usage(tenant_id, document_id, "S3", "PutObject · evidencia multipágina", requests=1)
        else:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=source_key,
                Body=content or b"documento pendiente",
                ContentType=str(analysis["content_type"]),
            )
            self.usage(tenant_id, document_id, "S3", "PutObject · evidencia", requests=1)
            source_keys = [source_key]
        if source_keys:
            source_key = source_keys[0]
        analysis["source_object_key"] = source_key
        analysis["source_object_keys"] = source_keys
        copy_key = f"client-copies/{tenant_id}/{document_id}-{safe_name}"
        self.s3.put_object(Bucket=self.bucket, Key=copy_key, Body=content or b"copia del documento", ContentType=str(analysis["content_type"]))
        self.usage(tenant_id, document_id, "S3", "PutObject · copia cliente", requests=1)
        email_delivery: dict[str, object] = {"status": "not_required", "provider": "aws-ses"}
        # During testing, an explicit override must exercise the real SES path even
        # when OCR has not classified the document direction as outbound yet. In
        # normal operation (without an override), preserve the outbound-only rule.
        should_send_email = bool(recipient_override) or analysis["interpretation"]["document_direction"] == "outbound"
        if should_send_email and recipient:
            sender = os.getenv("SES_FROM_EMAIL", "")
            if sender:
                self.ses.send_email(
                    Source=sender,
                    Destination={"ToAddresses": [recipient]},
                    Message={
                        "Subject": {"Data": f"Documento {analysis['interpretation']['document_number']}", "Charset": "UTF-8"},
                        "Body": {"Text": {"Data": "Copia del documento procesado.", "Charset": "UTF-8"}},
                    },
                )
                self.usage(tenant_id, document_id, "SES", "SendEmail · copia cliente", requests=1, messages=1)
                email_delivery = {"status": "sent", "provider": "aws-ses", "to": recipient}
                if recipient_override:
                    email_delivery["intended_to"] = client_email
                    email_delivery["redirected"] = True
            else:
                email_delivery = {"status": "not_configured", "provider": "aws-ses", "to": recipient}
                if recipient_override:
                    email_delivery["intended_to"] = client_email
                    email_delivery["redirected"] = True
        record = {**analysis, "status": "sent_to_erp", "erp": erp, "connector": "mock_aws", "client_copy": {"status": "prepared", "object_key": copy_key}, "email_delivery": email_delivery}
        record["evidence_url"] = self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": source_key},
            ExpiresIn=3600,
        )
        self.table.put_item(Item={"pk": f"TENANT#{tenant_id}", "sk": f"DOCUMENT#{document_id}", "payload": json.dumps(record, ensure_ascii=False)})
        return record

    def usage_snapshot(self, tenant_id: str) -> dict[str, object]:
        response = self.table.query(KeyConditionExpression=Key("pk").eq(f"TENANT#{tenant_id}") & Key("sk").begins_with("USAGE#"))
        events = []
        for item in response.get("Items", []):
            event = dict(item)
            for key in ("requests", "pages", "input_tokens", "output_tokens", "state_transitions", "messages"):
                event[key] = int(event.get(key, 0))
            events.append(event)
        events = [annotate_event(event) for event in events]
        totals = {key: sum(int(event.get(key, 0)) for event in events) for key in ("requests", "pages", "input_tokens", "output_tokens", "state_transitions", "messages")}
        services: dict[str, dict[str, object]] = {}
        for event in events:
            service = str(event.get("service", "AWS"))
            services.setdefault(service, {"service": service, "requests": 0, "pages": 0, "input_tokens": 0, "output_tokens": 0, "state_transitions": 0, "messages": 0, "token_cost_eur": 0.0})
            current = services[service]
            for key in ("requests", "pages", "input_tokens", "output_tokens", "state_transitions", "messages"):
                current[key] = int(current[key]) + int(event.get(key, 0))
            current["token_cost_eur"] = round(float(current["token_cost_eur"]) + float(event.get("token_cost_eur", 0)), 8)
        token_cost = sum_token_cost(events)
        return {
            "provider": "aws",
            "aws_connected": True,
            "cognito_excluded": True,
            "notice": "Consumo observado en llamadas AWS; Cognito queda fuera.",
            "pricing": pricing_config(),
            "summary": {"documents": 0, "actual": totals, "estimated": totals, "actual_token_cost_eur": token_cost, "estimated_token_cost_eur": token_cost},
            "services": list(services.values()),
            "events": list(reversed(events)),
        }

    def list_records(self, tenant_id: str) -> list[dict[str, object]]:
        response = self.table.query(KeyConditionExpression=Key("pk").eq(f"TENANT#{tenant_id}") & Key("sk").begins_with("DOCUMENT#"))
        records: list[dict[str, object]] = []
        for item in response.get("Items", []):
            try:
                record = json.loads(str(item.get("payload", "{}")))
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                key = record.get("source_object_key")
                if key:
                    record["evidence_url"] = self.s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": self.bucket, "Key": str(key)},
                        ExpiresIn=3600,
                    )
                records.append(record)
        return list(reversed(records))

    def reset_documents(self, tenant_id: str) -> dict[str, object]:
        """Remove document and analysis records plus their S3 objects for one tenant."""
        items: list[dict[str, object]] = []
        for prefix in ("DOCUMENT#", "ANALYSIS#"):
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq(f"TENANT#{tenant_id}") & Key("sk").begins_with(prefix)
            )
            items.extend(response.get("Items", []))
            while response.get("LastEvaluatedKey"):
                response = self.table.query(
                    KeyConditionExpression=Key("pk").eq(f"TENANT#{tenant_id}") & Key("sk").begins_with(prefix),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

        s3_keys: set[str] = set()
        document_count = 0
        analysis_count = 0
        for item in items:
            sort_key = str(item.get("sk", ""))
            if sort_key.startswith("DOCUMENT#"):
                document_count += 1
            elif sort_key.startswith("ANALYSIS#"):
                analysis_count += 1
            try:
                record = json.loads(str(item.get("payload", "{}")))
            except json.JSONDecodeError:
                record = {}
            if not isinstance(record, dict):
                continue
            source_key = record.get("source_object_key")
            if source_key:
                s3_keys.add(str(source_key))
            page_keys = record.get("source_object_keys", [])
            for page_key in page_keys if isinstance(page_keys, list) else []:
                if page_key:
                    s3_keys.add(str(page_key))
            client_copy = record.get("client_copy")
            if isinstance(client_copy, dict) and client_copy.get("object_key"):
                s3_keys.add(str(client_copy["object_key"]))

        deleted_objects = 0
        key_list = list(s3_keys)
        for start in range(0, len(key_list), 1000):
            batch = [{"Key": key} for key in key_list[start:start + 1000]]
            if not batch:
                continue
            self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": batch, "Quiet": True})
            deleted_objects += len(batch)
        for item in items:
            self.table.delete_item(Key={"pk": str(item["pk"]), "sk": str(item["sk"])})

        return {
            "tenant_id": tenant_id,
            "deleted_documents": document_count,
            "deleted_analysis": analysis_count,
            "deleted_objects": deleted_objects,
            "preserved": ["tenant configuration", "templates", "usage telemetry"],
        }

    def source_url(self, tenant_id: str, document_id: str) -> str | None:
        item = self.table.get_item(Key={"pk": f"TENANT#{tenant_id}", "sk": f"DOCUMENT#{document_id}"}).get("Item")
        if not item:
            return None
        try:
            record = json.loads(str(item.get("payload", "{}")))
        except json.JSONDecodeError:
            return None
        key = record.get("source_object_key") if isinstance(record, dict) else None
        if not key:
            return None
        return self.s3.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": str(key)}, ExpiresIn=300)


def handler(event: dict[str, object], _context) -> dict[str, object]:
    path = str(event.get("rawPath", "/"))
    method = str(event.get("requestContext", {}).get("http", {}).get("method", "GET")) if isinstance(event.get("requestContext"), dict) else "GET"
    if method == "OPTIONS":
        return _response(204, {})
    try:
        identity = _requested_identity(event, _identity(event))
    except PermissionError as error:
        return _response(403, {"error": str(error)})
    if path == "/health":
        return _response(200, {"status": "ok", "service": "smart-magatzem-aws", "ai_provider": "aws", "auth_provider": "cognito"})
    runtime = AwsRuntime()
    if path == "/api/auth/me" and method == "GET":
        return _response(200, {"user": identity})
    if path == "/api/tenants":
        if "*" not in identity["permissions"]:
            return _response(403, {"error": "solo un administrador puede gestionar tenants"})
        if method == "GET":
            return _response(200, {"data": runtime.list_tenants(str(identity["user_id"]), str(identity["tenant_id"]))})
        if method == "POST":
            payload = _body(event)
            return _response(201, runtime.create_tenant(str(identity["user_id"]), str(payload.get("id", "")), str(payload.get("name", ""))))
    if path == "/api/admin/erp-connection":
        if "*" not in identity["permissions"]:
            return _response(403, {"error": "solo un administrador puede cambiar la conexión ERP"})
        if method == "GET":
            return _response(200, runtime.erp_connection(str(identity["tenant_id"])))
        if method == "POST":
            return _response(200, runtime.save_erp_connection(str(identity["tenant_id"]), _body(event)))
    if path == "/api/admin/erp-connection/test" and method == "POST":
        if "*" not in identity["permissions"]:
            return _response(403, {"error": "solo un administrador puede probar la conexión ERP"})
        return _response(200, {"status": "configured", "connection": runtime.mark_erp_check(str(identity["tenant_id"]), "connected"), "response": {"mode": "aws-demo"}})
    if path == "/api/admin/document-config" and method == "GET":
        if "*" not in identity["permissions"]:
            return _response(403, {"error": "solo un administrador puede consultar la configuración"})
        return _response(200, {
            "tenant_id": identity["tenant_id"],
            "fields": runtime.document_fields(str(identity["tenant_id"])),
            "templates": runtime.templates(str(identity["tenant_id"])),
            "validation_rules": runtime.validation_rules(str(identity["tenant_id"])),
            "capture_settings": runtime.capture_settings(str(identity["tenant_id"])),
        })
    if path == "/api/admin/document-config/fields" and method == "POST":
        if "*" not in identity["permissions"]:
            return _response(403, {"error": "solo un administrador puede cambiar los campos"})
        return _response(200, {"fields": runtime.save_document_fields(str(identity["tenant_id"]), _body(event).get("fields"))})
    if path == "/api/admin/document-config/templates" and method == "POST":
        if "*" not in identity["permissions"]:
            return _response(403, {"error": "solo un administrador puede cargar plantillas"})
        payload = _body(event)
        return _response(201, runtime.save_template(str(identity["tenant_id"]), str(payload.get("filename", "")), str(payload.get("content_base64", "")), str(payload.get("document_type", "order"))))
    if path == "/api/tenant/capture-settings" and method == "GET":
        return _response(200, {
            "tenant_id": identity["tenant_id"],
            "capture_settings": runtime.capture_settings(str(identity["tenant_id"])),
        })
    if path == "/api/admin/document-config/capture-settings":
        if "*" not in identity["permissions"]:
            return _response(403, {"error": "solo un administrador puede cambiar la configuración de captura"})
        if method == "GET":
            return _response(200, {"capture_settings": runtime.capture_settings(str(identity["tenant_id"]))})
        if method == "POST":
            return _response(200, {"capture_settings": runtime.save_capture_settings(str(identity["tenant_id"]), _body(event).get("capture_settings", {}))})
    if path == "/api/admin/document-config/validation-rules":
        if "*" not in identity["permissions"]:
            return _response(403, {"error": "solo un administrador puede cambiar las reglas del tenant"})
        if method == "GET":
            return _response(200, {"validation_rules": runtime.validation_rules(str(identity["tenant_id"]))})
        if method == "POST":
            return _response(200, {"validation_rules": runtime.save_validation_rules(str(identity["tenant_id"]), _body(event).get("validation_rules", {}))})
    if path == "/api/admin/documents/reset" and method == "POST":
        if "*" not in identity["permissions"]:
            return _response(403, {"error": "solo un administrador puede reiniciar documentos"})
        return _response(200, runtime.reset_documents(str(identity["tenant_id"])))
    if path == "/api/customers" and method == "GET":
        query = str((event.get("queryStringParameters") or {}).get("q", ""))
        return _response(200, {"data": _clients(query)})
    if path == "/api/suppliers" and method == "GET":
        query = str((event.get("queryStringParameters") or {}).get("q", ""))
        return _response(200, {"data": _suppliers(query)})
    if path in {"/api/intake/documents", "/api/intake/delivery-notes"} and method == "GET":
        return _response(200, {"data": runtime.list_records(str(identity["tenant_id"]))})
    if path.startswith("/api/intake/documents/") and path.endswith("/document") and method == "GET":
        document_id = path.removeprefix("/api/intake/documents/").removesuffix("/document").strip("/")
        source_url = runtime.source_url(str(identity["tenant_id"]), document_id)
        return _redirect(source_url) if source_url else _response(404, {"error": "evidencia no encontrada"})
    if path == "/api/usage/aws" and method == "GET":
        return _response(200, runtime.usage_snapshot(str(identity["tenant_id"])))
    if method == "POST" and path.startswith("/api/intake/") and "*" not in identity["permissions"]:
        return _response(403, {"error": "el rol guest no puede procesar documentos"})
    if path in {"/api/intake/documents/analyze", "/api/intake/delivery-notes/analyze"} and method == "POST":
        return _response(200, runtime.analyze(_body(event), identity))
    if path in {"/api/intake/documents", "/api/intake/delivery-notes"} and method == "POST":
        return _response(202, runtime.process(_body(event), identity))
    return _response(404, {"error": "ruta no encontrada"})
