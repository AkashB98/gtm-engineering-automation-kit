"""Schema contract gate: no record reaches the CRM sink unless it
satisfies the contract — required fields, types, allowed values.

Invalid records are rejected with a per-field reason list, before
any write. The gate reports errors and never raises on bad data, so
callers can map a dirty batch to a clean exit code instead of a
crash. Only valid records are ever written to the sink file.
"""

from __future__ import annotations

import json
from typing import Dict, List

ALLOWED_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS "
    "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV "
    "WI WY DC".split())

ALLOWED_SOURCES = {"web", "referral", "event", "outbound", "partner"}

REQUIRED_STRING_FIELDS = ["lead_id", "first_name", "last_name",
                          "email", "company", "state"]


def _email_ok(value: str) -> bool:
    if " " in value or value.count("@") != 1:
        return False
    local, domain = value.split("@")
    return bool(local) and "." in domain and not domain.startswith(".") \
        and not domain.endswith(".")


def validate_record(record: Dict) -> List[Dict]:
    """Per-field errors for one record ([] means the record is clean)."""
    if not isinstance(record, dict):
        return [{"field": "(record)", "reason": "record must be an object"}]
    errors: List[Dict] = []
    for field in REQUIRED_STRING_FIELDS:
        if field not in record or record[field] is None:
            errors.append({"field": field,
                           "reason": "missing required field"})
            continue
        value = record[field]
        if not isinstance(value, str):
            errors.append({"field": field, "reason": "must be a string"})
            continue
        if not value.strip():
            errors.append({"field": field,
                           "reason": "must be a non-empty string"})
            continue
        if field == "email" and not _email_ok(value.strip()):
            errors.append({"field": field, "reason": "invalid email format"})
        if field == "state" and value.strip().upper() not in ALLOWED_STATES:
            errors.append({"field": field, "reason": "not an allowed value"})
    if "source" in record and record["source"] is not None:
        value = record["source"]
        if not isinstance(value, str):
            errors.append({"field": "source", "reason": "must be a string"})
        elif value not in ALLOWED_SOURCES:
            errors.append({"field": "source",
                           "reason": "not an allowed value"})
    if "employees" in record and record["employees"] is not None:
        value = record["employees"]
        # bool is a subclass of int — reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            errors.append({"field": "employees",
                           "reason": "must be a positive integer"})
    return errors


def validate_records(records: List[Dict]) -> Dict:
    results = []
    for record in records:
        errors = validate_record(record)
        results.append({
            "lead_id": record.get("lead_id") if isinstance(record, dict) else None,
            "valid": not errors,
            "errors": errors,
        })
    valid = sum(1 for r in results if r["valid"])
    return {"results": results, "valid_count": valid,
            "invalid_count": len(results) - valid}


def valid_records(records: List[Dict]) -> List[Dict]:
    return [r for r in records if not validate_record(r)]


def write_sink(records: List[Dict], path: str) -> List[Dict]:
    """Write ONLY the valid records to the JSON sink; returns them."""
    clean = valid_records(records)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(clean, sort_keys=True) + "\n")
    return clean
