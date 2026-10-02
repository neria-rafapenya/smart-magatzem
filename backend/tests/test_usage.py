import unittest

from backend.usage import build_usage_snapshot


class UsageSnapshotTests(unittest.TestCase):
    def test_local_snapshot_excludes_cognito_and_sums_estimated_services(self) -> None:
        snapshot = build_usage_snapshot(
            [
                {
                    "id": "INT-001",
                    "created_at": "2026-09-30T10:00:00+00:00",
                    "status": "sent_to_erp",
                    "email_delivery": {"status": "simulated"},
                },
                {
                    "id": "INT-002",
                    "created_at": "2026-09-30T10:01:00+00:00",
                    "status": "rejected",
                },
            ],
            "local",
        )

        self.assertFalse(snapshot["aws_connected"])
        self.assertTrue(snapshot["cognito_excluded"])
        self.assertEqual(snapshot["summary"]["actual"]["requests"], 0)
        self.assertEqual(snapshot["summary"]["estimated"]["requests"], 11)
        self.assertNotIn("Cognito", {event["service"] for event in snapshot["events"]})
        self.assertEqual(snapshot["summary"]["estimated"]["messages"], 1)
        self.assertGreater(snapshot["summary"]["estimated_token_cost_eur"], 0)
        self.assertEqual(snapshot["summary"]["actual_token_cost_eur"], 0.0)


if __name__ == "__main__":
    unittest.main()
