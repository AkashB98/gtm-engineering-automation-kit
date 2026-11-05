import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator import generate_crm_records, generate_routing_golden
from validation import (valid_records, validate_record, validate_records,
                        write_sink)
from helpers import valid_record


class TestGate(unittest.TestCase):
    def test_clean_record_passes(self):
        self.assertEqual(validate_record(valid_record()), [])

    def test_optional_fields_may_be_absent(self):
        rec = valid_record()
        del rec["source"], rec["employees"]
        self.assertEqual(validate_record(rec), [])

    def test_missing_required_field(self):
        rec = valid_record()
        del rec["email"]
        self.assertEqual(validate_record(rec),
                         [{"field": "email",
                           "reason": "missing required field"}])

    def test_empty_string_is_missing_in_effect(self):
        errors = validate_record(valid_record(company="   "))
        self.assertEqual(errors, [{"field": "company",
                                   "reason": "must be a non-empty string"}])

    def test_wrong_type(self):
        errors = validate_record(valid_record(first_name=42))
        self.assertEqual(errors, [{"field": "first_name",
                                   "reason": "must be a string"}])

    def test_invalid_email_formats(self):
        for bad in ("no-at-sign", "a@b", "a b@c.com", "@x.com", "a@.com"):
            errors = validate_record(valid_record(email=bad))
            self.assertEqual(errors, [{"field": "email",
                                       "reason": "invalid email format"}],
                             bad)

    def test_state_allowed_values(self):
        errors = validate_record(valid_record(state="XX"))
        self.assertEqual(errors, [{"field": "state",
                                   "reason": "not an allowed value"}])
        self.assertEqual(validate_record(valid_record(state="dc")), [])

    def test_source_allowed_values(self):
        errors = validate_record(valid_record(source="carrier-pigeon"))
        self.assertEqual(errors, [{"field": "source",
                                   "reason": "not an allowed value"}])

    def test_employees_must_be_positive_int(self):
        for bad in ("many", 0, -3, 2.5, True):
            errors = validate_record(valid_record(employees=bad))
            self.assertEqual(errors, [{"field": "employees",
                                       "reason": "must be a positive integer"}],
                             repr(bad))

    def test_non_dict_record(self):
        self.assertEqual(validate_record(["not", "a", "dict"]),
                         [{"field": "(record)",
                           "reason": "record must be an object"}])


class TestFixtureGate(unittest.TestCase):
    def test_crm_fixture_split_pinned(self):
        records = generate_crm_records()
        gate = validate_records(records)
        self.assertEqual(gate["valid_count"], 6)
        self.assertEqual(gate["invalid_count"], 4)
        by_id = {r["lead_id"]: r for r in gate["results"]}
        self.assertEqual(by_id["C007"]["errors"],
                         [{"field": "email",
                           "reason": "missing required field"}])
        self.assertEqual(by_id["C008"]["errors"][0]["field"], "state")
        self.assertEqual(by_id["C009"]["errors"][0]["field"], "source")
        self.assertEqual(by_id["C010"]["errors"][0]["field"], "employees")
        for cid in ("C007", "C008", "C009", "C010"):
            self.assertEqual(len(by_id[cid]["errors"]), 1, cid)

    def test_clean_golden_leads_never_blocked(self):
        golden = generate_routing_golden()
        leads = [c["lead"] for c in golden["cases"]
                     if c["lead"]["state"] != "XX"]
        gate = validate_records(leads)
        self.assertEqual(gate["invalid_count"], 0, gate["results"])

    def test_sink_contains_only_valid_records(self):
        records = generate_crm_records()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sink.json")
            written = write_sink(records, path)
            self.assertEqual([r["lead_id"] for r in written],
                             ["C001", "C002", "C003", "C004", "C005", "C006"])
            with open(path, encoding="utf-8") as fh:
                on_disk = json.loads(fh.read())
            self.assertEqual(on_disk, written)
            self.assertEqual(valid_records(records), written)


if __name__ == "__main__":
    unittest.main()
