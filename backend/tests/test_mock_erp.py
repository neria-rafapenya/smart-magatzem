import unittest

from ERP.mock_erp import MockERPState
from ERP.openapi import OPENAPI_SPEC


class MockERPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.erp = MockERPState()

    def test_has_deterministic_seed_data(self) -> None:
        self.assertEqual(len(self.erp.list_products()), 3)
        self.assertEqual(len(self.erp.orders), 2)
        self.assertEqual(len(self.erp.customers), 20)
        self.assertEqual(self.erp.orders[0]["id"], "PED-1001")

    def test_delivery_note_lifecycle_from_order(self) -> None:
        note = self.erp.create_delivery_note({"order_id": "PED-1001"})
        self.assertEqual(note["id"], "ALB-1001")
        self.assertEqual(note["status"], "draft")
        self.assertEqual(note["lines"][0]["quantity"], 4)

        confirmed = self.erp.transition_delivery_note("ALB-1001", "confirm")
        delivered = self.erp.transition_delivery_note("ALB-1001", "deliver")

        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(delivered["status"], "delivered")
        self.assertEqual(self.erp.orders[0]["status"], "delivered")

    def test_delivery_note_rejects_invalid_transition(self) -> None:
        self.erp.create_delivery_note({"order_id": "PED-1001"})

        with self.assertRaises(ValueError):
            self.erp.transition_delivery_note("ALB-1001", "deliver")

    def test_openapi_documents_delivery_note_flow(self) -> None:
        paths = OPENAPI_SPEC["paths"]

        self.assertIn("/api/v1/delivery-notes", paths)
        self.assertIn("/api/v1/orders/{id}/delivery-note", paths)
        self.assertIn("/api/v1/delivery-notes/{id}/deliver", paths)
        self.assertIn("/api/v1/invoices/import", paths)
        self.assertIn("/api/v1/orders/import", paths)
        self.assertIn("/api/v1/packing-lists/import", paths)
        self.assertIn("/api/v1/transport-documents/import", paths)

    def test_invoice_import_is_kept_separate_from_delivery_notes(self) -> None:
        invoice = self.erp.import_invoice(
            {
                "client_id": "CLI-001",
                "document_number": "T125 935",
                "lines": [{"sku": "1695213980", "quantity": 3.5}],
            }
        )

        self.assertEqual(invoice["id"], "ERP-FAC-1001")
        self.assertEqual(invoice["status"], "received")
        self.assertEqual(self.erp.snapshot()["imported_invoices"][0]["document_number"], "T125 935")

    def test_logistics_imports_are_kept_separate(self) -> None:
        order = self.erp.import_order(
            {
                "client_id": "CLI-001",
                "document_number": "PED-001",
                "document_direction": "inbound",
                "order_kind": "purchase",
            }
        )
        packing_list = self.erp.import_packing_list(
            {
                "client_id": "CLI-001",
                "document_number": "PCK-001",
                "document_direction": "inbound",
            }
        )
        transport = self.erp.import_transport_document(
            {
                "client_id": "CLI-001",
                "document_number": "CMR-001",
                "document_direction": "inbound",
            }
        )

        self.assertEqual(order["id"], "ERP-PED-1001")
        self.assertEqual(packing_list["id"], "ERP-PCK-1001")
        self.assertEqual(transport["id"], "ERP-TRP-1001")
        snapshot = self.erp.snapshot()
        self.assertEqual(len(snapshot["imported_orders"]), 1)
        self.assertEqual(len(snapshot["imported_packing_lists"]), 1)
        self.assertEqual(len(snapshot["imported_transport_documents"]), 1)

    def test_reset_returns_to_seed_state(self) -> None:
        self.erp.create_delivery_note({"order_id": "PED-1001"})
        self.erp.reset()

        self.assertEqual(self.erp.list_delivery_notes()[0]["id"], "ALB-1000")
        self.assertEqual(self.erp.orders[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
