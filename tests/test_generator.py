import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import (generate_crm_records, generate_ground_truth,
                       generate_leads, generate_routing_golden,
                       leads_to_csv, leads_to_jsonl)
from cli import load_records
import tempfile


class TestGenerator(unittest.TestCase):
    def test_deterministic_same_seed(self):
        self.assertEqual(generate_leads(), generate_leads())
        self.assertEqual(generate_leads(7), generate_leads(7))

    def test_counts(self):
        leads = generate_leads()
        self.assertEqual(len(leads), 33)
        self.assertEqual(len({r["lead_id"] for r in leads}), 33)

    def test_different_seed_same_id_set(self):
        self.assertEqual({r["lead_id"] for r in generate_leads(1)},
                         {r["lead_id"] for r in generate_leads(42)})

    def test_ground_truth_shape(self):
        truth = generate_ground_truth()
        self.assertEqual(len(truth["clusters"]), 19)
        self.assertEqual(len(truth["pairs"]), 17)
        covered = {lid for ids in truth["clusters"].values() for lid in ids}
        self.assertEqual(covered, {r["lead_id"] for r in generate_leads()})

    def test_all_emails_fictional_domains(self):
        domains = set()
        for r in generate_leads():
            if r["email"]:
                domains.add(r["email"].split("@")[1])
        self.assertTrue(domains)
        for d in domains:
            self.assertNotIn(d, {"gmail.com", "yahoo.com", "outlook.com"})

    def test_jsonl_roundtrip(self):
        leads = generate_leads()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "leads.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(leads_to_jsonl(leads))
            self.assertEqual(load_records(path), leads)

    def test_csv_roundtrip(self):
        leads = generate_leads()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "leads.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(leads_to_csv(leads))
            self.assertEqual(load_records(path), leads)

    def test_routing_golden_shape(self):
        golden = generate_routing_golden()
        self.assertEqual(len(golden["cases"]), 13)
        reps = {c["expected_rep"] for c in golden["cases"]}
        self.assertIn(None, reps)  # the unknown-territory case

    def test_crm_records_shape(self):
        records = generate_crm_records()
        self.assertEqual(len(records), 10)
        self.assertEqual([r["lead_id"] for r in records],
                         [f"C00{i}" for i in range(1, 10)] + ["C010"])


if __name__ == "__main__":
    unittest.main()
