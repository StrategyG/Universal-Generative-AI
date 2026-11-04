import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts" / "v1" / "platform-event.schema.json"
VALID_FIXTURE_PATH = ROOT / "contracts" / "v1" / "fixtures" / "platform-event.valid.json"


class PlatformEventSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.event = json.loads(VALID_FIXTURE_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def test_valid_golden_event(self):
        self.assertEqual(list(self.validator.iter_errors(self.event)), [])

    def test_rejects_missing_tenant(self):
        event = copy.deepcopy(self.event)
        del event["tenant_id"]
        self.assertTrue(list(self.validator.iter_errors(event)))

    def test_rejects_non_monotonic_sequence(self):
        event = copy.deepcopy(self.event)
        event["sequence"] = 0
        self.assertTrue(list(self.validator.iter_errors(event)))

    def test_rejects_major_version_without_schema_upgrade(self):
        event = copy.deepcopy(self.event)
        event["contract_version"] = "2.0.0"
        self.assertTrue(list(self.validator.iter_errors(event)))

    def test_rejects_unexpected_top_level_fields(self):
        event = copy.deepcopy(self.event)
        event["access_token"] = "must-never-be-present"
        self.assertTrue(list(self.validator.iter_errors(event)))

    def test_rejects_invalid_actor_issuer(self):
        event = copy.deepcopy(self.event)
        event["principal"]["issuer"] = "not-an-issuer-uri"
        self.assertTrue(list(self.validator.iter_errors(event)))


if __name__ == "__main__":
    unittest.main()
