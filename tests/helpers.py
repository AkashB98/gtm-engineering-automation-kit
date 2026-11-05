"""Shared builders for the test suite (not a test module)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_lead(lead_id="T001", first="Test", last="Person",
              email="test.person@example.com", company="Example Co",
              state="CA", source="web"):
    return {"lead_id": lead_id, "first_name": first, "last_name": last,
            "email": email, "company": company, "state": state,
            "source": source}


def valid_record(**overrides):
    rec = {"lead_id": "T100", "first_name": "Test", "last_name": "Person",
           "email": "test.person@example.com", "company": "Example Co",
           "state": "CA", "source": "web", "employees": 25}
    rec.update(overrides)
    return rec
