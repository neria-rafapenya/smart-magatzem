"""Servidor mock de ERP para pruebas locales, sin base de datos ni AWS."""

from __future__ import annotations

import copy
import json
import os
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .openapi import openapi_json, swagger_html


def _now() -> str:
    return datetime.now(UTC).isoformat()


class MockERPState:
    """Estado determinista y reiniciable del ERP simulado."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.warehouses = [
            {"id": "MAG-BCN", "name": "Almacén Barcelona", "city": "Barcelona"},
            {"id": "MAG-GIR", "name": "Almacén Girona", "city": "Girona"},
        ]
        self.products = [
            {"sku": "SKU-001", "name": "Tornillo", "unit": "unit", "active": True},
            {"sku": "SKU-002", "name": "Tuerca", "unit": "unit", "active": True},
            {"sku": "SKU-003", "name": "Arandela", "unit": "unit", "active": True},
        ]
        self.customers = [
            {"id": "CLI-001", "name": "Ferretería Neria", "tax_id": "B12345678"},
            {"id": "CLI-002", "name": "Construcciones Delta", "tax_id": "B87654321"},
            {"id": "CLI-003", "name": "Suministros García", "tax_id": "B13579246"},
            {"id": "CLI-004", "name": "Obras y Reformas Martínez", "tax_id": "B24681357"},
            {"id": "CLI-005", "name": "Materiales López", "tax_id": "B31415926"},
            {"id": "CLI-006", "name": "Ferretería El Roble", "tax_id": "B27182818"},
            {"id": "CLI-007", "name": "Distribuciones Sánchez", "tax_id": "B16180339"},
            {"id": "CLI-008", "name": "Instalaciones Romero", "tax_id": "B11235813"},
            {"id": "CLI-009", "name": "Construcciones La Plaza", "tax_id": "B14142135"},
            {"id": "CLI-010", "name": "Suministros Hernández", "tax_id": "B17320508"},
            {"id": "CLI-011", "name": "Maderas Fernández", "tax_id": "B22360679"},
            {"id": "CLI-012", "name": "Reformas Costa Azul", "tax_id": "B24494897"},
            {"id": "CLI-013", "name": "Materiales Sancho", "tax_id": "B31622776"},
            {"id": "CLI-014", "name": "Ferretería La Marina", "tax_id": "B27160544"},
            {"id": "CLI-015", "name": "Obras Castellana", "tax_id": "B17364817"},
            {"id": "CLI-016", "name": "Suministros del Norte", "tax_id": "B22313016"},
            {"id": "CLI-017", "name": "Instalaciones Pardo", "tax_id": "B26457513"},
            {"id": "CLI-018", "name": "Construcciones Soler", "tax_id": "B30151134"},
            {"id": "CLI-019", "name": "Ferretería Santa Ana", "tax_id": "B34641016"},
            {"id": "CLI-020", "name": "Materiales García y Asociados", "tax_id": "B36180339"},
        ]
        for customer in self.customers:
            customer["email"] = f"cliente{customer['id'].removeprefix('CLI-')}@demo.smart-magatzem.local"
        self.suppliers = [
            {"id": "SUP-001", "name": "Distribuciones Ibéricas", "tax_id": "B40123456"},
            {"id": "SUP-002", "name": "Logística del Ebro", "tax_id": "B40234567"},
            {"id": "SUP-003", "name": "Recambios Levante", "tax_id": "B40345678"},
            {"id": "SUP-004", "name": "Embalajes del Mediterráneo", "tax_id": "B40456789"},
            {"id": "SUP-005", "name": "Transportes Soler", "tax_id": "B40567890"},
            {"id": "SUP-006", "name": "Suministros Industriales Ruiz", "tax_id": "B40678901"},
            {"id": "SUP-007", "name": "Materiales Costa Brava", "tax_id": "B40789012"},
            {"id": "SUP-008", "name": "Palets y Cargas García", "tax_id": "B40890123"},
            {"id": "SUP-009", "name": "Ferretería Mayorista Centro", "tax_id": "B40901234"},
            {"id": "SUP-010", "name": "Proveedores del Norte", "tax_id": "B41012345"},
        ]
        for supplier in self.suppliers:
            supplier["email"] = f"proveedor{supplier['id'].removeprefix('SUP-')}@demo.smart-magatzem.local"
        self.orders = [
            {
                "id": "PED-1001",
                "status": "pending",
                "customer_id": "CLI-001",
                "warehouse_id": "MAG-BCN",
                "lines": [{"sku": "SKU-002", "quantity": 4}],
            },
            {
                "id": "PED-1002",
                "status": "delivered",
                "customer_id": "CLI-002",
                "warehouse_id": "MAG-GIR",
                "lines": [{"sku": "SKU-001", "quantity": 2}],
            },
        ]
        self.delivery_notes: list[dict[str, object]] = [
            {
                "id": "ALB-1000",
                "order_id": "PED-1002",
                "customer_id": "CLI-002",
                "warehouse_id": "MAG-GIR",
                "status": "delivered",
                "lines": [{"sku": "SKU-001", "name": "Tornillo", "quantity": 2, "unit": "unit"}],
                "created_at": "2026-01-15T09:00:00+00:00",
                "confirmed_at": "2026-01-15T09:05:00+00:00",
                "delivered_at": "2026-01-15T12:00:00+00:00",
            }
        ]
        self.imported_delivery_notes: list[dict[str, object]] = []
        self.imported_invoices: list[dict[str, object]] = []
        self.imported_orders: list[dict[str, object]] = []
        self.imported_packing_lists: list[dict[str, object]] = []
        self.imported_transport_documents: list[dict[str, object]] = []

    def list_products(self, query: str = "") -> list[dict[str, object]]:
        with self._lock:
            term = query.strip().lower()
            return [
                copy.deepcopy(product)
                for product in self.products
                if not term or term in product["sku"].lower() or term in product["name"].lower()
            ]

    def reset(self) -> None:
        """Restablece los datos semilla para repetir una prueba local."""
        fresh = MockERPState()
        with self._lock:
            self.warehouses = fresh.warehouses
            self.products = fresh.products
            self.customers = fresh.customers
            self.suppliers = fresh.suppliers
            self.orders = fresh.orders
            self.delivery_notes = fresh.delivery_notes
            self.imported_delivery_notes = fresh.imported_delivery_notes
            self.imported_invoices = fresh.imported_invoices
            self.imported_orders = fresh.imported_orders
            self.imported_packing_lists = fresh.imported_packing_lists
            self.imported_transport_documents = fresh.imported_transport_documents

    def get_product(self, sku: str) -> dict[str, object] | None:
        return next((item for item in self.list_products() if item["sku"] == sku), None)

    def get_supplier(self, supplier_id: str) -> dict[str, object] | None:
        with self._lock:
            supplier = next((item for item in self.suppliers if item["id"] == supplier_id), None)
            return copy.deepcopy(supplier) if supplier else None

    def list_delivery_notes(self, status: str = "") -> list[dict[str, object]]:
        with self._lock:
            return [
                copy.deepcopy(note)
                for note in self.delivery_notes
                if not status or note["status"] == status
            ]

    def get_delivery_note(self, note_id: str) -> dict[str, object] | None:
        with self._lock:
            note = next((item for item in self.delivery_notes if item["id"] == note_id), None)
            return copy.deepcopy(note) if note else None

    def create_delivery_note(self, payload: dict[str, object]) -> dict[str, object]:
        order_id = str(payload.get("order_id", "")).strip()
        with self._lock:
            order = next((item for item in self.orders if item["id"] == order_id), None) if order_id else None
            if order_id and order is None:
                raise KeyError(f"pedido no encontrado: {order_id}")

            customer_id = str(payload.get("customer_id") or (order or {}).get("customer_id", "")).strip()
            warehouse_id = str(payload.get("warehouse_id") or (order or {}).get("warehouse_id", "")).strip()
            lines = payload.get("lines") or (order or {}).get("lines")
            if not customer_id or not warehouse_id or not isinstance(lines, list) or not lines:
                raise ValueError("customer_id, warehouse_id y lines son obligatorios")
            if not any(customer["id"] == customer_id for customer in self.customers):
                raise KeyError(f"cliente no encontrado: {customer_id}")
            if not any(warehouse["id"] == warehouse_id for warehouse in self.warehouses):
                raise KeyError(f"almacén no encontrado: {warehouse_id}")

            normalized_lines = []
            for line in lines:
                if not isinstance(line, dict):
                    raise ValueError("cada línea del albarán debe ser un objeto")
                sku = str(line.get("sku", "")).strip()
                quantity = line.get("quantity")
                product = self.get_product(sku)
                if product is None:
                    raise KeyError(f"producto no encontrado: {sku}")
                if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
                    raise ValueError("la cantidad de cada línea debe ser un entero positivo")
                normalized_lines.append(
                    {"sku": sku, "name": product["name"], "quantity": quantity, "unit": product["unit"]}
                )

            used_numbers = [int(str(item["id"]).split("-")[1]) for item in self.delivery_notes]
            next_number = max(used_numbers or [1000]) + 1
            note = {
                "id": f"ALB-{next_number:04d}",
                "order_id": order_id or None,
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "status": "draft",
                "lines": normalized_lines,
                "created_at": _now(),
                "confirmed_at": None,
                "delivered_at": None,
            }
            self.delivery_notes.append(note)
            return copy.deepcopy(note)

    def transition_delivery_note(self, note_id: str, action: str) -> dict[str, object]:
        transitions = {
            "confirm": {"from": "draft", "to": "confirmed", "field": "confirmed_at"},
            "deliver": {"from": "confirmed", "to": "delivered", "field": "delivered_at"},
            "cancel": {"from": {"draft", "confirmed"}, "to": "cancelled", "field": None},
        }
        transition = transitions.get(action)
        if transition is None:
            raise ValueError(f"acción no soportada: {action}")
        with self._lock:
            note = next((item for item in self.delivery_notes if item["id"] == note_id), None)
            if note is None:
                raise KeyError(f"albarán no encontrado: {note_id}")
            allowed_from = transition["from"]
            current_status = note["status"]
            if current_status not in (allowed_from if isinstance(allowed_from, set) else {allowed_from}):
                raise ValueError(f"no se puede ejecutar {action} desde estado {current_status}")
            note["status"] = transition["to"]
            if transition["field"]:
                note[transition["field"]] = _now()
            if note["order_id"]:
                order = next((item for item in self.orders if item["id"] == note["order_id"]), None)
                if order is not None and transition["to"] == "delivered":
                    order["status"] = "delivered"
            return copy.deepcopy(note)

    def import_delivery_note(self, payload: dict[str, object]) -> dict[str, object]:
        """Registra en el ERP un albarán que ya fue validado por el pipeline."""
        client_id = str(payload.get("client_id", "")).strip()
        document_number = str(payload.get("document_number", "")).strip()
        if not client_id or not document_number:
            raise ValueError("client_id y document_number son obligatorios")
        if not any(item["id"] == client_id for item in [*self.customers, *self.suppliers]):
            raise KeyError(f"cliente no encontrado: {client_id}")
        with self._lock:
            imported = {
                "id": f"ERP-ALB-{1000 + len(self.imported_delivery_notes) + 1:04d}",
                "document_number": document_number,
                "client_id": client_id,
                "status": "received",
                "source_object_key": payload.get("source_object_key"),
                "lines": copy.deepcopy(payload.get("lines", [])),
                "received_at": _now(),
            }
            self.imported_delivery_notes.append(imported)
            return copy.deepcopy(imported)

    def import_invoice(self, payload: dict[str, object]) -> dict[str, object]:
        """Registra en el ERP una factura validada por el pipeline."""
        client_id = str(payload.get("client_id", "")).strip()
        document_number = str(payload.get("document_number", "")).strip()
        if not client_id or not document_number:
            raise ValueError("client_id y document_number son obligatorios")
        if not any(item["id"] == client_id for item in [*self.customers, *self.suppliers]):
            raise KeyError(f"cliente no encontrado: {client_id}")
        with self._lock:
            imported = {
                "id": f"ERP-FAC-{1000 + len(self.imported_invoices) + 1:04d}",
                "document_number": document_number,
                "client_id": client_id,
                "status": "received",
                "source_object_key": payload.get("source_object_key"),
                "lines": copy.deepcopy(payload.get("lines", [])),
                "received_at": _now(),
            }
            self.imported_invoices.append(imported)
            return copy.deepcopy(imported)

    def _import_logistics_document(
        self,
        payload: dict[str, object],
        collection: list[dict[str, object]],
        prefix: str,
        document_type: str,
    ) -> dict[str, object]:
        client_id = str(payload.get("client_id", "")).strip()
        document_number = str(payload.get("document_number", "")).strip()
        if not client_id or not document_number:
            raise ValueError("client_id y document_number son obligatorios")
        if not any(item["id"] == client_id for item in [*self.customers, *self.suppliers]):
            raise KeyError(f"cliente no encontrado: {client_id}")
        with self._lock:
            imported = {
                "id": f"{prefix}{1000 + len(collection) + 1:04d}",
                "document_type": document_type,
                "document_number": document_number,
                "client_id": client_id,
                "document_direction": payload.get("document_direction", "unknown"),
                "order_kind": payload.get("order_kind", "unknown"),
                "details": copy.deepcopy(payload.get("details", {})),
                "status": "received",
                "source_object_key": payload.get("source_object_key"),
                "lines": copy.deepcopy(payload.get("lines", [])),
                "received_at": _now(),
            }
            collection.append(imported)
            return copy.deepcopy(imported)

    def import_order(self, payload: dict[str, object]) -> dict[str, object]:
        return self._import_logistics_document(payload, self.imported_orders, "ERP-PED-", "order")

    def import_packing_list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._import_logistics_document(payload, self.imported_packing_lists, "ERP-PCK-", "packing_list")

    def import_transport_document(self, payload: dict[str, object]) -> dict[str, object]:
        return self._import_logistics_document(payload, self.imported_transport_documents, "ERP-TRP-", "transport_document")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "warehouses": copy.deepcopy(self.warehouses),
                "products": self.list_products(),
                "customers": copy.deepcopy(self.customers),
                "suppliers": copy.deepcopy(self.suppliers),
                "orders": copy.deepcopy(self.orders),
                "delivery_notes": copy.deepcopy(self.delivery_notes),
                "imported_delivery_notes": copy.deepcopy(self.imported_delivery_notes),
                "imported_invoices": copy.deepcopy(self.imported_invoices),
                "imported_orders": copy.deepcopy(self.imported_orders),
                "imported_packing_lists": copy.deepcopy(self.imported_packing_lists),
                "imported_transport_documents": copy.deepcopy(self.imported_transport_documents),
            }


def create_server(host: str = "127.0.0.1", port: int = 9000, state: MockERPState | None = None):
    erp = state or MockERPState()

    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            query = parse_qs(parsed.query)
            if path == "":
                self._send(
                    HTTPStatus.OK,
                    {
                        "service": "mock-erp",
                        "status": "ok",
                        "mode": "local",
                        "health": "/health",
                        "docs": "/docs",
                        "openapi": "/openapi.json",
                        "api": "/api/v1/snapshot",
                    },
                )
            elif path == "/docs":
                self._send_text(HTTPStatus.OK, swagger_html(), "text/html; charset=utf-8")
            elif path == "/openapi.json":
                self._send_text(HTTPStatus.OK, openapi_json(), "application/json; charset=utf-8")
            elif path == "/health":
                self._send(HTTPStatus.OK, {"status": "ok", "service": "mock-erp", "mode": "local"})
            elif path == "/api/v1/products":
                self._send(HTTPStatus.OK, {"data": erp.list_products(query.get("q", [""])[0])})
            elif path.startswith("/api/v1/products/"):
                product = erp.get_product(unquote(path.removeprefix("/api/v1/products/")))
                self._send(HTTPStatus.OK if product else HTTPStatus.NOT_FOUND, product or {"error": "producto no encontrado"})
            elif path == "/api/v1/warehouses":
                self._send(HTTPStatus.OK, {"data": copy.deepcopy(erp.warehouses)})
            elif path == "/api/v1/customers":
                term = query.get("q", [""])[0].strip().lower()
                customers = [
                    customer for customer in erp.customers
                    if not term or term in customer["id"].lower() or term in customer["name"].lower()
                ]
                self._send(HTTPStatus.OK, {"data": copy.deepcopy(customers)})
            elif path.startswith("/api/v1/customers/"):
                customer_id = unquote(path.removeprefix("/api/v1/customers/"))
                customer = next((item for item in erp.customers if item["id"] == customer_id), None)
                self._send(HTTPStatus.OK if customer else HTTPStatus.NOT_FOUND, copy.deepcopy(customer) if customer else {"error": "cliente no encontrado"})
            elif path == "/api/v1/suppliers":
                term = query.get("q", [""])[0].strip().lower()
                suppliers = [
                    supplier for supplier in erp.suppliers
                    if not term or term in supplier["id"].lower() or term in supplier["name"].lower()
                ]
                self._send(HTTPStatus.OK, {"data": copy.deepcopy(suppliers)})
            elif path.startswith("/api/v1/suppliers/"):
                supplier_id = unquote(path.removeprefix("/api/v1/suppliers/"))
                supplier = erp.get_supplier(supplier_id)
                self._send(HTTPStatus.OK if supplier else HTTPStatus.NOT_FOUND, supplier or {"error": "proveedor no encontrado"})
            elif path == "/api/v1/delivery-notes":
                self._send(HTTPStatus.OK, {"data": erp.list_delivery_notes(query.get("status", [""])[0])})
            elif path.startswith("/api/v1/delivery-notes/"):
                note = erp.get_delivery_note(unquote(path.removeprefix("/api/v1/delivery-notes/")))
                self._send(HTTPStatus.OK if note else HTTPStatus.NOT_FOUND, note or {"error": "albarán no encontrado"})
            elif path == "/api/v1/orders":
                self._send(HTTPStatus.OK, {"data": copy.deepcopy(erp.orders)})
            elif path.startswith("/api/v1/orders/"):
                order_id = unquote(path.removeprefix("/api/v1/orders/"))
                order = next((item for item in erp.orders if item["id"] == order_id), None)
                self._send(HTTPStatus.OK if order else HTTPStatus.NOT_FOUND, copy.deepcopy(order) if order else {"error": "pedido no encontrado"})
            elif path == "/api/v1/snapshot":
                self._send(HTTPStatus.OK, erp.snapshot())
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "ruta no encontrada"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/")
            try:
                payload = self._read_json()
                if path == "/api/v1/delivery-notes":
                    self._send(HTTPStatus.CREATED, erp.create_delivery_note(payload))
                    return
                if path == "/api/v1/test/reset":
                    erp.reset()
                    self._send(HTTPStatus.OK, {"status": "reset", "mode": "local-test"})
                    return
                if path == "/api/v1/delivery-notes/import":
                    self._send(HTTPStatus.CREATED, erp.import_delivery_note(payload))
                    return
                if path == "/api/v1/invoices/import":
                    self._send(HTTPStatus.CREATED, erp.import_invoice(payload))
                    return
                if path == "/api/v1/orders/import":
                    self._send(HTTPStatus.CREATED, erp.import_order(payload))
                    return
                if path == "/api/v1/packing-lists/import":
                    self._send(HTTPStatus.CREATED, erp.import_packing_list(payload))
                    return
                if path == "/api/v1/transport-documents/import":
                    self._send(HTTPStatus.CREATED, erp.import_transport_document(payload))
                    return
                if path.startswith("/api/v1/orders/") and path.endswith("/delivery-note"):
                    order_id = unquote(path.removeprefix("/api/v1/orders/").removesuffix("/delivery-note")).strip("/")
                    payload["order_id"] = order_id
                    self._send(HTTPStatus.CREATED, erp.create_delivery_note(payload))
                    return
                if path.startswith("/api/v1/delivery-notes/"):
                    suffix = path.removeprefix("/api/v1/delivery-notes/")
                    note_id, separator, action = suffix.rpartition("/")
                    if separator and action in {"confirm", "deliver", "cancel"}:
                        self._send(HTTPStatus.OK, erp.transition_delivery_note(unquote(note_id), action))
                        return
                self._send(HTTPStatus.NOT_FOUND, {"error": "ruta no encontrada"})
                return
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            except KeyError as error:
                self._send(HTTPStatus.NOT_FOUND, {"error": str(error).strip("'")})
                return

        def log_message(self, *_args) -> None:
            return

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("el cuerpo debe ser un objeto JSON")
            return value

        def _send(self, status: HTTPStatus, body: object) -> None:
            self._send_text(status, json.dumps(body, ensure_ascii=False), "application/json; charset=utf-8")

        def _send_text(self, status: HTTPStatus, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type")

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host = os.getenv("MOCK_ERP_HOST", "127.0.0.1")
    port = int(os.getenv("MOCK_ERP_PORT", "9000"))
    server = create_server(host, port)
    print(f"Mock ERP local en http://{host}:{port}")
    print("Datos semilla cargados. Ctrl+C para detenerlo")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
