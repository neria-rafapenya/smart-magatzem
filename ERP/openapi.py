"""Contrato OpenAPI y página Swagger UI del mock ERP local."""

from __future__ import annotations

import json


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "Smart Magatzem - Mock ERP",
        "version": "0.1.0",
        "description": "Sandbox local para probar el flujo pedido → albarán → packing list → transporte → factura.",
    },
    "servers": [{"url": "http://127.0.0.1:9000", "description": "Mock ERP local"}],
    "tags": [
        {"name": "Albaranes", "description": "Ciclo de vida de los albaranes"},
        {"name": "Facturas", "description": "Recepción de facturas validadas por el pipeline"},
        {"name": "Logística", "description": "Pedidos, packing lists y documentos de transporte validados por el pipeline"},
    ],
    "paths": {
        "/health": {
            "get": {"summary": "Estado del mock ERP", "responses": {"200": {"description": "Servicio disponible"}}}
        },
        "/api/v1/products": {
            "get": {
                "summary": "Listar productos",
                "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Productos disponibles"}},
            }
        },
        "/api/v1/customers": {
            "get": {
                "summary": "Listar clientes",
                "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Clientes disponibles"}},
            }
        },
        "/api/v1/customers/{id}": {
            "get": {
                "summary": "Consultar un cliente",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string", "example": "CLI-001"}}],
                "responses": {"200": {"description": "Cliente"}, "404": {"$ref": "#/components/responses/NotFound"}},
            }
        },
        "/api/v1/suppliers": {
            "get": {
                "summary": "Listar proveedores",
                "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Proveedores disponibles"}},
            }
        },
        "/api/v1/suppliers/{id}": {
            "get": {
                "summary": "Consultar un proveedor",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string", "example": "SUP-001"}}],
                "responses": {"200": {"description": "Proveedor"}, "404": {"$ref": "#/components/responses/NotFound"}},
            }
        },
        "/api/v1/warehouses": {
            "get": {"summary": "Listar almacenes", "responses": {"200": {"description": "Almacenes disponibles"}}}
        },
        "/api/v1/orders": {
            "get": {"summary": "Listar pedidos", "responses": {"200": {"description": "Pedidos disponibles"}}}
        },
        "/api/v1/delivery-notes": {
            "get": {
                "tags": ["Albaranes"],
                "summary": "Listar albaranes",
                "parameters": [{"name": "status", "in": "query", "schema": {"$ref": "#/components/schemas/DeliveryNoteStatus"}}],
                "responses": {"200": {"description": "Albaranes disponibles"}},
            },
            "post": {
                "tags": ["Albaranes"],
                "summary": "Crear un albarán",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/DeliveryNoteCreate"}}}},
                "responses": {"201": {"description": "Albarán creado"}, "400": {"$ref": "#/components/responses/BadRequest"}},
            },
        },
        "/api/v1/delivery-notes/{id}": {
            "get": {
                "tags": ["Albaranes"],
                "summary": "Consultar un albarán",
                "parameters": [{"$ref": "#/components/parameters/DeliveryNoteId"}],
                "responses": {"200": {"description": "Albarán"}, "404": {"$ref": "#/components/responses/NotFound"}},
            }
        },
        "/api/v1/orders/{id}/delivery-note": {
            "post": {
                "tags": ["Albaranes"],
                "summary": "Crear albarán desde un pedido",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string", "example": "PED-1001"}}],
                "responses": {"201": {"description": "Albarán creado desde el pedido"}, "404": {"$ref": "#/components/responses/NotFound"}},
            }
        },
        "/api/v1/delivery-notes/{id}/confirm": {
            "post": {"tags": ["Albaranes"], "summary": "Confirmar albarán", "parameters": [{"$ref": "#/components/parameters/DeliveryNoteId"}], "responses": {"200": {"description": "Albarán confirmado"}, "400": {"$ref": "#/components/responses/BadRequest"}}}
        },
        "/api/v1/delivery-notes/{id}/deliver": {
            "post": {"tags": ["Albaranes"], "summary": "Marcar albarán como entregado", "parameters": [{"$ref": "#/components/parameters/DeliveryNoteId"}], "responses": {"200": {"description": "Albarán entregado"}, "400": {"$ref": "#/components/responses/BadRequest"}}}
        },
        "/api/v1/delivery-notes/{id}/cancel": {
            "post": {"tags": ["Albaranes"], "summary": "Cancelar albarán", "parameters": [{"$ref": "#/components/parameters/DeliveryNoteId"}], "responses": {"200": {"description": "Albarán cancelado"}, "400": {"$ref": "#/components/responses/BadRequest"}}}
        },
        "/api/v1/delivery-notes/import": {
            "post": {
                "summary": "Registrar un albarán validado por el pipeline",
                "description": "Endpoint que representa la entrada final al ERP después del OCR y las reglas.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ImportedDeliveryNote"}}}},
                "responses": {"201": {"description": "Albarán recibido por el ERP"}, "400": {"$ref": "#/components/responses/BadRequest"}},
            }
        },
        "/api/v1/invoices/import": {
            "post": {
                "tags": ["Facturas"],
                "summary": "Registrar una factura validada por el pipeline",
                "description": "Endpoint del ERP mock para recibir facturas después del OCR y las reglas.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ImportedInvoice"}}}},
                "responses": {"201": {"description": "Factura recibida por el ERP"}, "400": {"$ref": "#/components/responses/BadRequest"}},
            }
        },
        "/api/v1/orders/import": {
            "post": {
                "tags": ["Logística"],
                "summary": "Registrar un pedido validado por el pipeline",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ImportedLogisticsDocument"}}}},
                "responses": {"201": {"description": "Pedido recibido por el ERP"}, "400": {"$ref": "#/components/responses/BadRequest"}},
            }
        },
        "/api/v1/packing-lists/import": {
            "post": {
                "tags": ["Logística"],
                "summary": "Registrar un packing list validado por el pipeline",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ImportedLogisticsDocument"}}}},
                "responses": {"201": {"description": "Packing list recibido por el ERP"}, "400": {"$ref": "#/components/responses/BadRequest"}},
            }
        },
        "/api/v1/transport-documents/import": {
            "post": {
                "tags": ["Logística"],
                "summary": "Registrar un documento de transporte validado por el pipeline",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ImportedLogisticsDocument"}}}},
                "responses": {"201": {"description": "Documento de transporte recibido por el ERP"}, "400": {"$ref": "#/components/responses/BadRequest"}},
            }
        },
        "/api/v1/snapshot": {
            "get": {"summary": "Ver el estado completo del mock", "responses": {"200": {"description": "Snapshot del ERP"}}}
        },
        "/api/v1/test/reset": {
            "post": {
                "summary": "Restablecer datos semilla (solo pruebas locales)",
                "description": "Endpoint exclusivo del mock local para repetir escenarios desde cero.",
                "responses": {"200": {"description": "Datos restablecidos"}},
            }
        },
    },
    "components": {
        "parameters": {
            "DeliveryNoteId": {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "example": "ALB-1001"}}
        },
        "responses": {
            "BadRequest": {"description": "Solicitud no válida"},
            "NotFound": {"description": "Recurso no encontrado"},
        },
        "schemas": {
            "DeliveryNoteStatus": {"type": "string", "enum": ["draft", "confirmed", "delivered", "cancelled"]},
            "DeliveryNoteLine": {
                "type": "object",
                "required": ["sku", "quantity"],
                "properties": {"sku": {"type": "string", "example": "SKU-002"}, "quantity": {"type": "integer", "minimum": 1, "example": 4}},
            },
            "DeliveryNoteCreate": {
                "type": "object",
                "required": ["customer_id", "warehouse_id", "lines"],
                "properties": {
                    "order_id": {"type": "string", "example": "PED-1001"},
                    "customer_id": {"type": "string", "example": "CLI-001"},
                    "warehouse_id": {"type": "string", "example": "MAG-BCN"},
                    "lines": {"type": "array", "items": {"$ref": "#/components/schemas/DeliveryNoteLine"}},
                },
            },
            "ImportedDeliveryNote": {
                "type": "object",
                "required": ["client_id", "document_number"],
                "properties": {
                    "client_id": {"type": "string", "example": "CLI-001"},
                    "document_number": {"type": "string", "example": "ALB-DEMO-001"},
                    "source_object_key": {"type": "string", "example": "incoming/INT-123/albaran.jpg"},
                    "lines": {"type": "array", "items": {"$ref": "#/components/schemas/DeliveryNoteLine"}},
                },
            },
            "ImportedInvoice": {
                "type": "object",
                "required": ["client_id", "document_number"],
                "properties": {
                    "client_id": {"type": "string", "example": "CLI-001"},
                    "document_number": {"type": "string", "example": "T125 935"},
                    "source_object_key": {"type": "string", "example": "incoming/INT-123/factura.jpg"},
                    "lines": {"type": "array", "items": {"$ref": "#/components/schemas/InvoiceLine"}},
                },
            },
            "ImportedLogisticsDocument": {
                "type": "object",
                "required": ["client_id", "document_number"],
                "properties": {
                    "client_id": {"type": "string", "example": "CLI-001"},
                    "document_number": {"type": "string", "example": "PED-2026-001"},
                    "document_direction": {"type": "string", "enum": ["inbound", "outbound", "unknown"]},
                    "order_kind": {"type": "string", "enum": ["purchase", "sales", "unknown"]},
                    "details": {"type": "object", "additionalProperties": True, "example": {"packages_count": 4, "weight_kg": 120.5}},
                    "source_object_key": {"type": "string", "example": "incoming/INT-123/documento.jpg"},
                    "lines": {"type": "array", "items": {"$ref": "#/components/schemas/InvoiceLine"}},
                },
            },
            "InvoiceLine": {
                "type": "object",
                "required": ["sku", "quantity"],
                "properties": {
                    "sku": {"type": "string", "example": "1695213980"},
                    "quantity": {"type": "number", "minimum": 0, "example": 3.5},
                },
            },
        },
    },
}


def swagger_html() -> str:
    spec_url = "/openapi.json"
    return f"""<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Smart Magatzem - Mock ERP API</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.onload = () => SwaggerUIBundle({{ url: "{spec_url}", dom_id: "#swagger-ui", deepLinking: true, presets: [SwaggerUIBundle.presets.apis], layout: "BaseLayout" }});
    </script>
  </body>
</html>"""


def openapi_json() -> str:
    return json.dumps(OPENAPI_SPEC, ensure_ascii=False)
