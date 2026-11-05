import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dedupe import (cluster_leads, dedupe_payload, email_domain,
                    is_duplicate, levenshtein, normalize_company,
                    normalize_email, pair_metrics, pairs_of, truth_pairs)
from generator import generate_ground_truth, generate_leads
from helpers import make_lead


class TestNormalize(unittest.TestCase):
    def test_company_suffixes_stripped(self):
        self.assertEqual(normalize_company("Northwind Labs, Inc."),
                         "northwind labs")
        self.assertEqual(normalize_company("Northwind Labs LLC"),
                         "northwind labs")
        self.assertEqual(normalize_company("Acme Corp."), "acme")
        self.assertEqual(normalize_company("Acme Corporation"), "acme")

    def test_company_case_and_punctuation(self):
        self.assertEqual(normalize_company("BRIGHTPATH  Health!"),
                         "brightpath health")
        self.assertEqual(normalize_company(""), "")
        self.assertEqual(normalize_company(None), "")

    def test_email_normalization_and_domain(self):
        self.assertEqual(normalize_email("  Maya.Chen@Example.COM "),
                         "maya.chen@example.com")
        self.assertEqual(email_domain("a@Sub.Example.com"), "sub.example.com")
        self.assertEqual(email_domain("no-at-sign"), "")
        self.assertEqual(email_domain(""), "")

    def test_levenshtein(self):
        self.assertEqual(levenshtein("chen", "chan"), 1)
        self.assertEqual(levenshtein("webb", "web"), 1)
        self.assertEqual(levenshtein("same", "same"), 0)
        self.assertEqual(levenshtein("", "abc"), 3)
        self.assertEqual(levenshtein("kitten", "sitting"), 3)


class TestMatchingRules(unittest.TestCase):
    def test_exact_email_matches_despite_name_typo(self):
        a = make_lead(email="same@example.com", last="Webb")
        b = make_lead(lead_id="T002", email="same@example.com", last="Web",
                      company="Other Co")
        self.assertTrue(is_duplicate(a, b))

    def test_name_and_company_match(self):
        a = make_lead(email="one@example.com")
        b = make_lead(lead_id="T002", email="two@example.org")
        self.assertTrue(is_duplicate(a, b))

    def test_typo_name_same_company(self):
        a = make_lead(last="Chen")
        b = make_lead(lead_id="T002", last="Chan", email="")
        self.assertTrue(is_duplicate(a, b))

    def test_nickname_same_company(self):
        a = make_lead(first="Robert", last="Hargrove", company="Ironpeak")
        b = make_lead(lead_id="T002", first="Bob", last="Hargrove",
                      company="Ironpeak", email="bob@ironpeak.com")
        self.assertTrue(is_duplicate(a, b))

    def test_initial_same_company(self):
        a = make_lead(first="Jordan", last="Ellis", company="Brightpath")
        b = make_lead(lead_id="T002", first="J.", last="Ellis",
                      company="Brightpath", email="j@brightpath.com")
        self.assertTrue(is_duplicate(a, b))

    def test_same_name_different_company_no_merge(self):
        a = make_lead(first="Alex", last="Morgan", company="Verdant Energy",
                      email="alex@verdant.com")
        b = make_lead(lead_id="T002", first="Alex", last="Morgan",
                      company="Cloudhaven", email="alex@cloudhaven.io")
        self.assertFalse(is_duplicate(a, b))

    def test_same_company_different_person_no_merge(self):
        a = make_lead(first="Maya", last="Chen", company="Northwind Labs",
                      email="maya@northwind.com")
        b = make_lead(lead_id="T002", first="Derek", last="Shaw",
                      company="Northwind Labs", email="derek@northwind.com")
        self.assertFalse(is_duplicate(a, b))

    def test_generic_domain_name_match_no_merge(self):
        from dedupe import GENERIC_DOMAINS
        generic = sorted(GENERIC_DOMAINS)[0]  # a free-mail domain
        a = make_lead(first="Sam", last="Lee", company="Alpha",
                      email=f"sam.lee@{generic}")
        b = make_lead(lead_id="T002", first="Sam", last="Lee",
                      company="Beta", email=f"samlee@{generic}")
        # Same name, same free-mail domain, different companies and
        # different local parts: the domain rule must NOT fire.
        self.assertFalse(is_duplicate(a, b))

    def test_two_initials_same_surname_no_merge(self):
        a = make_lead(first="J.", last="Ellis", company="Brightpath")
        b = make_lead(lead_id="T002", first="J.", last="Smith",
                      company="Brightpath", email="x@brightpath.com")
        self.assertFalse(is_duplicate(a, b))


class TestFixtureScoring(unittest.TestCase):
    def setUp(self):
        self.leads = generate_leads()
        self.truth = generate_ground_truth()
        self.by_id = {r["lead_id"]: r for r in self.leads}

    def test_headline_precision_recall_pinned(self):
        payload = dedupe_payload(self.leads, self.truth)
        m = payload["metrics"]
        self.assertEqual(m["precision"], 1.0)
        self.assertEqual(m["recall"], 0.9412)
        self.assertEqual((m["true_positives"], m["false_positives"],
                          m["false_negatives"]), (16, 0, 1))
        self.assertEqual(payload["cluster_count"], 20)

    def test_hard_negatives_stay_separate(self):
        clusters = cluster_leads(self.leads)
        home = {}
        for members in clusters:
            for lid in members:
                home[lid] = tuple(members)
        self.assertNotEqual(home["L025"], home["L026"])  # same name, 2 firms
        self.assertEqual(home["L024"], ("L024",))        # same firm, new person
        self.assertEqual(home["L001"], ("L001", "L002", "L003"))

    def test_known_miss_is_pinned_not_hidden(self):
        # Kate / Katherine Voss: outside the nickname map + abbreviated
        # company ("Ptrs") — the matcher misses this true pair.
        self.assertFalse(is_duplicate(self.by_id["L032"], self.by_id["L033"]))
        missed = truth_pairs(self.truth) - pairs_of(cluster_leads(self.leads))
        self.assertEqual(missed, {("L032", "L033")})

    def test_pair_metrics_hand_case(self):
        m = pair_metrics({("a", "b"), ("a", "c")},
                         {("a", "b"), ("b", "c")})
        self.assertEqual(m, {"precision": 0.5, "recall": 0.5,
                             "true_positives": 1, "false_positives": 1,
                             "false_negatives": 1})


if __name__ == "__main__":
    unittest.main()
