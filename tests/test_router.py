import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator import generate_routing_golden
from router import (REPS, region_of, route_leads, route_payload,
                    routing_accuracy)
from helpers import make_lead


def _west(lead_id, company="Quartz Peak Software"):
    return make_lead(lead_id=lead_id, company=company, state="CA",
                     email=f"{lead_id.lower()}@quartzpeak.com")


class TestRegions(unittest.TestCase):
    def test_region_mapping(self):
        self.assertEqual(region_of("CA"), "west")
        self.assertEqual(region_of("tx"), "central")
        self.assertEqual(region_of("NY"), "east")
        self.assertEqual(region_of("FL"), "south")
        self.assertIsNone(region_of("XX"))
        self.assertIsNone(region_of(""))
        self.assertIsNone(region_of(None))


class TestGoldenRouting(unittest.TestCase):
    def test_golden_accuracy_is_perfect(self):
        golden = generate_routing_golden()
        leads = [c["lead"] for c in golden["cases"]]
        acc = routing_accuracy(route_leads(leads), golden)
        self.assertEqual(acc, {"correct": 13, "total": 13, "accuracy": 1.0})

    def test_ownership_beats_territory(self):
        lead = make_lead(company="Aster Robotics", state="CA")
        (a,) = route_leads([lead])
        self.assertEqual(a["rep_id"], "cara_lind")  # east rep owns it
        self.assertEqual(a["reason"], "account_owner")

    def test_ownership_uses_normalized_company(self):
        lead = make_lead(company="Northwind Labs, Inc.", state="WA")
        (a,) = route_leads([lead])
        self.assertEqual(a["rep_id"], "ben_osei")

    def test_unknown_territory_unassigned(self):
        (a,) = route_leads([make_lead(state="XX")])
        self.assertIsNone(a["rep_id"])
        self.assertEqual(a["reason"], "unknown_territory")


class TestRoundRobinAndCapacity(unittest.TestCase):
    def test_round_robin_alternates(self):
        leads = [_west(f"W{i}") for i in range(4)]
        reps = [a["rep_id"] for a in route_leads(leads)]
        self.assertEqual(reps, ["ana_ruiz", "sam_whitaker",
                                "ana_ruiz", "sam_whitaker"])

    def test_capacity_is_a_hard_limit(self):
        leads = [_west(f"W{i}") for i in range(8)]
        assignments = route_leads(leads)
        reps = [a["rep_id"] for a in assignments]
        self.assertEqual(reps[:6], ["ana_ruiz", "sam_whitaker"] * 3)
        self.assertEqual(reps[6:], [None, None])
        self.assertTrue(all(a["reason"] == "capacity_exhausted"
                            for a in assignments[6:]))
        payload = route_payload(leads)
        self.assertTrue(all(n <= REPS[r]["capacity"]
                            for r, n in payload["summary"]["per_rep"].items()))

    def test_owner_at_capacity_falls_through_to_territory(self):
        # cara_lind owns Aster Robotics AND is east rep 1 (capacity 3).
        owned = [make_lead(lead_id=f"A{i}", company="Aster Robotics",
                           state="NY", email=f"a{i}@asterrobotics.com")
                 for i in range(3)]
        fourth = make_lead(lead_id="A9", company="Aster Robotics",
                           state="NY", email="a9@asterrobotics.com")
        assignments = route_leads(owned + [fourth])
        self.assertEqual([a["rep_id"] for a in assignments[:3]],
                         ["cara_lind"] * 3)
        self.assertEqual(assignments[3]["rep_id"], "omar_haddad")
        self.assertEqual(assignments[3]["reason"],
                         "owner_at_capacity_territory")

    def test_routing_is_deterministic(self):
        leads = [_west(f"W{i}") for i in range(5)]
        self.assertEqual(route_leads(leads), route_leads(leads))

    def test_unowned_account_does_not_stick(self):
        leads = [_west("S1"), _west("S2")]
        reps = [a["rep_id"] for a in route_leads(leads)]
        self.assertNotEqual(reps[0], reps[1])


if __name__ == "__main__":
    unittest.main()
