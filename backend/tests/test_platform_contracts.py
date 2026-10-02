import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from backend.auth import LocalAuthError, LocalAuthProvider, has_permission
from backend.connectors import LocalFileConnector
from backend.quality import LocalImageQualityAnalyzer


class PlatformContractTests(unittest.TestCase):
    def test_local_auth_exposes_tenant_roles_and_permissions(self) -> None:
        provider = LocalAuthProvider(db_path=":memory:")
        self.addCleanup(provider.store.connection.close)
        result = provider.login("operario@smart-magatzem.local", "demo1234")
        identity = result["user"]

        self.assertEqual(result["access_token"], "local.USR-003.TEN-001")
        self.assertEqual(identity["tenant_id"], "TEN-001")
        self.assertIn("warehouse_operator", identity["roles"])
        self.assertTrue(has_permission(identity, "document.capture"))
        self.assertFalse(has_permission(identity, "tenant.configure"))
        self.assertEqual(provider.authenticate(result["access_token"]), identity)

    def test_local_auth_rejects_wrong_password(self) -> None:
        provider = LocalAuthProvider(db_path=":memory:")
        self.addCleanup(provider.store.connection.close)
        with self.assertRaises(LocalAuthError):
            provider.login("admin@smart-magatzem.local", "incorrecta")

    def test_local_auth_supports_concurrent_http_threads(self) -> None:
        provider = LocalAuthProvider(db_path=":memory:")
        self.addCleanup(provider.store.connection.close)

        def login(_: int) -> str:
            result = provider.login("operario@smart-magatzem.local", "demo1234")
            return result["user"]["user_id"]

        with ThreadPoolExecutor(max_workers=8) as executor:
            user_ids = list(executor.map(login, range(24)))

        self.assertEqual(user_ids, ["USR-003"] * 24)

    def test_image_quality_does_not_block_text_or_digital_document(self) -> None:
        report = LocalImageQualityAnalyzer().analyze(b"texto", "text/plain", "documento.txt")

        self.assertEqual(report["status"], "not_applicable")
        self.assertEqual(report["decision"], "pass")

    @staticmethod
    def _quality_fixture(blur_radius: float) -> bytes:
        image = Image.new("L", (1200, 1600), 245)
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 100, 1120, 1500), outline=25, width=8)
        for y in range(200, 1450, 100):
            draw.line((150, y, 1050, y), fill=50, width=3)
        image = image.filter(ImageFilter.GaussianBlur(blur_radius))
        output = BytesIO()
        image.save(output, format="JPEG", quality=85)
        return output.getvalue()

    def test_moderate_image_issue_is_warning_not_block(self) -> None:
        report = LocalImageQualityAnalyzer().analyze(
            self._quality_fixture(1.5), "image/jpeg", "captura.jpg"
        )

        self.assertEqual(report["status"], "good")
        self.assertEqual(report["decision"], "pass")
        self.assertIn("imagen borrosa o desenfocada", report["warnings"])
        self.assertEqual(report["blocking_reasons"], [])

    def test_severe_image_issue_still_blocks(self) -> None:
        report = LocalImageQualityAnalyzer().analyze(
            self._quality_fixture(3.0), "image/jpeg", "captura.jpg"
        )

        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(report["decision"], "review")
        self.assertIn("imagen borrosa o desenfocada", report["blocking_reasons"])

    def test_file_connector_exports_json_csv_and_excel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connector = LocalFileConnector(Path(directory))
            payload = {
                "client_id": "CLI-001",
                "document_number": "ALB-LOCAL-001",
                "lines": [{"sku": "SKU-001", "quantity": 2}],
            }
            first = connector.import_document("delivery_note", payload)
            second = connector.import_document("delivery_note", payload)

            self.assertEqual(first["status"], "queued")
            self.assertEqual(second["status"], "already_received")
            self.assertTrue(Path(first["files"]["json"]).exists())
            self.assertTrue(Path(first["files"]["csv"]).exists())
            self.assertTrue(Path(first["files"]["xlsx"]).exists())
            canonical = json.loads(Path(first["files"]["json"]).read_text(encoding="utf-8"))
            self.assertEqual(canonical["payload"]["document_number"], "ALB-LOCAL-001")


if __name__ == "__main__":
    unittest.main()
