#!/usr/bin/env python3
"""Create coherent local PDF fixtures for the Smart Magatzem document flow."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output" / "pdf"
PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
BLUE = colors.HexColor("#1f4e79")
LIGHT_BLUE = colors.HexColor("#eaf2f8")
GRID = colors.HexColor("#b7c4d1")
TEXT = colors.HexColor("#243447")
MUTED = colors.HexColor("#5b6b7a")
GREEN = colors.HexColor("#e8f5e9")

STYLES = getSampleStyleSheet()
CELL = ParagraphStyle(
    "Cell",
    parent=STYLES["Normal"],
    fontName="Helvetica",
    fontSize=8.5,
    leading=10,
    textColor=TEXT,
    spaceAfter=0,
)
CELL_SMALL = ParagraphStyle("CellSmall", parent=CELL, fontSize=7.5, leading=8.5)
CELL_BOLD = ParagraphStyle("CellBold", parent=CELL, fontName="Helvetica-Bold")
CELL_CENTER = ParagraphStyle("CellCenter", parent=CELL, alignment=TA_CENTER)
CELL_RIGHT = ParagraphStyle("CellRight", parent=CELL, alignment=TA_RIGHT)


def p(value: object, style: ParagraphStyle = CELL) -> Paragraph:
    return Paragraph(str(value).replace("&", "&amp;"), style)


def money(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


def draw_header(c: canvas.Canvas, title: str, document_number: str, subtitle: str) -> None:
    c.setFillColor(BLUE)
    c.rect(0, PAGE_H - 29 * mm, PAGE_W, 29 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, PAGE_H - 12 * mm, "SMART MAGATZEM, S.L.")
    c.setFont("Helvetica", 8.5)
    c.drawString(MARGIN, PAGE_H - 19 * mm, "CIF B90000001 | Carrer de la Industria, 42 | 08018 Barcelona")
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 11 * mm, title.upper())
    c.setFont("Helvetica", 9)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 18 * mm, document_number)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN, PAGE_H - 35 * mm, subtitle)


def draw_footer(c: canvas.Canvas, filename: str) -> None:
    c.setStrokeColor(GRID)
    c.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawString(MARGIN, 8 * mm, "Plantilla de prueba local - Smart Magatzem")
    c.drawRightString(PAGE_W - MARGIN, 8 * mm, filename)


def draw_box(c: canvas.Canvas, x: float, y: float, w: float, h: float, title: str) -> None:
    c.setStrokeColor(GRID)
    c.setFillColor(colors.white)
    c.roundRect(x, y, w, h, 2 * mm, fill=1, stroke=1)
    c.setFillColor(LIGHT_BLUE)
    c.rect(x, y + h - 8 * mm, w, 8 * mm, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x + 4 * mm, y + h - 5.4 * mm, title.upper())


def draw_fields(c: canvas.Canvas, x: float, y: float, fields: list[tuple[str, str]], line_gap: float = 5.7 * mm) -> None:
    for label, value in fields:
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 7.3)
        c.drawString(x, y, label.upper())
        c.setFillColor(TEXT)
        c.setFont("Helvetica", 8.3)
        c.drawString(x + 32 * mm, y, value)
        y -= line_gap


def draw_table(
    c: canvas.Canvas,
    x: float,
    top: float,
    widths: list[float],
    headers: list[str],
    rows: list[list[object]],
    small: bool = False,
    row_heights: list[float] | None = None,
) -> float:
    style = CELL_SMALL if small else CELL
    data = [[p(header, CELL_BOLD) for header in headers]]
    for row in rows:
        data.append([value if isinstance(value, Paragraph) else p(value, style) for value in row])
    table = Table(data, colWidths=widths, rowHeights=row_heights, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), BLUE),
                ("GRID", (0, 0), (-1, -1), 0.45, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
            ]
        )
    )
    _, height = table.wrapOn(c, PAGE_W, PAGE_H)
    table.drawOn(c, x, top - height)
    return top - height


def draw_signature_boxes(c: canvas.Canvas, y: float, left_title: str = "EMISOR", right_title: str = "RECEPTOR") -> None:
    gap = 8 * mm
    w = (PAGE_W - 2 * MARGIN - gap) / 2
    for x, title in ((MARGIN, left_title), (MARGIN + w + gap, right_title)):
        draw_box(c, x, y, w, 29 * mm, title)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.5)
        c.drawString(x + 4 * mm, y + 6 * mm, "Firma y sello")


def finish(c: canvas.Canvas, filename: str) -> None:
    draw_footer(c, filename)
    c.showPage()
    c.save()


def create_order() -> Path:
    filename = "01-pedido-venta-PED-2026-0042.pdf"
    path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    draw_header(c, "Pedido de venta", "PED-2026-0042", "Documento comercial: condiciones acordadas antes de la entrega")
    y = PAGE_H - 48 * mm
    gap = 7 * mm
    w = (PAGE_W - 2 * MARGIN - gap) / 2
    draw_box(c, MARGIN, y - 37 * mm, w, 37 * mm, "Pedido")
    draw_fields(c, MARGIN + 4 * mm, y - 14 * mm, [("Fecha", "29/09/2026"), ("Entrega prevista", "02/10/2026"), ("Moneda", "EUR"), ("Estado", "Confirmado")])
    draw_box(c, MARGIN + w + gap, y - 37 * mm, w, 37 * mm, "Cliente")
    draw_fields(c, MARGIN + w + gap + 4 * mm, y - 14 * mm, [("Nombre", "Ferreteria Neria, S.L."), ("CIF", "B12345678"), ("Codigo", "CLI-001"), ("Direccion", "Carrer Major, 18 - 17001 Girona")])
    top = y - 48 * mm
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top, "LINEAS DEL PEDIDO")
    top -= 5 * mm
    rows = [
        ["SKU-001", "Tornillo galvanizado M8", "100", "1,20", money(120.0)],
        ["SKU-002", "Tuerca hexagonal M8", "100", "0,80", money(80.0)],
        ["SKU-003", "Arandela plana M8", "100", "0,30", money(30.0)],
    ]
    draw_table(c, MARGIN, top, [28 * mm, 70 * mm, 22 * mm, 27 * mm, 35 * mm], ["SKU", "Descripcion", "Cantidad", "Precio", "Importe"], rows)
    draw_box(c, MARGIN, 50 * mm, PAGE_W - 2 * MARGIN, 25 * mm, "Condiciones")
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 8.5)
    c.drawString(MARGIN + 4 * mm, 64 * mm, "Entrega en la direccion del cliente. Pedido asociado al flujo de expedicion OUTBOUND.")
    c.drawString(MARGIN + 4 * mm, 57 * mm, "Observaciones: incluir identificacion de bultos y documento de transporte.")
    draw_signature_boxes(c, 17 * mm, "CLIENTE", "SMART MAGATZEM")
    finish(c, filename)
    return path


def create_neria_order(filename: str, document_number: str, direction: str, order_kind: str, title: str, date: str, delivery_date: str) -> Path:
    path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    draw_header(c, title, document_number, "Pedido de prueba para validar la direccion de entrada o salida")
    y = PAGE_H - 48 * mm
    gap = 7 * mm
    w = (PAGE_W - 2 * MARGIN - gap) / 2
    draw_box(c, MARGIN, y - 37 * mm, w, 37 * mm, "Pedido")
    draw_fields(c, MARGIN + 4 * mm, y - 14 * mm, [
        ("Tipo", order_kind),
        ("Fecha", date),
        ("Entrega", delivery_date),
        ("Direccion", direction),
    ])
    draw_box(c, MARGIN + w + gap, y - 37 * mm, w, 37 * mm, "Ferreteria Neria")
    draw_fields(c, MARGIN + w + gap + 4 * mm, y - 14 * mm, [
        ("Nombre", "Ferreteria Neria, S.L."),
        ("CIF", "B12345678"),
        ("Codigo", "CLI-001"),
        ("Direccion", "Carrer Major, 18 - 17001 Girona"),
    ])
    top = y - 48 * mm
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top, "LINEAS DEL PEDIDO")
    top -= 5 * mm
    rows = [
        ["SKU-001", "Tornillo galvanizado M8", "50", "1,20", money(60.0)],
        ["SKU-002", "Tuerca hexagonal M8", "50", "0,80", money(40.0)],
        ["SKU-003", "Arandela plana M8", "50", "0,30", money(15.0)],
    ]
    draw_table(c, MARGIN, top, [28 * mm, 70 * mm, 22 * mm, 27 * mm, 35 * mm], ["SKU", "Descripcion", "Cantidad", "Precio", "Importe"], rows)
    draw_box(c, MARGIN, 50 * mm, PAGE_W - 2 * MARGIN, 25 * mm, "Reglas del pedido")
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 8.5)
    if direction == "ENTRADA":
        c.drawString(MARGIN + 4 * mm, 64 * mm, "PEDIDO DE COMPRA - PROVEEDOR: Ferreteria Neria - recepcion en Smart Magatzem.")
        c.drawString(MARGIN + 4 * mm, 57 * mm, "La mercancia se recibe en el almacen y queda pendiente de validacion de entrada.")
    else:
        c.drawString(MARGIN + 4 * mm, 64 * mm, "PEDIDO DE VENTA - CLIENTE: Ferreteria Neria - expedicion desde Smart Magatzem.")
        c.drawString(MARGIN + 4 * mm, 57 * mm, "La mercancia se prepara para salida y entrega en la direccion del cliente.")
    draw_signature_boxes(c, 17 * mm, "CLIENTE / PROVEEDOR", "SMART MAGATZEM")
    finish(c, filename)
    return path


def create_blank_order_template() -> Path:
    filename = "08-plantilla-pedido-en-blanco.pdf"
    path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    draw_header(c, "Plantilla de pedido", "PED-____________", "Plantilla en blanco para rellenar a mano")
    header_box_x = PAGE_W - MARGIN - 58 * mm
    header_box_y = PAGE_H - 24 * mm
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.white)
    c.roundRect(header_box_x, header_box_y, 58 * mm, 9 * mm, 1.5 * mm, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(header_box_x + 4 * mm, header_box_y + 3.1 * mm, "PED:")
    c.setStrokeColor(GRID)
    c.line(header_box_x + 16 * mm, header_box_y + 3 * mm, header_box_x + 54 * mm, header_box_y + 3 * mm)
    y = PAGE_H - 48 * mm
    gap = 7 * mm
    w = (PAGE_W - 2 * MARGIN - gap) / 2

    draw_box(c, MARGIN, y - 43 * mm, w, 43 * mm, "Datos del pedido")
    field_y = y - 14 * mm
    for label in ("Numero", "Fecha", "Entrega prevista"):
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 7.3)
        c.drawString(MARGIN + 4 * mm, field_y, label.upper())
        c.setStrokeColor(GRID)
        c.line(MARGIN + 34 * mm, field_y - 1 * mm, MARGIN + w - 4 * mm, field_y - 1 * mm)
        field_y -= 7 * mm
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 7.3)
    c.drawString(MARGIN + 4 * mm, field_y, "DIRECCION")
    for index, label in enumerate(("Entrada", "Salida")):
        box_x = MARGIN + 34 * mm + index * 25 * mm
        c.setStrokeColor(GRID)
        c.rect(box_x, field_y - 3 * mm, 4 * mm, 4 * mm, fill=0, stroke=1)
        c.setFillColor(TEXT)
        c.setFont("Helvetica", 8.3)
        c.drawString(box_x + 6 * mm, field_y - 0.5 * mm, label)

    right_x = MARGIN + w + gap
    draw_box(c, right_x, y - 43 * mm, w, 43 * mm, "Cliente / proveedor")
    field_y = y - 14 * mm
    for label in ("Nombre", "ID / CIF", "Email", "Direccion"):
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Bold", 7.3)
        c.drawString(right_x + 4 * mm, field_y, label.upper())
        c.setStrokeColor(GRID)
        c.line(right_x + 32 * mm, field_y - 1 * mm, right_x + w - 4 * mm, field_y - 1 * mm)
        field_y -= 7 * mm

    top = y - 54 * mm
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top, "LINEAS DEL PEDIDO")
    top -= 5 * mm
    rows = [["", "", "", "", ""] for _ in range(7)]
    draw_table(
        c,
        MARGIN,
        top,
        [27 * mm, 74 * mm, 22 * mm, 25 * mm, 34 * mm],
        ["SKU", "Descripcion", "Cantidad", "Unidad", "Observaciones"],
        rows,
        row_heights=[10 * mm] + [14 * mm] * 7,
    )

    draw_box(c, MARGIN, 51 * mm, PAGE_W - 2 * MARGIN, 25 * mm, "Observaciones y condiciones")
    for line_y in (65 * mm, 58 * mm):
        c.setStrokeColor(GRID)
        c.line(MARGIN + 4 * mm, line_y, PAGE_W - MARGIN - 4 * mm, line_y)
    draw_signature_boxes(c, 17 * mm, "CLIENTE / PROVEEDOR", "SMART MAGATZEM")
    finish(c, filename)
    return path


def create_delivery_note() -> Path:
    filename = "02-albaran-salida-ALB-2026-0042.pdf"
    path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    draw_header(c, "Albaran de salida", "ALB-2026-0042", "Documento logistico: mercancia entregada realmente")
    y = PAGE_H - 48 * mm
    gap = 7 * mm
    w = (PAGE_W - 2 * MARGIN - gap) / 2
    draw_box(c, MARGIN, y - 37 * mm, w, 37 * mm, "Expedicion")
    draw_fields(c, MARGIN + 4 * mm, y - 14 * mm, [("Pedido", "PED-2026-0042"), ("Fecha", "02/10/2026"), ("Direccion", "SALIDA"), ("Lote", "LOT-2026-09-A")])
    draw_box(c, MARGIN + w + gap, y - 37 * mm, w, 37 * mm, "Receptor")
    draw_fields(c, MARGIN + w + gap + 4 * mm, y - 14 * mm, [("Cliente", "Ferreteria Neria, S.L."), ("Codigo", "CLI-001"), ("CIF", "B12345678"), ("Entrega", "Carrer Major, 18 - Girona")])
    top = y - 48 * mm
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top, "MERCANCIA ENTREGADA")
    top -= 5 * mm
    rows = [
        ["SKU-001", "Tornillo galvanizado M8", "100", "LOT-2026-09-A", "Completo"],
        ["SKU-002", "Tuerca hexagonal M8", "100", "LOT-2026-09-A", "Completo"],
        ["SKU-003", "Arandela plana M8", "100", "LOT-2026-09-A", "Completo"],
    ]
    draw_table(c, MARGIN, top, [28 * mm, 66 * mm, 24 * mm, 38 * mm, 30 * mm], ["SKU", "Descripcion", "Cantidad", "Lote", "Estado"], rows)
    draw_box(c, MARGIN, 54 * mm, PAGE_W - 2 * MARGIN, 22 * mm, "Conformidad")
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 8.5)
    c.drawString(MARGIN + 4 * mm, 67 * mm, "El receptor confirma la entrega de las cantidades indicadas.")
    c.drawString(MARGIN + 4 * mm, 60 * mm, "Referencia de transporte: CMR-2026-0042. Packing list: PCK-2026-0042.")
    draw_signature_boxes(c, 19 * mm, "EMISOR", "RECEPTOR")
    finish(c, filename)
    return path


def create_packing_list() -> Path:
    filename = "03-packing-list-PCK-2026-0042.pdf"
    path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    draw_header(c, "Packing list", "PCK-2026-0042", "Lista de bultos: agrupacion fisica, peso y dimensiones")
    y = PAGE_H - 48 * mm
    gap = 7 * mm
    w = (PAGE_W - 2 * MARGIN - gap) / 2
    draw_box(c, MARGIN, y - 37 * mm, w, 37 * mm, "Referencia")
    draw_fields(c, MARGIN + 4 * mm, y - 14 * mm, [("Pedido", "PED-2026-0042"), ("Albaran", "ALB-2026-0042"), ("Bultos", "2 cajas"), ("Direccion", "SALIDA")])
    draw_box(c, MARGIN + w + gap, y - 37 * mm, w, 37 * mm, "Totales fisicos")
    draw_fields(c, MARGIN + w + gap + 4 * mm, y - 14 * mm, [("Peso neto", "35,0 kg"), ("Peso bruto", "38,5 kg"), ("Dimensiones", "60 x 40 x 35 cm"), ("Palets", "0")])
    top = y - 48 * mm
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top, "DETALLE DE BULTOS")
    top -= 5 * mm
    rows = [
        ["BUL-01", "Caja de carton", "SKU-001 x 100\nSKU-002 x 100", "19,0 kg", "60 x 40 x 35 cm"],
        ["BUL-02", "Caja de carton", "SKU-003 x 100", "19,5 kg", "60 x 40 x 35 cm"],
    ]
    draw_table(c, MARGIN, top, [25 * mm, 35 * mm, 62 * mm, 27 * mm, 35 * mm], ["Bulto", "Tipo", "Contenido", "Peso bruto", "Dimensiones"], rows)
    draw_box(c, MARGIN, 54 * mm, PAGE_W - 2 * MARGIN, 22 * mm, "Marcado")
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 8.5)
    c.drawString(MARGIN + 4 * mm, 67 * mm, "Cada bulto esta marcado con: CLI-001 / ALB-2026-0042 / BUL-01 o BUL-02.")
    c.drawString(MARGIN + 4 * mm, 60 * mm, "Mantener seco. No apilar mas de 3 cajas.")
    draw_signature_boxes(c, 19 * mm, "PREPARADO POR", "RECIBIDO POR")
    finish(c, filename)
    return path


def create_transport() -> Path:
    filename = "04-documento-transporte-CMR-2026-0042.pdf"
    path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    draw_header(c, "Documento de transporte - CMR", "CMR-2026-0042", "Orden de porte: como y cuando se mueve la mercancia")
    y = PAGE_H - 48 * mm
    gap = 7 * mm
    w = (PAGE_W - 2 * MARGIN - gap) / 2
    draw_box(c, MARGIN, y - 42 * mm, w, 42 * mm, "Origen y destino")
    draw_fields(c, MARGIN + 4 * mm, y - 14 * mm, [("Expedidor", "Smart Magatzem, S.L."), ("Origen", "Barcelona"), ("Consignatario", "Ferreteria Neria, S.L."), ("Destino", "Girona"), ("Direccion", "Carrer Major, 18")])
    draw_box(c, MARGIN + w + gap, y - 42 * mm, w, 42 * mm, "Transporte")
    draw_fields(c, MARGIN + w + gap + 4 * mm, y - 14 * mm, [("Transportista", "Transportes Soler"), ("Matricula", "1234ABC"), ("Pickup", "02/10/2026 10:00"), ("Ventana", "12:00 - 14:00"), ("Direccion", "SALIDA")])
    top = y - 53 * mm
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top, "CARGA TRANSPORTADA")
    top -= 5 * mm
    rows = [
        ["PCK-2026-0042", "2", "38,5 kg", "60 x 40 x 35 cm", "ALB-2026-0042"],
    ]
    draw_table(c, MARGIN, top, [38 * mm, 22 * mm, 28 * mm, 47 * mm, 44 * mm], ["Packing list", "Bultos", "Peso bruto", "Dimensiones", "Referencia"], rows)
    draw_box(c, MARGIN, 54 * mm, PAGE_W - 2 * MARGIN, 22 * mm, "Instrucciones")
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 8.5)
    c.drawString(MARGIN + 4 * mm, 67 * mm, "Recogida confirmada a las 10:00. Entrega dentro de la ventana horaria indicada.")
    c.drawString(MARGIN + 4 * mm, 60 * mm, "Contacto de entrega: almacen@ferreteria-neria.example")
    draw_signature_boxes(c, 19 * mm, "CARGADOR", "TRANSPORTISTA")
    finish(c, filename)
    return path


def create_invoice() -> Path:
    filename = "05-factura-FAC-2026-0042.pdf"
    path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    draw_header(c, "Factura", "FAC-2026-0042", "Documento economico asociado al pedido y la entrega")
    y = PAGE_H - 48 * mm
    gap = 7 * mm
    w = (PAGE_W - 2 * MARGIN - gap) / 2
    draw_box(c, MARGIN, y - 37 * mm, w, 37 * mm, "Factura")
    draw_fields(c, MARGIN + 4 * mm, y - 14 * mm, [("Fecha", "02/10/2026"), ("Vencimiento", "02/11/2026"), ("Pedido", "PED-2026-0042"), ("Albaran", "ALB-2026-0042")])
    draw_box(c, MARGIN + w + gap, y - 37 * mm, w, 37 * mm, "Cliente")
    draw_fields(c, MARGIN + w + gap + 4 * mm, y - 14 * mm, [("Nombre", "Ferreteria Neria, S.L."), ("CIF", "B12345678"), ("Codigo", "CLI-001"), ("Direccion", "Carrer Major, 18 - Girona")])
    top = y - 48 * mm
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, top, "CONCEPTOS FACTURADOS")
    top -= 5 * mm
    rows = [
        ["SKU-001", "Tornillo galvanizado M8", "100", "1,20", "120,00 EUR"],
        ["SKU-002", "Tuerca hexagonal M8", "100", "0,80", "80,00 EUR"],
        ["SKU-003", "Arandela plana M8", "100", "0,30", "30,00 EUR"],
    ]
    draw_table(c, MARGIN, top, [28 * mm, 70 * mm, 22 * mm, 27 * mm, 35 * mm], ["SKU", "Descripcion", "Cantidad", "Precio", "Importe"], rows)
    draw_box(c, MARGIN, 52 * mm, PAGE_W - 2 * MARGIN, 29 * mm, "Resumen")
    draw_fields(c, MARGIN + 4 * mm, 72 * mm, [("Base imponible", "230,00 EUR"), ("IVA 21%", "48,30 EUR"), ("Total", "278,30 EUR")], line_gap=6 * mm)
    c.setFillColor(GREEN)
    c.roundRect(PAGE_W - MARGIN - 55 * mm, 58 * mm, 49 * mm, 17 * mm, 2 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#256b3b"))
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(PAGE_W - MARGIN - 30.5 * mm, 66 * mm, "278,30 EUR")
    draw_signature_boxes(c, 17 * mm, "EMISOR", "CLIENTE")
    finish(c, filename)
    return path


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        create_order(),
        create_neria_order("06-pedido-entrada-PED-2026-0043.pdf", "PED-2026-0043", "ENTRADA", "Pedido de compra", "Pedido de entrada", "30/09/2026", "03/10/2026"),
        create_neria_order("07-pedido-salida-PED-2026-0044.pdf", "PED-2026-0044", "SALIDA", "Pedido de venta", "Pedido de salida", "30/09/2026", "03/10/2026"),
        create_blank_order_template(),
        create_delivery_note(),
        create_packing_list(),
        create_transport(),
        create_invoice(),
    ]
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
