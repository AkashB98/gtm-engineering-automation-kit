"""Combined report: dedupe quality, routing accuracy, gate outcome
and a deterministic narrative copied from the computed numbers."""

from __future__ import annotations

from typing import Dict, List

from dedupe import dedupe_payload  # noqa: E402
from router import route_leads, routing_accuracy  # noqa: E402
from validation import validate_records  # noqa: E402


def build_report(leads: List[Dict], truth: Dict, golden: Dict,
                 crm_records: List[Dict]) -> Dict:
    dedupe = dedupe_payload(leads, truth)
    golden_leads = [c["lead"] for c in golden["cases"]]
    accuracy = routing_accuracy(route_leads(golden_leads), golden)
    gate = validate_records(crm_records)
    m = dedupe["metrics"]
    narrative = (
        f"Dedupe: {dedupe['record_count']} messy leads resolved into "
        f"{dedupe['cluster_count']} clusters; pair precision "
        f"{m['precision']} and recall {m['recall']} against "
        f"{m['true_positives'] + m['false_negatives']} labelled "
        f"duplicate pairs ({m['false_negatives']} missed, "
        f"{m['false_positives']} falsely merged). "
        f"Routing: {accuracy['correct']}/{accuracy['total']} golden "
        f"cases assigned to the expected rep (accuracy "
        f"{accuracy['accuracy']}). "
        f"Schema gate: {gate['valid_count']} of "
        f"{gate['valid_count'] + gate['invalid_count']} CRM records "
        f"passed the contract; {gate['invalid_count']} rejected with "
        f"per-field reasons before any CRM write."
    )
    return {"dedupe": dedupe, "routing": accuracy, "gate": gate,
            "narrative": narrative}
