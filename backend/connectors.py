"""Conectores de salida del documento canónico.

El conector de fichero permite probar la integración sin conocer todavía la API
del ERP. Produce formatos auditables y compatibles con herramientas ofimáticas.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from xml.sax.saxutils import escape

from .contracts import DocumentConnector


class ERPDocumentConnector:
    name = "mock_erp"

    def __init__(self, erp) -> None:
        self.erp = erp

    def health(self) -> dict[str, object]:
        return self.erp.health()

    def import_document(self, document_type: str, payload: dict[str, object]) -> dict[str, object]:
        methods = {
            "order": "import_order",
            "purchase_order": "import_order",
            "sales_order": "import_order",
            "delivery_note": "import_delivery_note",
            "packing_list": "import_packing_list",
            "transport_document": "import_transport_document",
            "invoice": "import_invoice",
            # DeCA se conserva como documento nativo y se entrega al adaptador
            # logístico hasta que el ERP exponga un endpoint DeCA específico.
            "deca": "import_transport_document",
        }
        method = getattr(self.erp, methods.get(document_type, ""), None)
        if not callable(method):
            raise ValueError(f"el ERP no admite el tipo de documento: {document_type}")
        return method(payload)


class LocalFileConnector:
    """Conector genérico local: JSON canónico + CSV + XLSX compatible con Excel."""

    name = "file"

    def __init__(self, root: str | Path = "data/connectors/files") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def health(self) -> dict[str, object]:
        return {"status": "ok", "provider": self.name, "root": str(self.root)}

    def import_document(self, document_type: str, payload: dict[str, object]) -> dict[str, object]:
        canonical = {
            "document_type": document_type,
            "payload": payload,
            "created_at": datetime.now(UTC).isoformat(),
            "connector": self.name,
        }
        digest_payload = {"document_type": document_type, "payload": payload}
        digest = hashlib.sha256(json.dumps(digest_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12].upper()
        safe_type = re.sub(r"[^a-z0-9_-]", "_", document_type.lower())
        folder = self.root / safe_type
        folder.mkdir(parents=True, exist_ok=True)
        base = folder / f"{safe_type}-{digest}"
        json_path = base.with_suffix(".json")
        csv_path = base.with_suffix(".csv")
        xlsx_path = base.with_suffix(".xlsx")
        already_exists = json_path.exists()
        if not already_exists:
            json_path.write_text(json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8")
            self._write_csv(csv_path, document_type, payload)
            self._write_xlsx(xlsx_path, document_type, payload)
        return {
            "id": f"FILE-{safe_type.upper()}-{digest}",
            "status": "already_received" if already_exists else "queued",
            "connector": self.name,
            "document_type": document_type,
            "files": {
                "json": str(json_path),
                "csv": str(csv_path),
                "xlsx": str(xlsx_path),
            },
        }

    @staticmethod
    def _write_csv(path: Path, document_type: str, payload: dict[str, object]) -> None:
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["field", "value"])
        writer.writerow(["document_type", document_type])
        for key, value in payload.items():
            if key == "lines" and isinstance(value, list):
                continue
            writer.writerow([key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value])
        lines = payload.get("lines", [])
        if isinstance(lines, list):
            writer.writerow([])
            writer.writerow(["line", "sku", "quantity"])
            for index, line in enumerate(lines, 1):
                if isinstance(line, dict):
                    writer.writerow([index, line.get("sku", ""), line.get("quantity", "")])
        path.write_text(output.getvalue(), encoding="utf-8")

    @staticmethod
    def _write_xlsx(path: Path, document_type: str, payload: dict[str, object]) -> None:
        """Escribe un XLSX mínimo sin depender de openpyxl."""
        rows: list[list[object]] = [["field", "value"], ["document_type", document_type]]
        for key, value in payload.items():
            if key != "lines":
                rows.append([key, value if isinstance(value, (str, int, float)) else json.dumps(value, ensure_ascii=False)])
        rows.append([])
        rows.append(["line", "sku", "quantity"])
        lines = payload.get("lines", [])
        if isinstance(lines, list):
            for index, line in enumerate(lines, 1):
                if isinstance(line, dict):
                    rows.append([index, line.get("sku", ""), line.get("quantity", "")])

        def cell(value: object, ref: str) -> str:
            text = escape(str(value if value is not None else ""))
            return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'

        cells = []
        for row_index, row in enumerate(rows, 1):
            row_cells = []
            for col_index, value in enumerate(row, 1):
                ref = f"{chr(64 + col_index)}{row_index}"
                row_cells.append(cell(value, ref))
            cells.append(f'<row r="{row_index}">{"".join(row_cells)}</row>')
        sheet = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(cells)}</sheetData></worksheet>'
        content_types = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
        workbook = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Documento" sheetId="1" r:id="rId1"/></sheets></workbook>'
        rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        workbook_rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", rels)
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)


def build_document_connector(erp, name: str | None = None, root: str | Path = "data/connectors/files") -> DocumentConnector:
    selected = (name or "mock_erp").strip().lower()
    if selected == "file":
        return LocalFileConnector(root)
    return ERPDocumentConnector(erp)
