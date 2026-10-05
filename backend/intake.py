"""Pipeline local para clasificar, leer y validar documentos antes del ERP."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from .connectors import ERPDocumentConnector
from .contracts import DocumentConnector, DocumentQualityAnalyzer
from .erp_client import ERPClient, ERPClientError
from .quality import LocalImageQualityAnalyzer


class IntakeError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class LocalObjectStore:
    """Sustituto local de S3 durante la fase sin AWS."""

    def __init__(self, root: str | Path = "data/local-s3") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, content: bytes) -> str:
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return key

    def put_json(self, key: str, payload: dict[str, object]) -> str:
        return self.put(key, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


class DeliveryNoteIntake:
    """Orquestación local: object store → OCR → reglas → ERP → copia cliente."""

    REQUESTED_DOCUMENT_TYPES = {
        "auto",
        "order",
        "purchase_order",
        "sales_order",
        "delivery_note",
        "packing_list",
        "transport_document",
        "invoice",
        "deca",
    }

    def __init__(
        self,
        erp: ERPClient,
        object_store: LocalObjectStore | None = None,
        quality_analyzer: DocumentQualityAnalyzer | None = None,
        connector: DocumentConnector | None = None,
        validation_rules_provider=None,
    ) -> None:
        self.erp = erp
        self.object_store = object_store or LocalObjectStore(os.getenv("LOCAL_OBJECT_STORE_DIR", "data/local-s3"))
        self.quality_analyzer = quality_analyzer or LocalImageQualityAnalyzer()
        self.connector = connector or ERPDocumentConnector(erp)
        self.validation_rules_provider = validation_rules_provider
        self.records: list[dict[str, object]] = self._load_records()

    def list_records(self, tenant_id: str | None = None) -> list[dict[str, object]]:
        records = self.records if not tenant_id else [record for record in self.records if str(record.get("tenant_id", "TEN-LOCAL")) == tenant_id]
        return list(reversed(records))

    def get_record(self, record_id: str, tenant_id: str | None = None) -> dict[str, object] | None:
        return next(
            (
                record.copy()
                for record in self.records
                if record.get("id") == record_id
                and (tenant_id is None or str(record.get("tenant_id", "TEN-LOCAL")) == tenant_id)
            ),
            None,
        )

    def get_source_document(self, record_id: str, tenant_id: str | None = None) -> tuple[bytes, str, str] | None:
        record = self.get_record(record_id, tenant_id)
        if not record:
            return None
        source_key = str(record.get("source_object_key", ""))
        source_path = self.object_store.root / source_key
        try:
            content = source_path.read_bytes()
        except OSError:
            return None
        content_type = str(record.get("content_type", "")) or mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        return content, content_type, source_path.name

    def _load_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        metadata_dir = self.object_store.root / "metadata"
        if not metadata_dir.exists():
            return records
        for metadata_path in sorted(metadata_dir.glob("*.json")):
            try:
                record = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(record, dict) and record.get("id"):
                records.append(record)
        return sorted(records, key=lambda record: str(record.get("created_at", "")))

    def analyze(self, payload: dict[str, object]) -> dict[str, object]:
        """Previsualiza OCR e interpretación sin enviar nada al ERP."""
        analysis = self._analyze_payload(payload, "ANL")
        analysis.pop("_content", None)
        self.object_store.put_json(f"analysis/{analysis['id']}.json", analysis)
        return analysis

    def process(self, payload: dict[str, object]) -> dict[str, object]:
        analysis = self._analyze_payload(payload, "INT")
        filename = str(analysis["filename"])
        client_id = str(analysis["client_id"])
        client_email = str(analysis.get("client_email", "")).strip()
        content = analysis.pop("_content")
        source_key = str(analysis["source_object_key"])
        record: dict[str, object] = {
            "id": analysis["id"],
            "filename": filename,
            "client_id": client_id,
            "client_email": client_email or None,
            "document_type": analysis["interpretation"]["document_type"],
            "document_direction": analysis["interpretation"]["document_direction"],
            "content_type": analysis["content_type"],
            "source_object_key": source_key,
            "source_object_keys": analysis.get("source_object_keys", [source_key]),
            "pages_count": analysis.get("pages_count", 1),
            "content_fingerprint": analysis.get("content_fingerprint"),
            "duplicate_check": analysis.get("duplicate_check"),
            "tenant_id": analysis["tenant_id"],
            "input_mode": analysis.get("input_mode", "document"),
            "connector": self.connector.name,
            "quality_report": analysis["quality_report"],
            "ocr": analysis["ocr"],
            "interpretation": analysis["interpretation"],
            "cross_validation": analysis.get("cross_validation"),
            "native_reading": analysis.get("native_reading"),
            "status": "rejected" if not analysis["can_send"] else "accepted",
            "created_at": datetime.now(UTC).isoformat(),
        }

        if not analysis["can_send"]:
            self.object_store.put_json(f"metadata/{analysis['id']}.json", record)
            self.records.append(record)
            return record

        try:
            erp_payload = {
                "client_id": client_id,
                "document_number": analysis["interpretation"]["document_number"],
                "document_direction": analysis["interpretation"]["document_direction"],
                "order_kind": analysis["interpretation"].get("order_kind"),
                "details": analysis["interpretation"].get("details", {}),
                "lines": analysis["interpretation"]["lines"],
                "source_object_key": source_key,
            }
            erp_record = self._import_to_erp(analysis["interpretation"]["document_type"], erp_payload)
        except ERPClientError as error:
            record["status"] = "erp_rejected"
            record["erp_error"] = str(error)
            self.object_store.put_json(f"metadata/{analysis['id']}.json", record)
            self.records.append(record)
            return record

        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
        client_copy_key = f"client-copies/{client_id}/{analysis['id']}-{safe_name}"
        self.object_store.put(client_copy_key, content or b"copia local del documento")
        record["erp"] = erp_record
        record["client_copy"] = {"status": "prepared", "object_key": client_copy_key}
        record["email_delivery"] = self._prepare_client_email(record, client_email, client_copy_key)
        record["status"] = "sent_to_erp"
        self.object_store.put_json(f"metadata/{analysis['id']}.json", record)
        self.records.append(record)
        return record

    def _analyze_payload(self, payload: dict[str, object], identifier_prefix: str) -> dict[str, object]:
        filename = str(payload.get("filename", "albaran.bin")).strip() or "albaran.bin"
        content_type = str(payload.get("content_type", "application/octet-stream"))
        client_id = str(payload.get("client_id", "")).strip()
        if not client_id:
            raise IntakeError("client_id es obligatorio")

        tenant_id = str(payload.get("tenant_id", "TEN-LOCAL")).strip() or "TEN-LOCAL"
        client_email = self._resolve_client_email(payload)
        requested_document_type = str(payload.get("document_type", "auto")).strip().lower() or "auto"
        if requested_document_type not in self.REQUESTED_DOCUMENT_TYPES:
            raise IntakeError(
                "document_type debe ser auto, order, delivery_note, packing_list, transport_document, invoice o deca"
            )
        requested_direction = str(payload.get("document_direction", "auto")).strip().lower() or "auto"
        if requested_direction not in {"auto", "inbound", "outbound"}:
            raise IntakeError("document_direction debe ser auto, inbound u outbound")
        analysis_id = f"{identifier_prefix}-{uuid.uuid4().hex[:10].upper()}"
        content, source_key, source_keys, page_types = self._prepare_sources(payload, analysis_id, filename, content_type, tenant_id)
        content_fingerprint = hashlib.sha256(content).hexdigest() if content else None

        selected_customer = self._resolve_selected_customer(payload, client_id)
        manual_data = payload.get("manual_data")
        native_reading = self._native_reading(content_type, filename, content)
        if isinstance(manual_data, dict):
            quality_report = {
                "status": "reviewed_manually",
                "score": 1.0,
                "decision": "pass",
                "provider": "manual",
                "reasons": [],
                "warnings": ["Los campos han sido confirmados manualmente por el operador."],
                "blocking_reasons": [],
            }
            ocr_text = ""
            interpretation = self._interpret_manual(
                manual_data,
                client_id,
                requested_document_type,
                selected_customer,
                requested_direction,
            )
            input_mode = "manual"
        else:
            quality_report = self.quality_analyzer.analyze(content, content_type, filename)
            ocr_chunks = [self._run_ocr(key, page_type) for key, page_type in zip(source_keys, page_types)]
            ocr_text = "\n\n".join(chunk for chunk in ocr_chunks if chunk).strip()
            interpretation = self._interpret(
                ocr_text,
                client_id,
                requested_document_type,
                selected_customer,
                requested_direction,
            )
            input_mode = "document"
        duplicate_check = self._find_duplicate(
            tenant_id,
            client_id,
            content_fingerprint,
            interpretation,
        )
        if duplicate_check["status"] == "duplicate":
            policy = str(self._validation_rules(tenant_id).get("duplicate_policy", "block"))
            if policy == "block":
                interpretation["reasons"].insert(0, "el documento ya se ha procesado anteriormente")
                interpretation["missing_fields"].insert(0, "documento no duplicado")
            elif policy == "warning":
                interpretation.setdefault("warnings", []).append("el documento parece duplicado")

        cross_validation = self._cross_validate(tenant_id, interpretation)
        if cross_validation.get("status") == "blocked":
            interpretation["reasons"].extend(str(item) for item in cross_validation.get("reasons", []))
            interpretation["missing_fields"].extend(str(item) for item in cross_validation.get("missing_fields", []))

        if requested_document_type == "deca":
            if not native_reading.get("is_native"):
                interpretation["reasons"].append("DeCA requiere un PDF o XML nativo; no se acepta una foto o un escaneo")
                interpretation["missing_fields"].append("documento DeCA nativo")
            native_reading["required"] = True
        if not client_email and interpretation["document_direction"] != "inbound":
            interpretation["reasons"].append("falta el correo del cliente para enviar la copia")
            interpretation["missing_fields"].append("correo del cliente")
        elif client_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", client_email):
            interpretation["reasons"].append("el correo del cliente no es válido")
            interpretation["missing_fields"].append("correo del cliente válido")
        if quality_report.get("decision") == "review":
            quality_reasons = quality_report.get("reasons", [])
            reason = "calidad de imagen insuficiente: " + "; ".join(str(item) for item in quality_reasons)
            interpretation["reasons"].insert(0, reason)
            interpretation["missing_fields"].insert(0, "calidad de imagen")
        missing_fields = interpretation["missing_fields"]
        can_send = not interpretation["reasons"]
        return {
            "id": analysis_id,
            "filename": filename,
            "client_id": client_id,
            "client_email": client_email,
            "content_type": content_type,
            "source_object_key": source_key,
            "source_object_keys": source_keys,
            "pages_count": len(source_keys),
            "content_fingerprint": content_fingerprint,
            "tenant_id": tenant_id,
            "input_mode": input_mode,
            "ocr": {"status": "manual" if input_mode == "manual" else "completed" if ocr_text else "empty", "text": ocr_text},
            "quality": "good" if (input_mode == "manual" or (quality_report.get("status") in {"good", "not_applicable"} and ocr_text)) and not missing_fields and not interpretation["reasons"] else "needs_review",
            "quality_report": quality_report,
            "native_reading": native_reading,
            "duplicate_check": duplicate_check,
            "cross_validation": cross_validation,
            "missing_fields": missing_fields,
            "interpretation": interpretation,
            "can_send": can_send,
            "status": "ready" if can_send else "blocked",
            "_content": content,
        }

    def _validation_rules(self, tenant_id: str) -> dict[str, object]:
        if callable(self.validation_rules_provider):
            try:
                value = self.validation_rules_provider(tenant_id)
                if isinstance(value, dict):
                    return value
            except Exception:
                # La configuración nunca debe impedir una lectura documental.
                pass
        return {
            "delivery_note_against_order": {"enabled": True, "on_mismatch": "human_review"},
            "invoice_against_delivery_note": {"enabled": True, "on_mismatch": "human_review"},
            "duplicate_policy": "block",
            "enable_batch_documents": False,
            "max_pages_per_document": 20,
        }

    def _prepare_sources(
        self,
        payload: dict[str, object],
        analysis_id: str,
        filename: str,
        content_type: str,
        tenant_id: str,
    ) -> tuple[bytes, str, list[str], list[str]]:
        raw_pages = payload.get("pages")
        if raw_pages is not None:
            if not isinstance(raw_pages, list) or not raw_pages:
                raise IntakeError("pages debe ser una lista no vacía")
            rules = self._validation_rules(tenant_id)
            enabled = os.getenv("ENABLE_BATCH_DOCUMENTS", "").strip().lower() in {"1", "true", "yes"}
            enabled = enabled or bool(rules.get("enable_batch_documents", False))
            if not enabled:
                raise IntakeError("la subida multipágina está desactivada; activa ENABLE_BATCH_DOCUMENTS para probarla")
            max_pages = int(rules.get("max_pages_per_document", 20) or 20)
            if len(raw_pages) > max_pages:
                raise IntakeError(f"el documento supera el límite de {max_pages} páginas")
            keys: list[str] = []
            types: list[str] = []
            first_content = b""
            for index, page in enumerate(raw_pages, 1):
                if not isinstance(page, dict):
                    raise IntakeError(f"la página {index} no es válida")
                page_content = self._decode_content(page.get("content_base64", ""))
                if not page_content:
                    raise IntakeError(f"la página {index} está vacía")
                page_type = str(page.get("content_type", content_type)).strip() or content_type
                page_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(str(page.get("filename", f"page-{index}"))).name)
                key = f"incoming/{analysis_id}/pages/{index:03d}-{page_name}"
                self.object_store.put(key, page_content)
                keys.append(key)
                types.append(page_type)
                if not first_content:
                    first_content = page_content
            return first_content, keys[0], keys, types

        content = self._decode_content(payload.get("content_base64", ""))
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
        source_key = f"incoming/{analysis_id}/{safe_name}"
        self.object_store.put(source_key, content or b"documento pendiente de lectura")
        return content, source_key, [source_key], [content_type]

    def _native_reading(self, content_type: str, filename: str, content: bytes) -> dict[str, object]:
        suffix = Path(filename).suffix.lower()
        is_xml = content_type in {"application/xml", "text/xml"} or suffix == ".xml"
        is_pdf = content_type == "application/pdf" or suffix == ".pdf"
        if is_xml:
            text = self._parse_native_xml(content)
            return {"format": "xml", "is_native": bool(text), "ocr_used": False, "text_available": bool(text)}
        if is_pdf:
            text = self._extract_pdf_text_from_bytes(content)
            return {"format": "pdf", "is_native": bool(text), "ocr_used": not bool(text), "text_available": bool(text)}
        return {"format": "image" if content_type.startswith("image/") else "other", "is_native": False, "ocr_used": False, "text_available": False}

    @staticmethod
    def _parse_native_xml(content: bytes) -> str:
        try:
            root = ElementTree.fromstring(content)
        except (ElementTree.ParseError, ValueError):
            return ""
        values: list[str] = []
        for element in root.iter():
            value = " ".join((element.text or "").split())
            if value:
                tag = element.tag.rsplit("}", 1)[-1]
                values.append(f"{tag}: {value}")
        return "\n".join(values)

    @staticmethod
    def _extract_pdf_text_from_bytes(content: bytes) -> str:
        if not content:
            return ""
        try:
            from pypdf import PdfReader
            from io import BytesIO

            reader = PdfReader(BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except (ImportError, OSError, ValueError):
            return ""

    def _find_duplicate(
        self,
        tenant_id: str,
        client_id: str,
        content_fingerprint: str | None,
        interpretation: dict[str, object],
    ) -> dict[str, object]:
        active_statuses = {"accepted", "sent_to_erp", "erp_rejected"}
        for record in self.records:
            if str(record.get("tenant_id", "TEN-LOCAL")) != tenant_id or str(record.get("status")) not in active_statuses:
                continue
            if content_fingerprint and record.get("content_fingerprint") == content_fingerprint:
                return {"status": "duplicate", "kind": "exact", "existing_record_id": record.get("id")}
            existing_interpretation = record.get("interpretation")
            if not isinstance(existing_interpretation, dict):
                continue
            if (
                str(record.get("client_id")) == client_id
                and str(existing_interpretation.get("document_type")) == str(interpretation.get("document_type"))
                and interpretation.get("document_number")
                and existing_interpretation.get("document_number") == interpretation.get("document_number")
            ):
                return {"status": "duplicate", "kind": "business_key", "existing_record_id": record.get("id")}
        return {"status": "new", "kind": None, "existing_record_id": None}

    def _cross_validate(self, tenant_id: str, interpretation: dict[str, object]) -> dict[str, object]:
        document_type = str(interpretation.get("document_type", ""))
        rules = self._validation_rules(tenant_id)
        if document_type == "delivery_note":
            rule_key = "delivery_note_against_order"
            expected_type = "order"
            relation_key = "related_order_number"
            label = "pedido"
        elif document_type == "invoice":
            rule_key = "invoice_against_delivery_note"
            expected_type = "delivery_note"
            relation_key = "related_delivery_note_number"
            label = "albarán"
        else:
            return {"status": "not_applicable", "rule": None, "reasons": [], "missing_fields": []}
        rule = rules.get(rule_key) if isinstance(rules.get(rule_key), dict) else {}
        if not bool(rule.get("enabled", True)):
            return {"status": "disabled", "rule": rule_key, "reasons": [], "missing_fields": []}
        details = interpretation.get("details") if isinstance(interpretation.get("details"), dict) else {}
        reference = str(details.get(relation_key) or "").strip()
        result: dict[str, object] = {
            "status": "warning" if not reference else "not_checked",
            "rule": rule_key,
            "reference": reference or None,
            "reasons": [],
            "missing_fields": [],
        }
        if not reference:
            result["reasons"] = [f"no se ha encontrado la referencia al {label} para validar el documento"]
            result["missing_fields"] = [f"referencia al {label}"]
            return result

        related = next(
            (
                record
                for record in self.records
                if str(record.get("tenant_id", "TEN-LOCAL")) == tenant_id
                and str(record.get("client_id")) == str(interpretation.get("client_id"))
                and isinstance(record.get("interpretation"), dict)
                and str(record["interpretation"].get("document_type")) == expected_type
                and str(record["interpretation"].get("document_number")) == reference
                and str(record.get("status")) in {"accepted", "sent_to_erp"}
            ),
            None,
        )
        if related is None:
            getter_name = "get_order" if expected_type == "order" else "get_delivery_note"
            getter = getattr(self.erp, getter_name, None)
            if callable(getter):
                try:
                    related = getter(reference)
                except ERPClientError:
                    related = None
        if not isinstance(related, dict):
            result["status"] = "warning"
            result["reasons"] = [f"no se ha podido consultar el {label} {reference} en el ERP"]
            return result

        related_client = str(related.get("client_id") or related.get("customer_id") or "")
        if related_client and related_client != str(interpretation.get("client_id")):
            result["status"] = "blocked"
            result["reasons"] = [f"el {label} relacionado pertenece a otro cliente"]
            result["missing_fields"] = [f"cliente del {label} relacionado"]
            return result
        related_interpretation = related.get("interpretation") if isinstance(related.get("interpretation"), dict) else related
        related_lines = related_interpretation.get("lines", []) if isinstance(related_interpretation, dict) else []
        current_lines = interpretation.get("lines", [])
        mismatches = self._compare_lines(current_lines, related_lines, rule)
        if mismatches:
            result["status"] = "blocked"
            result["reasons"] = ["las cantidades o precios no coinciden con el documento relacionado"]
            result["missing_fields"] = ["validación de cantidades/precios"]
            result["mismatches"] = mismatches
            return result
        result["status"] = "passed"
        result["matched_document"] = related.get("id") or related.get("document_number") or reference
        return result

    @staticmethod
    def _compare_lines(
        current_lines: object,
        related_lines: object,
        rule: dict[str, object],
    ) -> list[dict[str, object]]:
        if not isinstance(current_lines, list) or not isinstance(related_lines, list):
            return []
        quantity_tolerance = float(rule.get("quantity_tolerance_percent", 0) or 0)
        price_tolerance = float(rule.get("price_tolerance_percent", 0) or 0)
        related_by_sku = {
            str(line.get("sku", "")).strip(): line
            for line in related_lines
            if isinstance(line, dict) and str(line.get("sku", "")).strip()
        }
        mismatches: list[dict[str, object]] = []
        for line in current_lines:
            if not isinstance(line, dict):
                continue
            sku = str(line.get("sku", "")).strip()
            expected = related_by_sku.get(sku)
            if expected is None:
                mismatches.append({"sku": sku, "reason": "SKU no presente en el documento relacionado"})
                continue
            try:
                actual_quantity = float(line.get("quantity", 0))
                expected_quantity = float(expected.get("quantity", 0))
            except (TypeError, ValueError):
                continue
            allowed_quantity = abs(expected_quantity) * quantity_tolerance / 100
            if abs(actual_quantity - expected_quantity) > allowed_quantity:
                mismatches.append({"sku": sku, "field": "quantity", "expected": expected_quantity, "actual": actual_quantity, "tolerance_percent": quantity_tolerance})
            actual_price = line.get("unit_price", line.get("price"))
            expected_price = expected.get("unit_price", expected.get("price"))
            if actual_price is not None and expected_price is not None:
                try:
                    actual_price_value = float(actual_price)
                    expected_price_value = float(expected_price)
                except (TypeError, ValueError):
                    continue
                allowed_price = abs(expected_price_value) * price_tolerance / 100
                if abs(actual_price_value - expected_price_value) > allowed_price:
                    mismatches.append({"sku": sku, "field": "price", "expected": expected_price_value, "actual": actual_price_value, "tolerance_percent": price_tolerance})
        return mismatches

    def _interpret_manual(
        self,
        manual_data: dict[str, object],
        client_id: str,
        requested_document_type: str,
        selected_customer: dict[str, object],
        requested_direction: str,
    ) -> dict[str, object]:
        """Construye una interpretación validada a partir de datos confirmados por el operador."""
        reasons: list[str] = []
        missing_fields: list[str] = []
        allowed_types = {"order", "delivery_note", "packing_list", "transport_document", "invoice", "deca"}
        document_type = str(manual_data.get("document_type", requested_document_type)).strip().lower()
        if document_type not in allowed_types:
            reasons.append("selecciona un tipo de documento válido")
            missing_fields.append("tipo de documento")
            document_type = "unknown"

        document_number = str(manual_data.get("document_number", "")).strip() or None
        if not document_number:
            document_label = self._document_label(document_type)
            reasons.append(f"falta el número de {document_label}")
            missing_fields.append(f"número de {document_label}")

        raw_direction = str(manual_data.get("document_direction", requested_direction)).strip().lower()
        document_direction = raw_direction if raw_direction in {"inbound", "outbound"} else "unknown"
        if document_direction == "unknown":
            reasons.append("selecciona si el documento es de entrada o de salida")
            missing_fields.append("dirección del documento: entrada o salida")

        lines: list[dict[str, object]] = []
        raw_lines = manual_data.get("lines", [])
        if isinstance(raw_lines, list):
            for raw_line in raw_lines:
                if not isinstance(raw_line, dict):
                    continue
                sku = str(raw_line.get("sku", "")).strip()
                try:
                    quantity = float(str(raw_line.get("quantity", "")).replace(",", "."))
                except (TypeError, ValueError):
                    quantity = 0
                if sku and quantity > 0:
                    line: dict[str, object] = {"sku": sku, "quantity": int(quantity) if quantity.is_integer() else quantity}
                    raw_price = raw_line.get("unit_price", raw_line.get("price"))
                    if raw_price not in (None, ""):
                        try:
                            line["unit_price"] = float(str(raw_price).replace(",", "."))
                        except (TypeError, ValueError):
                            pass
                    lines.append(line)
        if not lines:
            reasons.append("añade al menos una línea de producto o servicio")
            missing_fields.append("líneas de producto")

        order_kind = str(manual_data.get("order_kind", "unknown")).strip().lower()
        if order_kind not in {"purchase", "sales"}:
            order_kind = "purchase" if document_direction == "inbound" and document_type == "order" else "sales" if document_direction == "outbound" and document_type == "order" else "unknown"

        details = manual_data.get("details") if isinstance(manual_data.get("details"), dict) else {}
        safe_details: dict[str, object] = {}
        for key in {
            "packages_count",
            "weight_kg",
            "dimensions",
            "carrier",
            "vehicle_plate",
            "pickup",
            "delivery_window",
        }:
            value = details.get(key)
            if value not in (None, ""):
                safe_details[key] = value

        return {
            "rules_version": "manual-v1",
            "client_id": client_id,
            "requested_document_type": requested_document_type,
            "document_type": document_type,
            "document_direction": document_direction,
            "order_kind": order_kind,
            "details": safe_details,
            "document_number": document_number,
            "document_customer": {
                "id": selected_customer.get("id"),
                "name": selected_customer.get("name"),
                "tax_id": selected_customer.get("tax_id"),
            },
            "selected_customer": {
                "id": selected_customer.get("id", client_id),
                "name": selected_customer.get("name"),
                "tax_id": selected_customer.get("tax_id"),
            },
            "customer_match": {"status": "matched", "reason": "cliente confirmado manualmente por el operador"},
            "lines": lines,
            "field_confidence": {"document_number": 1.0, "document_type": 1.0, "document_direction": 1.0, "customer": 1.0, "lines": 1.0},
            "reasons": reasons,
            "missing_fields": missing_fields,
        }

    @staticmethod
    def _resolve_client_email(payload: dict[str, object]) -> str:
        # El correo del cliente forma parte de la lectura y la validación del
        # documento. La redirección de pruebas se aplica únicamente al envío.
        return str(payload.get("client_email", "")).strip()

    def _resolve_selected_customer(self, payload: dict[str, object], client_id: str) -> dict[str, object]:
        if self.connector.name == "file" and (payload.get("client_name") or payload.get("client_tax_id")):
            return {
                "id": client_id,
                "name": str(payload.get("client_name", "")).strip(),
                "tax_id": str(payload.get("client_tax_id", "")).strip(),
            }
        get_party = getattr(self.erp, "get_party", None)
        if callable(get_party):
            party = get_party(client_id)
            if isinstance(party, dict):
                return party
            raise IntakeError("no se ha podido recuperar la empresa seleccionada del ERP", 502)
        get_customer = getattr(self.erp, "get_customer", None)
        if callable(get_customer):
            customer = get_customer(client_id)
            if isinstance(customer, dict):
                return customer
            raise IntakeError("no se ha podido recuperar el cliente seleccionado del ERP", 502)
        return {
            "id": client_id,
            "name": str(payload.get("client_name", "")).strip(),
            "tax_id": str(payload.get("client_tax_id", "")).strip(),
        }

    def _prepare_client_email(
        self,
        record: dict[str, object],
        client_email: str,
        attachment_key: str,
    ) -> dict[str, object]:
        if record.get("document_direction") == "inbound":
            return {"status": "not_required", "provider": "local-simulation"}
        if not client_email:
            return {"status": "not_configured", "provider": "local-simulation"}
        override = (
            os.getenv("EMAIL_RECIPIENT_OVERRIDE", "").strip()
            or os.getenv("LOCAL_EMAIL_RECIPIENT_OVERRIDE", "").strip()
        )
        recipient = override or client_email
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", recipient):
            return {"status": "invalid_recipient", "provider": "local-simulation", "to": client_email}
        email_event = {
            "status": "simulated",
            "provider": "local-simulation",
            "to": recipient,
            "subject": f"Documento {record['document_type']} {record['interpretation']['document_number']}",
            "attachment_object_key": attachment_key,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if override:
            email_event["intended_to"] = client_email
            email_event["redirected"] = True
        self.object_store.put_json(f"outbox/{record['id']}.json", email_event)
        return email_event

    @staticmethod
    def _decode_content(encoded: object) -> bytes:
        if not encoded:
            return b""
        try:
            value = str(encoded)
            if value.startswith("data:") and "," in value:
                value = value.split(",", 1)[1]
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise IntakeError("content_base64 no es válido") from error

    def _run_ocr(self, source_key: str, content_type: str) -> str:
        source_path = self.object_store.root / source_key
        if content_type.startswith("text/") or source_path.suffix.lower() in {".txt", ".csv"}:
            return source_path.read_text(encoding="utf-8", errors="ignore").strip()
        if content_type in {"application/xml", "text/xml"} or source_path.suffix.lower() == ".xml":
            return self._parse_native_xml(source_path.read_bytes())
        if content_type == "application/pdf" or source_path.suffix.lower() == ".pdf":
            return self._run_pdf_ocr(source_path)
        if not content_type.startswith("image/"):
            return ""
        return self._run_tesseract(source_path)

    def _run_pdf_ocr(self, source_path: Path) -> str:
        """Lee PDFs de texto y usa OCR de imagen como respaldo local.

        Los albaranes PDF generados digitalmente contienen texto seleccionable y no
        necesitan rasterizarse. Para PDFs escaneados mantenemos el camino de
        pdftoppm + Tesseract, siempre sin depender de AWS.
        """
        embedded_text = self._extract_pdf_text(source_path)
        if embedded_text:
            return embedded_text

        try:
            with tempfile.TemporaryDirectory(prefix="smart-magatzem-ocr-") as temporary_dir:
                output_prefix = Path(temporary_dir) / "page"
                subprocess.run(
                    ["pdftoppm", "-png", "-r", "200", str(source_path), str(output_prefix)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                pages = sorted(Path(temporary_dir).glob("page-*.png"))
                return "\n".join(filter(None, (self._run_tesseract(page) for page in pages))).strip()
        except (FileNotFoundError, subprocess.SubprocessError):
            return ""

    @staticmethod
    def _extract_pdf_text(source_path: Path) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(source_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except (ImportError, OSError, ValueError):
            return ""

    @staticmethod
    def _run_tesseract(source_path: Path) -> str:
        try:
            result = subprocess.run(
                ["tesseract", str(source_path), "stdout", "-l", os.getenv("OCR_LANG", "spa+eng")],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (FileNotFoundError, subprocess.SubprocessError):
            return ""

    def _interpret(
        self,
        text: str,
        client_id: str,
        requested_document_type: str = "auto",
        selected_customer: dict[str, object] | None = None,
        requested_direction: str = "auto",
    ) -> dict[str, object]:
        reasons: list[str] = []
        missing_fields: list[str] = []
        normalized = text.upper()
        detected_document_type = self._detect_document_type(normalized)
        document_type = detected_document_type if requested_document_type == "auto" else requested_document_type

        if document_type == "unknown":
            reasons.append("no se ha podido determinar el tipo de documento")

        document_match = self._extract_document_number(normalized, document_type, requested_document_type)

        if not document_match:
            document_label = self._document_label(document_type)
            reasons.append(f"falta el número de {document_label}")
            missing_fields.append(f"número de {document_label}")

        line_matches = re.findall(r"(SKU[- ]\d+)\s*(?:X|×)?\s*(\d+)", normalized)
        lines: list[dict[str, object]] = [
            {"sku": sku.replace(" ", "-"), "quantity": int(quantity)} for sku, quantity in line_matches
        ]
        if document_type == "invoice" and not lines:
            lines = self._extract_invoice_lines(normalized)
        if not lines:
            reasons.append("no se han identificado líneas de producto o servicio")
            missing_fields.append("líneas de producto")

        document_customer = self._extract_document_customer(text)
        customer_match = self._compare_customers(document_customer, selected_customer or {"id": client_id})
        if customer_match["status"] == "mismatch":
            reasons.append("el cliente del documento no coincide con el cliente seleccionado")
            missing_fields.append("coincidencia de cliente")
        elif customer_match["status"] == "unknown":
            reasons.append("no se ha podido verificar el cliente del documento")
            missing_fields.append("cliente del documento verificable")

        order_kind = self._detect_order_kind(normalized)
        document_direction = self._detect_direction(normalized, document_type, order_kind, requested_direction)
        details = self._extract_document_details(text, document_type)
        if document_direction == "unknown":
            reasons.append("no se ha podido determinar si el documento es de entrada o de salida")
            missing_fields.append("dirección del documento: entrada o salida")

        return {
            "rules_version": "local-v3",
            "client_id": client_id,
            "requested_document_type": requested_document_type,
            "document_type": document_type,
            "document_direction": document_direction,
            "order_kind": order_kind,
            "details": details,
            "document_number": (
                document_match.group(1)
                if document_match and document_match.lastindex
                else document_match.group(0)
                if document_match
                else None
            ),
            "document_customer": document_customer,
            "selected_customer": {
                "id": selected_customer.get("id") if selected_customer else client_id,
                "name": selected_customer.get("name") if selected_customer else None,
                "tax_id": selected_customer.get("tax_id") if selected_customer else None,
            },
            "customer_match": customer_match,
            "lines": lines,
            "field_confidence": {
                "document_number": 0.96 if document_match else 0.0,
                "document_type": 0.94 if document_type != "unknown" else 0.0,
                "document_direction": 0.92 if document_direction != "unknown" else 0.0,
                "customer": 0.97 if customer_match["status"] == "matched" else 0.35 if customer_match["status"] == "unknown" else 0.12,
                "lines": 0.9 if lines else 0.0,
            },
            "reasons": reasons,
            "missing_fields": missing_fields,
        }

    def _import_to_erp(self, document_type: str, payload: dict[str, object]) -> dict[str, object]:
        try:
            return self.connector.import_document(document_type, payload)
        except ValueError as error:
            raise ERPClientError(str(error), 422) from error

    @staticmethod
    def _document_label(document_type: str) -> str:
        return {
            "order": "pedido",
            "purchase_order": "pedido de compra",
            "sales_order": "pedido de venta",
            "delivery_note": "albarán",
            "packing_list": "packing list",
            "transport_document": "documento de transporte",
            "invoice": "factura",
            "deca": "DeCA",
        }.get(document_type, "documento")

    @classmethod
    def _extract_document_number(cls, normalized: str, document_type: str, requested_document_type: str):
        prefixes = {
            "invoice": r"FACTURA|INVOICE",
            "delivery_note": r"ALBAR[AÁ]N(?:\s+DE\s+(?:SALIDA|ENTRADA))?|DELIVERY\s+NOTE|DOCUMENTO|N[ÚU]MERO",
            "order": r"PEDIDO|ORDER|PURCHASE\s+ORDER|SALES\s+ORDER|ORDEN\s+DE\s+(?:COMPRA|VENTA)",
            "purchase_order": r"PEDIDO|PURCHASE\s+ORDER|ORDEN\s+DE\s+COMPRA",
            "sales_order": r"PEDIDO|SALES\s+ORDER|ORDEN\s+DE\s+VENTA",
            "packing_list": r"PACKING\s+LIST|LISTA\s+DE\s+BULTOS|BULTOS",
            "transport_document": r"CMR|ORDEN\s+DE\s+PORTE|DOCUMENTO\s+DE\s+TRANSPORTE|TRANSPORTE",
            "deca": r"DECA|DOCUMENTO\s+ELECTR[ÓO]NICO",
        }
        prefix = prefixes.get(document_type) or prefixes.get(requested_document_type)

        # Los documentos reales suelen imprimir el identificador en una línea
        # independiente del título: PED-2026-0042, ALB-2026-0007, etc. No
        # obligamos a que aparezca junto a la palabra PEDIDO/ALBARÁN.
        identifier_prefixes = {
            "order": r"PED(?:IDO)?",
            "purchase_order": r"PED(?:IDO)?",
            "sales_order": r"PED(?:IDO)?",
            "delivery_note": r"ALB(?:AR[AÁ]N)?",
            "invoice": r"FAC(?:TURA)?",
            "packing_list": r"PCK|PACK(?:ING)?",
            "transport_document": r"CMR|TRP",
            "deca": r"DECA|DOC",
        }
        identifier_prefix = identifier_prefixes.get(document_type) or identifier_prefixes.get(requested_document_type)
        if identifier_prefix:
            standalone = re.search(
                rf"\b(?:{identifier_prefix})(?:[-_/]\d{{2,}})+\b",
                normalized,
            )
            if standalone:
                return standalone

        document_match = None
        if prefix:
            document_match = re.search(
                rf"(?:{prefix})[ \t]*(?:N[ºO.]?|[:#-])?[ \t]*([A-Z0-9][A-Z0-9/_-]{{2,}}(?:[ \t]+[A-Z0-9][A-Z0-9/_-]+)?)",
                normalized,
            )
        if not document_match and requested_document_type in {"invoice", "order", "purchase_order", "sales_order"}:
            first_line = next((line for line in normalized.splitlines() if line.strip()), "")
            document_match = re.search(r"\b([A-Z]{1,12}[-/]?\d{2,}(?:[ \t]+\d+)?)\b", first_line)
        return document_match

    @staticmethod
    def _detect_order_kind(normalized_text: str) -> str:
        if re.search(r"PEDIDO\s+DE\s+COMPRA|PURCHASE\s+ORDER|ORDEN\s+DE\s+COMPRA", normalized_text):
            return "purchase"
        if re.search(r"PEDIDO\s+DE\s+VENTA|SALES\s+ORDER|ORDEN\s+DE\s+VENTA", normalized_text):
            return "sales"
        return "unknown"

    @staticmethod
    def _extract_document_details(text: str, document_type: str) -> dict[str, object]:
        """Extrae campos logísticos sencillos para que el adaptador ERP los conserve."""
        normalized = text.upper()
        references: dict[str, object] = {}
        order_reference = re.search(
            r"\b(?:PED(?:IDO)?[-_/]\d{2,}(?:[-_/]\d+)*|PEDIDO(?:\s+DE\s+(?:COMPRA|VENTA))?\s*[:#-]?\s*(PED[-_/]\d{2,}(?:[-_/]\d+)*))\b",
            normalized,
        )
        delivery_reference = re.search(
            r"\b(?:ALB(?:AR[AÁ]N)?[-_/]\d{2,}(?:[-_/]\d+)*|ALBAR[AÁ]N\s*[:#-]?\s*(ALB[-_/]\d{2,}(?:[-_/]\d+)*))\b",
            normalized,
        )
        if order_reference:
            references["related_order_number"] = (order_reference.group(1) or order_reference.group(0)).replace(" ", "-")
        if delivery_reference:
            references["related_delivery_note_number"] = (delivery_reference.group(1) or delivery_reference.group(0)).replace(" ", "-")
        if document_type == "packing_list":
            package_match = re.search(
                r"\b(?:BULTOS|CAJAS|PALETS|PAL[ÉE]S)\b\s*(?:N[ºO.]?|TOTAL|:|-)?\s*(\d+)",
                normalized,
            )
            weight_match = re.search(
                r"\bPESO(?:\s+TOTAL)?\b\s*(?::|-)?\s*(\d+(?:[,.]\d+)?)\s*(?:KG|KGS|KILOS)?",
                normalized,
            )
            dimensions_match = re.search(r"\b(?:DIMENSIONES|DIMENSIONS)\b\s*(?::|-)?\s*([^\n]+)", normalized)
            return {
                **references,
                "packages_count": int(package_match.group(1)) if package_match else None,
                "weight_kg": float(weight_match.group(1).replace(",", ".")) if weight_match else None,
                "dimensions": dimensions_match.group(1).strip() if dimensions_match else None,
            }
        if document_type == "transport_document":
            carrier = DeliveryNoteIntake._extract_labeled_value(normalized, "TRANSPORTISTA", "CARRIER")
            pickup = DeliveryNoteIntake._extract_labeled_value(normalized, "PICKUP", "RECOGIDA", "CARGA")
            delivery_window = DeliveryNoteIntake._extract_labeled_value(
                normalized, "VENTANA HORARIA", "DELIVERY WINDOW", "FRANJA DE ENTREGA"
            )
            plate_match = re.search(r"\b(\d{4}\s?[A-Z]{3})\b", normalized)
            return {
                **references,
                "carrier": carrier,
                "vehicle_plate": plate_match.group(1).replace(" ", "") if plate_match else None,
                "pickup": pickup,
                "delivery_window": delivery_window,
            }
        return references

    @staticmethod
    def _extract_labeled_value(text: str, *labels: str) -> str | None:
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_pattern})\s*(?:[:#-])\s*([^\n]+)", text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _detect_direction(
        normalized_text: str,
        document_type: str,
        order_kind: str,
        requested_direction: str,
    ) -> str:
        if requested_direction in {"inbound", "outbound"}:
            return requested_direction
        if order_kind == "purchase":
            return "inbound"
        if order_kind == "sales":
            return "outbound"

        # INBOUND/OUTBOUND y pedido de compra/venta son marcadores explícitos.
        # Tienen prioridad sobre palabras sueltas como ENTRADA o SALIDA que
        # pueden ser solo etiquetas junto a una casilla manuscrita.
        explicit_inbound = bool(re.search(
            r"\b(INBOUND|FLUJO\s+DE\s+RECEPCI[ÓO]N|PEDIDO\s+DE\s+COMPRA|PURCHASE\s+ORDER|ORDEN\s+DE\s+COMPRA)\b",
            normalized_text,
        ))
        explicit_outbound = bool(re.search(
            r"\b(OUTBOUND|FLUJO\s+DE\s+EXPEDICI[ÓO]N|PEDIDO\s+DE\s+VENTA|SALES\s+ORDER|ORDEN\s+DE\s+VENTA)\b",
            normalized_text,
        ))
        if explicit_inbound and not explicit_outbound:
            return "inbound"
        if explicit_outbound and not explicit_inbound:
            return "outbound"
        if explicit_inbound and explicit_outbound:
            return "unknown"

        inbound = bool(re.search(r"\b(ENTRADA|RECEPCI[ÓO]N|PROVEEDOR|SUPPLIER|COMPRA)\b", normalized_text))
        outbound = bool(re.search(r"\b(SALIDA|EXPEDICI[ÓO]N|CLIENTE|CUSTOMER|VENTA)\b", normalized_text))
        if inbound and not outbound:
            return "inbound"
        if outbound and not inbound:
            return "outbound"
        return "unknown"

    @staticmethod
    def _detect_document_type(normalized_text: str) -> str:
        has_deca_marker = bool(re.search(r"\bDECA\b|DOCUMENTO\s+ELECTR[ÓO]NICO", normalized_text))
        has_invoice_marker = bool(re.search(r"\bFACTURA\b|\bINVOICE\b", normalized_text))
        has_delivery_note_marker = bool(re.search(r"\bALBAR[AÁ]N\b|\bDELIVERY\s+NOTE\b", normalized_text))
        has_packing_marker = bool(re.search(r"PACKING\s+LIST|LISTA\s+DE\s+BULTOS", normalized_text))
        has_transport_marker = bool(re.search(r"\bCMR\b|ORDEN\s+DE\s+PORTE|DOCUMENTO\s+DE\s+TRANSPORTE", normalized_text))
        has_order_marker = bool(re.search(
            r"\bPEDIDO\b|PURCHASE\s+ORDER|SALES\s+ORDER|ORDEN\s+DE\s+(?:COMPRA|VENTA)|\bPED(?:IDO)?(?:[-_/]\d{2,})+\b",
            normalized_text,
        ))
        markers = sum((has_deca_marker, has_invoice_marker, has_delivery_note_marker, has_packing_marker, has_transport_marker, has_order_marker))
        if markers != 1:
            return "unknown"
        if has_deca_marker:
            return "deca"
        if has_invoice_marker:
            return "invoice"
        if has_delivery_note_marker:
            return "delivery_note"
        if has_packing_marker:
            return "packing_list"
        if has_transport_marker:
            return "transport_document"
        if has_order_marker:
            return "order"
        return "unknown"

    @staticmethod
    def _extract_invoice_lines(normalized_text: str) -> list[dict[str, object]]:
        """Extrae líneas sencillas de facturas con código, cantidad y precio."""
        lines: list[dict[str, object]] = []
        line_pattern = re.compile(
            r"^\s*([A-Z0-9][A-Z0-9/_-]{2,})\s+.+?\s+(\d+[,.]\d{1,2})\s+(\d+[,.]\d{2})\b"
        )
        for raw_line in normalized_text.splitlines():
            match = line_pattern.search(raw_line)
            if not match:
                continue
            quantity = float(match.group(2).replace(",", "."))
            lines.append({
                "sku": match.group(1),
                "quantity": int(quantity) if quantity.is_integer() else quantity,
                "unit_price": float(match.group(3).replace(",", ".")),
            })
        return lines

    @staticmethod
    def _extract_document_customer(text: str) -> dict[str, str | None]:
        normalized = text.upper()
        document_id_match = re.search(r"\bCLI[- ]?(\d{3,})\b", normalized)
        tax_id_match = re.search(r"\b(?:[XYZ]\d{7,8}[A-Z]|\d{7,8}[A-Z])\b", normalized)
        customer_name: str | None = None
        lines = [line.strip(" |:") for line in normalized.splitlines()]
        for index, line in enumerate(lines):
            inline_match = re.match(
                r"^(?:CLIENTE|CUSTOMER|PROVEEDOR|SUPPLIER|DESTINATARIO|RECEPTOR|SHIP\s+TO|SOLD\s+TO|BILL\s+TO)\s*[:#-]\s*(.+)$",
                line,
            )
            if inline_match:
                customer_name = inline_match.group(1).strip()
                break
            if line in {
                "CLIENTE",
                "CUSTOMER",
                "PROVEEDOR",
                "SUPPLIER",
                "DESTINATARIO",
                "RECEPTOR",
                "SHIP TO",
                "SOLD TO",
                "BILL TO",
            }:
                for candidate in lines[index + 1:]:
                    if candidate and candidate not in {"OBSERVACIONES", "OBSERVATIONS"}:
                        customer_name = candidate
                        break
                if customer_name:
                    break
        return {
            "id": f"CLI-{document_id_match.group(1)}" if document_id_match else None,
            "name": customer_name,
            "tax_id": tax_id_match.group(0) if tax_id_match else None,
        }

    @classmethod
    def _compare_customers(
        cls,
        document_customer: dict[str, str | None],
        selected_customer: dict[str, object],
    ) -> dict[str, str]:
        document_id = document_customer.get("id")
        selected_id = str(selected_customer.get("id", "")).strip()
        if document_id:
            if document_id == selected_id:
                return {"status": "matched", "reason": "identificador de cliente coincidente"}
            return {"status": "mismatch", "reason": "identificadores de cliente diferentes"}

        document_tax_id = cls._normalize_customer_value(document_customer.get("tax_id"))
        selected_tax_id = cls._normalize_customer_value(selected_customer.get("tax_id"))
        if document_tax_id:
            if selected_tax_id and document_tax_id == selected_tax_id:
                return {"status": "matched", "reason": "NIF/CIF coincidente"}
            return {"status": "mismatch", "reason": "NIF/CIF diferente"}

        document_name = cls._normalize_customer_value(document_customer.get("name"))
        selected_name = cls._normalize_customer_value(selected_customer.get("name"))
        if document_name and selected_name and cls._customer_names_match(document_name, selected_name):
            return {"status": "matched", "reason": "nombre de cliente coincidente"}
        if document_name and selected_name:
            return {"status": "mismatch", "reason": "nombres de cliente diferentes"}
        return {"status": "unknown", "reason": "faltan datos identificativos del cliente"}

    @staticmethod
    def _normalize_customer_value(value: object) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^A-Z0-9]+", " ", normalized.upper()).strip()

    @classmethod
    def _customer_names_match(cls, first: str, second: str) -> bool:
        if first == second or first in second or second in first:
            return True
        first_tokens = set(first.split())
        second_tokens = set(second.split())
        shared_tokens = first_tokens.intersection(second_tokens)
        return len(shared_tokens) >= 2 and len(shared_tokens) / max(len(first_tokens), len(second_tokens)) >= 0.6
