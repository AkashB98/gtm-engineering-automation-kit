"""Rules-based lead routing: territory, account ownership,
round-robin with per-rep capacity limits.

Rule order (first match wins, capacity is a hard limit everywhere):

1. **Account ownership** — a lead whose (normalised) company is an
   existing owned account goes to that account's rep.
2. **Territory round-robin** — otherwise the lead's state maps to a
   region and the region's reps take turns, skipping any rep who is
   at capacity. Unowned accounts do not "stick" to a rep.
3. If the owner is at capacity, the lead falls through to the
   territory round-robin (reason ``owner_at_capacity_territory``).
4. Unknown territory, or every candidate at capacity, leaves the
   lead **unassigned with a reason** — never guessed.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from dedupe import normalize_company  # noqa: E402  (same-package import)

STATE_TO_REGION = {}
for _states, _region in [
        ("CA WA OR NV AZ UT CO ID MT WY NM HI AK", "west"),
        ("TX OK KS NE SD ND MN IA MO IL WI MI", "central"),
        ("NY MA VT NH ME RI CT NJ PA DE MD VA WV OH", "east"),
        ("FL GA NC SC TN AL MS KY AR LA", "south")]:
    for _s in _states.split():
        STATE_TO_REGION[_s] = _region

# Rep order inside a region IS the round-robin order.
REGION_REPS = {
    "west": ["ana_ruiz", "sam_whitaker"],
    "central": ["ben_osei", "nina_kowalski"],
    "east": ["cara_lind", "omar_haddad"],
    "south": ["devon_park", "grace_liu"],
}

REPS = {
    "ana_ruiz": {"name": "Ana Ruiz", "region": "west", "capacity": 3},
    "sam_whitaker": {"name": "Sam Whitaker", "region": "west", "capacity": 3},
    "ben_osei": {"name": "Ben Osei", "region": "central", "capacity": 3},
    "nina_kowalski": {"name": "Nina Kowalski", "region": "central", "capacity": 3},
    "cara_lind": {"name": "Cara Lind", "region": "east", "capacity": 3},
    "omar_haddad": {"name": "Omar Haddad", "region": "east", "capacity": 3},
    "devon_park": {"name": "Devon Park", "region": "south", "capacity": 3},
    "grace_liu": {"name": "Grace Liu", "region": "south", "capacity": 3},
}

# Existing accounts, keyed by NORMALISED company name.
OWNERSHIP = {
    "aster robotics": "cara_lind",
    "northwind labs": "ben_osei",
    "verdant energy": "ana_ruiz",
}


def region_of(state) -> Optional[str]:
    if not isinstance(state, str):
        return None
    return STATE_TO_REGION.get(state.strip().upper())


def route_leads(leads: List[Dict]) -> List[Dict]:
    """Assign each lead in input order; returns one assignment dict
    per lead: {lead_id, rep_id (or None), reason, region}."""
    counts = {rep_id: 0 for rep_id in REPS}
    pointers = {region: 0 for region in REGION_REPS}
    assignments: List[Dict] = []

    def territory_pick(region: str) -> Optional[str]:
        reps = REGION_REPS[region]
        start = pointers[region]
        for step in range(len(reps)):
            idx = (start + step) % len(reps)
            rep_id = reps[idx]
            if counts[rep_id] < REPS[rep_id]["capacity"]:
                pointers[region] = (idx + 1) % len(reps)
                return rep_id
        return None

    for lead in leads:
        region = region_of(lead.get("state", ""))
        owner = OWNERSHIP.get(normalize_company(lead.get("company", "")))
        rep_id: Optional[str] = None
        if owner is not None and counts[owner] < REPS[owner]["capacity"]:
            rep_id, reason = owner, "account_owner"
        elif region is not None:
            picked = territory_pick(region)
            if picked is not None:
                rep_id = picked
                reason = ("owner_at_capacity_territory"
                          if owner is not None else "territory_round_robin")
            else:
                reason = "capacity_exhausted"
        elif owner is not None:
            reason = "capacity_exhausted"
        else:
            reason = "unknown_territory"
        if rep_id is not None:
            counts[rep_id] += 1
        assignments.append({"lead_id": lead.get("lead_id"),
                            "rep_id": rep_id, "reason": reason,
                            "region": region})
    return assignments


def route_payload(leads: List[Dict]) -> Dict:
    assignments = route_leads(leads)
    per_rep = {rep_id: 0 for rep_id in REPS}
    for a in assignments:
        if a["rep_id"] is not None:
            per_rep[a["rep_id"]] += 1
    return {
        "assignments": assignments,
        "summary": {
            "total": len(assignments),
            "assigned": sum(1 for a in assignments if a["rep_id"]),
            "unassigned": sum(1 for a in assignments if not a["rep_id"]),
            "per_rep": per_rep,
        },
    }


def routing_accuracy(assignments: List[Dict], golden: Dict) -> Dict:
    expected = {c["lead"]["lead_id"]: c["expected_rep"]
                for c in golden["cases"]}
    correct = sum(1 for a in assignments
                  if expected.get(a["lead_id"]) == a["rep_id"])
    total = len(golden["cases"])
    return {"correct": correct, "total": total,
            "accuracy": round(correct / total, 4) if total else 1.0}
