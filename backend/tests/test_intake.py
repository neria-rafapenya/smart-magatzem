import base64
import tempfile
import unittest
from pathlib import Path

from backend.intake import DeliveryNoteIntake, LocalObjectStore


class FakeERP:
    def import_delivery_note(self, payload):
        return {"id": "ERP-ALB-1001", "document_number": payload["document_number"], "status": "received"}

    def import_invoice(self, payload):
        return {"id": "ERP-FAC-1001", "document_number": payload["document_number"], "status": "received"}

    def import_order(self, payload):
        return {"id": "ERP-PED-1001", "document_number": payload["document_number"], "status": "received"}

    def import_packing_list(self, payload):
        return {"id": "ERP-PCK-1001", "document_number": payload["document_number"], "status": "received"}

    def import_transport_document(self, payload):
        return {"id": "ERP-TRP-1001", "document_number": payload["document_number"], "status": "received"}


class IntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pipeline = DeliveryNoteIntake(FakeERP(), LocalObjectStore(Path(self.temp_dir.name)))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_valid_document_is_sent_to_erp_and_copied_for_client(self) -> None:
        content = base64.b64encode(b"ALBARAN: ALB-TEST-001\nCLIENTE: Ferreteria Neria\nSKU-001 x 2").decode()

        record = self.pipeline.process(
            {
                "client_id": "CLI-001",
                "client_email": "cliente001@example.test",
                "client_name": "Ferretería Neria",
                "client_tax_id": "B12345678",
                "filename": "albaran.txt",
                "content_type": "text/plain",
                "content_base64": content,
            }
        )

        self.assertEqual(record["status"], "sent_to_erp")
        self.assertEqual(record["erp"]["id"], "ERP-ALB-1001")
        self.assertEqual(record["client_copy"]["status"], "prepared")
        self.assertEqual(record["email_delivery"]["status"], "simulated")
        self.assertEqual(record["email_delivery"]["to"], "cliente001@example.test")

    def test_document_without_albaran_marker_is_rejected(self) -> None:
        record = self.pipeline.process(
            {
                "client_id": "CLI-001",
                "client_email": "cliente001@example.test",
                "filename": "factura.txt",
                "content_type": "text/plain",
                "content_base64": base64.b64encode(b"FACTURA: F-001").decode(),
            }
        )

        self.assertEqual(record["status"], "rejected")
        self.assertTrue(record["interpretation"]["reasons"])

    def test_analysis_blocks_invalid_document_before_erp(self) -> None:
        analysis = self.pipeline.analyze(
            {
                "client_id": "CLI-001",
                "client_email": "cliente001@example.test",
                "filename": "factura.txt",
                "content_type": "text/plain",
                "content_base64": base64.b64encode(b"FACTURA: F-001").decode(),
            }
        )

        self.assertEqual(analysis["status"], "blocked")
        self.assertFalse(analysis["can_send"])
        self.assertIn("líneas de producto", analysis["missing_fields"])

    def test_manual_entry_replaces_failed_reading_and_is_sent_to_erp(self) -> None:
        record = self.pipeline.process(
            {
                "client_id": "CLI-001",
                "client_email": "cliente001@example.test",
                "client_name": "Ferretería Neria",
                "client_tax_id": "B12345678",
                "document_type": "auto",
                "filename": "foto-ilegible.jpg",
                "content_type": "image/jpeg",
                "content_base64": base64.b64encode(b"imagen sin lectura").decode(),
                "manual_data": {
                    "document_type": "delivery_note",
                    "document_number": "ALB-MAN-001",
                    "document_direction": "outbound",
                    "lines": [{"sku": "SKU-001", "quantity": 4}],
                },
            }
        )

        self.assertEqual(record["status"], "sent_to_erp")
        self.assertEqual(record["input_mode"], "manual")
        self.assertEqual(record["document_type"], "delivery_note")
        self.assertEqual(record["interpretation"]["document_number"], "ALB-MAN-001")
        self.assertEqual(record["interpretation"]["lines"], [{"sku": "SKU-001", "quantity": 4}])
        self.assertEqual(record["quality_report"]["provider"], "manual")

    def test_duplicate_document_is_blocked_before_erp(self) -> None:
        payload = {
            "client_id": "CLI-001",
            "client_email": "cliente001@example.test",
            "client_name": "Ferretería Neria",
            "filename": "albaran.txt",
            "content_type": "text/plain",
            "content_base64": base64.b64encode(b"ALBARAN: ALB-DUP-001\nCLIENTE: Ferreteria Neria\nSKU-001 x 2").decode(),
        }
        first = self.pipeline.process(payload)
        second = self.pipeline.process(payload)

        self.assertEqual(first["status"], "sent_to_erp")
        self.assertEqual(second["status"], "rejected")
        self.assertEqual(second["duplicate_check"]["status"], "duplicate")

    def test_native_xml_is_read_without_ocr(self) -> None:
        content = base64.b64encode(
            b"<deca><document>DECA-2026-001</document><direction>inbound</direction><customer>CLI-001</customer><line>SKU-001 x 2</line></deca>"
        ).decode()
        analysis = self.pipeline.analyze(
            {
                "client_id": "CLI-001",
                "document_type": "deca",
                "document_direction": "inbound",
                "filename": "deca.xml",
                "content_type": "application/xml",
                "content_base64": content,
            }
        )

        self.assertTrue(analysis["native_reading"]["is_native"])
        self.assertFalse(analysis["native_reading"]["ocr_used"])
        self.assertTrue(analysis["can_send"])

    def test_invoice_is_detected_and_sent_to_invoice_endpoint(self) -> None:
        content = base64.b64encode(b"FACTURA: T125 935\nCLIENTE: Ferreteria Neria\nABC123 Aceite motor 2,00 21,50").decode()

        record = self.pipeline.process(
            {
                "client_id": "CLI-001",
                "client_email": "cliente001@example.test",
                "client_name": "Ferretería Neria",
                "client_tax_id": "B12345678",
                "filename": "factura.txt",
                "content_type": "text/plain",
                "content_base64": content,
            }
        )

        self.assertEqual(record["document_type"], "invoice")
        self.assertEqual(record["status"], "sent_to_erp")
        self.assertEqual(record["erp"]["id"], "ERP-FAC-1001")

    def test_manual_document_type_can_override_automatic_detection(self) -> None:
        analysis = self.pipeline.analyze(
            {
                "client_id": "CLI-001",
                "client_email": "cliente001@example.test",
                "document_type": "invoice",
                "filename": "documento.txt",
                "content_type": "text/plain",
                "client_name": "Ferretería Neria",
                "client_tax_id": "B12345678",
                "content_base64": base64.b64encode(b"T125 935\nCLIENTE: Ferreteria Neria\nABC123 Aceite motor 2,00 21,50").decode(),
            }
        )

        self.assertTrue(analysis["can_send"])
        self.assertEqual(analysis["interpretation"]["document_type"], "invoice")

    def test_logistics_document_types_use_separate_erp_operations(self) -> None:
        documents = [
            ("order", "PEDIDO DE COMPRA: PED-001\nPROVEEDOR: Ferreteria Neria\nSKU-001 x 2", "ERP-PED-1001", "inbound"),
            ("delivery_note", "ALBARAN DE SALIDA: ALB-001\nCLIENTE: Ferreteria Neria\nSKU-001 x 2", "ERP-ALB-1001", "outbound"),
            ("packing_list", "PACKING LIST: PCK-001\nCLIENTE: Ferreteria Neria\nSKU-001 x 2", "ERP-PCK-1001", "outbound"),
            ("transport_document", "CMR: CMR-001\nSALIDA\nCLIENTE: Ferreteria Neria\nSKU-001 x 2", "ERP-TRP-1001", "outbound"),
        ]

        for document_type, text, erp_id, direction in documents:
            with self.subTest(document_type=document_type):
                record = self.pipeline.process(
                    {
                        "client_id": "CLI-001",
                        "client_email": "cliente001@example.test",
                        "client_name": "Ferretería Neria",
                        "client_tax_id": "B12345678",
                        "document_type": document_type,
                        "filename": f"{document_type}.txt",
                        "content_type": "text/plain",
                        "content_base64": base64.b64encode(text.encode()).decode(),
                    }
                )

                self.assertEqual(record["status"], "sent_to_erp")
                self.assertEqual(record["erp"]["id"], erp_id)
                self.assertEqual(record["document_direction"], direction)

    def test_auto_detects_standalone_order_number_and_explicit_outbound_flow(self) -> None:
        analysis = self.pipeline.analyze(
            {
                "client_id": "CLI-001",
                "client_email": "cliente001@example.test",
                "client_name": "Ferretería Neria",
                "client_tax_id": "B12345678",
                "document_type": "auto",
                "filename": "pedido-fotografiado.jpg",
                "content_type": "text/plain",
                "content_base64": base64.b64encode(
                    b"PED-2026-0042\nPEDIDO\nCLIENTE: Ferreteria Neria\nCLI-001\n"
                    b"SKU-001 x 100\nSKU-002 x 100\nSKU-003 x 100\n"
                    b"flujo de expedicion OUTBOUND"
                ).decode(),
            }
        )

        self.assertTrue(analysis["can_send"])
        self.assertEqual(analysis["interpretation"]["document_type"], "order")
        self.assertEqual(analysis["interpretation"]["document_number"], "PED-2026-0042")
        self.assertEqual(analysis["interpretation"]["document_direction"], "outbound")

    def test_inbound_document_does_not_require_client_email(self) -> None:
        record = self.pipeline.process(
            {
                "client_id": "CLI-001",
                "client_name": "Ferretería Neria",
                "client_tax_id": "B12345678",
                "document_type": "packing_list",
                "filename": "packing-list.txt",
                "content_type": "text/plain",
                "content_base64": base64.b64encode(
                    b"PACKING LIST: PCK-002\nPROVEEDOR: Ferreteria Neria\nSKU-001 x 2"
                ).decode(),
            }
        )

        self.assertEqual(record["status"], "sent_to_erp")
        self.assertEqual(record["email_delivery"]["status"], "not_required")

    def test_packing_and_transport_details_are_interpreted(self) -> None:
        packing = self.pipeline.analyze(
            {
                "client_id": "CLI-001",
                "client_email": "cliente001@example.test",
                "client_name": "Ferretería Neria",
                "client_tax_id": "B12345678",
                "document_type": "packing_list",
                "filename": "packing.txt",
                "content_type": "text/plain",
                "content_base64": base64.b64encode(
                    b"PACKING LIST: PCK-003\nCLIENTE: Ferreteria Neria\nBULTOS: 4\nPESO TOTAL: 120,5 KG\nDIMENSIONES: 80x60x40"
                ).decode(),
            }
        )
        transport = self.pipeline.analyze(
            {
                "client_id": "CLI-001",
                "client_email": "cliente001@example.test",
                "client_name": "Ferretería Neria",
                "client_tax_id": "B12345678",
                "document_type": "transport_document",
                "filename": "cmr.txt",
                "content_type": "text/plain",
                "content_base64": base64.b64encode(
                    b"CMR: CMR-003\nSALIDA\nCLIENTE: Ferreteria Neria\nTRANSPORTISTA: Transportes Soler\nMATRICULA: 1234 ABC\nPICKUP: 29/09 10:00\nVENTANA HORARIA: 12:00-14:00\nSKU-001 x 2"
                ).decode(),
            }
        )

        self.assertEqual(packing["interpretation"]["details"]["packages_count"], 4)
        self.assertEqual(packing["interpretation"]["details"]["weight_kg"], 120.5)
        self.assertEqual(transport["interpretation"]["details"]["carrier"], "TRANSPORTES SOLER")
        self.assertEqual(transport["interpretation"]["details"]["vehicle_plate"], "1234ABC")


if __name__ == "__main__":
    unittest.main()
