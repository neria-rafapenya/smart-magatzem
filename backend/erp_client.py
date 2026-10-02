"""Cliente HTTP pequeño para consumir el mock ERP local."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ERPClientError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class ERPUnavailableError(ERPClientError):
    def __init__(self, message: str = "el mock ERP no está disponible") -> None:
        super().__init__(message, 503)


class ERPClient:
    def __init__(self, base_url: str = "http://127.0.0.1:9000") -> None:
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict[str, object]:
        return self._request("GET", "/health")

    def list_delivery_notes(self, status: str = "") -> dict[str, object]:
        path = "/api/v1/delivery-notes"
        if status:
            path += f"?status={status}"
        return self._request("GET", path)

    def list_customers(self, query: str = "") -> dict[str, object]:
        path = "/api/v1/customers"
        if query:
            path += f"?q={query}"
        return self._request("GET", path)

    def get_customer(self, customer_id: str) -> dict[str, object]:
        return self._request("GET", f"/api/v1/customers/{customer_id}")

    def list_suppliers(self, query: str = "") -> dict[str, object]:
        path = "/api/v1/suppliers"
        if query:
            path += f"?q={query}"
        return self._request("GET", path)

    def get_supplier(self, supplier_id: str) -> dict[str, object]:
        return self._request("GET", f"/api/v1/suppliers/{supplier_id}")

    def get_party(self, party_id: str) -> dict[str, object]:
        if party_id.upper().startswith("SUP-"):
            return self.get_supplier(party_id)
        return self.get_customer(party_id)

    def import_delivery_note(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/v1/delivery-notes/import", payload)

    def import_invoice(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/v1/invoices/import", payload)

    def import_order(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/v1/orders/import", payload)

    def import_packing_list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/v1/packing-lists/import", payload)

    def import_transport_document(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/v1/transport-documents/import", payload)

    def get_delivery_note(self, note_id: str) -> dict[str, object]:
        return self._request("GET", f"/api/v1/delivery-notes/{note_id}")

    def get_order(self, order_id: str) -> dict[str, object]:
        return self._request("GET", f"/api/v1/orders/{order_id}")

    def create_delivery_note(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/v1/delivery-notes", payload)

    def create_delivery_note_from_order(
        self, order_id: str, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        return self._request("POST", f"/api/v1/orders/{order_id}/delivery-note", payload or {})

    def transition_delivery_note(self, note_id: str, action: str) -> dict[str, object]:
        return self._request("POST", f"/api/v1/delivery-notes/{note_id}/{action}", {})

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8"))
                message = str(detail.get("error", "error del ERP"))
            except (ValueError, json.JSONDecodeError):
                message = "error del ERP"
            raise ERPClientError(message, error.code) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ERPUnavailableError() from error
