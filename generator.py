"""Deterministic synthetic messy-lead generator + ground truth.

SYNTHETIC DATA ONLY — every company, person and email here is
fictional, invented for this project. No real lead, customer or CRM
data is used anywhere.

The generator emits three fixture families:

* messy leads (33 records) — name variants, email/domain variants,
  company-name variants, typos and missing fields, arranged in 10
  duplicate clusters, 8 hard singletons and 1 deliberately hard
  duplicate pair the matcher is *expected* to miss (see README).
* a labelled ground truth (clusters + duplicate pairs) the dedupe
  evals score precision / recall against.
* a golden routing set (13 cases) and a CRM-record set for the
  schema gate (6 clean + 4 invalid, one defect each).
"""

from __future__ import annotations

import csv
import io
import json
import random
from typing import Dict, List

LEAD_FIELDS = ["lead_id", "first_name", "last_name", "email",
               "company", "state", "source"]


def _lead(lead_id, first, last, email, company, state, source):
    return {"lead_id": lead_id, "first_name": first, "last_name": last,
            "email": email, "company": company, "state": state,
            "source": source}


# Each inner list is one TRUE duplicate cluster: the same fictional
# person, re-entered with the kind of mess a real CRM accumulates.
_CLUSTERS = [
    ("maya_chen", [
        _lead("L001", "Maya", "Chen", "maya.chen@northwindlabs.com",
              "Northwind Labs, Inc.", "CA", "web"),
        _lead("L002", "MAYA", "CHEN", "maya_chen@northwindlabs.com",
              "Northwind Labs", "CA", "referral"),
        # Typo in the surname and a missing email.
        _lead("L003", "Maya", "Chan", "", "Northwind Labs LLC", "CA", "event"),
    ]),
    ("jordan_ellis", [
        _lead("L004", "Jordan", "Ellis", "jordan.ellis@brightpathhealth.com",
              "Brightpath Health", "NY", "web"),
        _lead("L005", "Jordan", "Ellis", "jordan.ellis@brightpathhealth.com",
              "Brightpath Health, Inc.", "NY", "outbound"),
        # Initial instead of a first name.
        _lead("L006", "J.", "Ellis", "jellis@brightpathhealth.com",
              "Brightpath Health", "NY", "partner"),
    ]),
    ("priya_nair", [
        _lead("L007", "Priya", "Nair", "priya.nair@cloudhaven.io",
              "Cloudhaven Systems, Inc.", "WA", "web"),
        # Email domain variant (.io vs .com); name + company carry it.
        _lead("L008", "Priya", "Nair", "priya.nair@cloudhaven.com",
              "Cloudhaven Systems", "WA", "web"),
    ]),
    ("marcus_webb", [
        _lead("L009", "Marcus", "Webb", "marcus.webb@summitridge.com",
              "Summit Ridge Consulting", "TX", "referral"),
        # Typo in the surname; the exact email match carries it.
        _lead("L010", "Marcus", "Web", "marcus.webb@summitridge.com",
              "Summit Ridge Consulting LLC", "TX", "referral"),
    ]),
    ("sofia_alvarez", [
        _lead("L011", "Sofia", "Alvarez", "sofia.alvarez@lumenfield.com",
              "Lumenfield Media", "FL", "event"),
        _lead("L012", "Sofia", "Alvarez", "sofia.alvarez@lumenfield.com",
              "Lumenfield Media, Inc.", "FL", "web"),
        _lead("L013", "Sofia", "Alvares", "sofia.alvares@lumenfield.com",
              "Lumenfield Media", "FL", "event"),
    ]),
    ("david_kim", [
        _lead("L014", "David", "Kim", "david.kim@asterrobotics.com",
              "Aster Robotics", "CA", "outbound"),
        _lead("L015", "David", "Kim", "d.kim@asterrobotics.com",
              "Aster Robotics, Inc.", "CA", "web"),
    ]),
    ("elena_petrova", [
        _lead("L016", "Elena", "Petrova", "elena.petrova@verdantenergy.com",
              "Verdant Energy", "CO", "web"),
        _lead("L017", "Elena", "Petrova", "elena.petrova@verdantenergy.com",
              "Verdant Energy LLC", "CO", "partner"),
    ]),
    ("robert_hargrove", [
        _lead("L018", "Robert", "Hargrove", "robert.hargrove@ironpeak.com",
              "Ironpeak Manufacturing", "IL", "outbound"),
        # Nickname variant (Bob for Robert).
        _lead("L019", "Bob", "Hargrove", "bob.hargrove@ironpeak.com",
              "Ironpeak Manufacturing", "IL", "referral"),
    ]),
    ("aisha_bello", [
        _lead("L020", "Aisha", "Bello", "aisha.bello@harborline.com",
              "Harborline Logistics", "GA", "web"),
        _lead("L021", "Aisha", "Bello", "aisha.bello@harborline.com",
              "Harborline Logistics, Inc.", "GA", "event"),
    ]),
    ("thomas_reed", [
        _lead("L022", "Thomas", "Reed", "thomas.reed@blueslate.com",
              "Blueslate Finance", "MA", "web"),
        _lead("L023", "Tom", "Reed", "tom.reed@blueslate.com",
              "Blueslate Finance", "MA", "referral"),
    ]),
    # The deliberately hard pair: a nickname the fixed nickname map
    # does not cover (Kate / Katherine) AND an abbreviated company
    # name ("Ptrs"). The matcher misses it; the eval pins the miss
    # instead of hiding it (recall 16/17, not 17/17).
    ("katherine_voss", [
        _lead("L032", "Katherine", "Voss", "katherine.voss@silveroak.com",
              "Silveroak Partners", "CA", "web"),
        _lead("L033", "Kate", "Voss", "kate.v@silveroak.com",
              "Silveroak Ptrs", "CA", "referral"),
    ]),
]

# Singletons — including the hard negatives: same company, different
# person (L024 vs the Maya Chen cluster; L027, L029, L030, L031) and
# the same name at two different companies (L025 / L026). A correct
# matcher merges NONE of these.
_SINGLETONS = [
    ("derek_shaw", _lead("L024", "Derek", "Shaw", "derek.shaw@northwindlabs.com",
                         "Northwind Labs", "WA", "web")),
    ("alex_morgan_verdant", _lead("L025", "Alex", "Morgan",
                                  "alex.morgan@verdantenergy.com",
                                  "Verdant Energy", "OR", "web")),
    ("alex_morgan_cloudhaven", _lead("L026", "Alex", "Morgan",
                                     "alex.morgan@cloudhaven.io",
                                     "Cloudhaven Systems", "WA", "web")),
    ("hannah_brooks", _lead("L027", "Hannah", "Brooks",
                            "hannah.brooks@summitridge.com",
                            "Summit Ridge Consulting", "TX", "event")),
    ("chris_novak", _lead("L028", "Chris", "Novak", "chris.novak@pinecrest.com",
                          "Pinecrest Legal", "NJ", "outbound")),
    ("fatima_sy", _lead("L029", "Fatima", "Sy", "fatima.sy@harborline.com",
                        "Harborline Logistics", "GA", "partner")),
    ("liam_ortiz", _lead("L030", "Liam", "Ortiz", "liam.ortiz@blueslate.com",
                         "Blueslate Finance", "MA", "web")),
    ("nina_park", _lead("L031", "Nina", "Park", "nina.park@ironpeak.com",
                        "Ironpeak Manufacturing", "IL", "referral")),
]


def _all_leads_in_order() -> List[Dict]:
    rows: List[Dict] = []
    for _name, members in _CLUSTERS:
        rows.extend(dict(m) for m in members)
    for _name, member in _SINGLETONS:
        rows.append(dict(member))
    return rows


def generate_leads(seed: int = 42) -> List[Dict]:
    """The 33 messy leads, deterministically shuffled by ``seed``.

    The shuffle only changes row order (as a CRM export would); ids,
    clusters and metrics are unaffected.
    """
    rows = _all_leads_in_order()
    random.Random(seed).shuffle(rows)
    return rows


def generate_ground_truth() -> Dict:
    clusters: Dict[str, List[str]] = {}
    for name, members in _CLUSTERS:
        clusters[name] = sorted(m["lead_id"] for m in members)
    for name, member in _SINGLETONS:
        clusters["single_" + name] = [member["lead_id"]]
    pairs = []
    for ids in clusters.values():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.append([ids[i], ids[j]])
    pairs.sort()
    return {"clusters": dict(sorted(clusters.items())), "pairs": pairs}


def leads_to_jsonl(rows: List[Dict]) -> str:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)


def leads_to_csv(rows: List[Dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=LEAD_FIELDS)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in LEAD_FIELDS})
    return buf.getvalue()


# ------------------------------------------------------------ routing

def _golden(lead_id, first, last, email, company, state, rep, note):
    lead = _lead(lead_id, first, last, email, company, state, "web")
    return {"lead": lead, "expected_rep": rep, "note": note}


def generate_routing_golden() -> Dict:
    cases = [
        _golden("G01", "Dana", "Whitfield", "dana.whitfield@asterrobotics.com",
                "Aster Robotics", "CA", "cara_lind",
                "account ownership beats west territory"),
        _golden("G02", "Peter", "Lang", "peter.lang@quartzpeak.com",
                "Quartz Peak Software", "WA", "ana_ruiz",
                "west round-robin pick 1"),
        _golden("G03", "Lucia", "Gomez", "lucia.gomez@quartzpeak.com",
                "Quartz Peak Software", "CA", "sam_whitaker",
                "west round-robin pick 2 — unowned accounts do not stick"),
        _golden("G04", "Nora", "Fields", "nora.fields@quartzpeak.com",
                "Quartz Peak Software", "OR", "ana_ruiz",
                "west round-robin pick 3 wraps to the first rep"),
        _golden("G05", "Hank", "Doyle", "hank.doyle@lonestar.com",
                "Lone Star Analytics", "TX", "ben_osei",
                "central round-robin pick 1"),
        _golden("G06", "Ruth", "Adler", "ruth.adler@northwindlabs.com",
                "Northwind Labs", "IL", "ben_osei",
                "account ownership beats central round-robin"),
        _golden("G07", "Omar", "Reyes", "omar.reyes@lonestar.com",
                "Lone Star Analytics", "TX", "nina_kowalski",
                "central round-robin pick 2"),
        _golden("G08", "Emily", "Zhang", "emily.zhang@hudsonlegal.com",
                "Hudson Legal Group", "NY", "cara_lind",
                "east round-robin pick 1"),
        _golden("G09", "Victor", "Chen", "victor.chen@asterrobotics.com",
                "Aster Robotics", "MA", "cara_lind",
                "ownership again; cara_lind reaches capacity exactly"),
        _golden("G10", "Grace", "Nolan", "grace.nolan@hudsonlegal.com",
                "Hudson Legal Group", "NJ", "omar_haddad",
                "east round-robin pick 2"),
        _golden("G11", "Carlos", "Mendez", "carlos.mendez@palmettotravel.com",
                "Palmetto Travel", "FL", "devon_park",
                "south round-robin pick 1"),
        _golden("G12", "Beth", "Sullivan", "beth.sullivan@palmettotravel.com",
                "Palmetto Travel", "GA", "grace_liu",
                "south round-robin pick 2"),
        _golden("G13", "Ivan", "Petrov", "ivan.petrov@quartzpeak.com",
                "Quartz Peak Software", "XX", None,
                "unknown territory is unassigned, never guessed"),
    ]
    return {"cases": cases}


# ------------------------------------------------------------- schema

def _crm(lead_id, first, last, email, company, state, source, employees):
    rec = _lead(lead_id, first, last, email, company, state, source)
    rec["employees"] = employees
    return rec


def generate_crm_records() -> List[Dict]:
    """10 CRM-write candidates: 6 clean, 4 invalid (one defect each)."""
    clean = [
        _crm("C001", "Maya", "Chen", "maya.chen@northwindlabs.com",
             "Northwind Labs", "CA", "web", 120),
        _crm("C002", "Jordan", "Ellis", "jordan.ellis@brightpathhealth.com",
             "Brightpath Health", "NY", "referral", 45),
        _crm("C003", "Priya", "Nair", "priya.nair@cloudhaven.io",
             "Cloudhaven Systems", "WA", "web", 300),
        _crm("C004", "Marcus", "Webb", "marcus.webb@summitridge.com",
             "Summit Ridge Consulting", "TX", "outbound", 18),
        _crm("C005", "Sofia", "Alvarez", "sofia.alvarez@lumenfield.com",
             "Lumenfield Media", "FL", "event", 60),
        _crm("C006", "David", "Kim", "david.kim@asterrobotics.com",
             "Aster Robotics", "CA", "partner", 85),
    ]
    missing_email = _crm("C007", "Elena", "Petrova",
                         "elena.petrova@verdantenergy.com",
                         "Verdant Energy", "CO", "web", 210)
    del missing_email["email"]
    bad_state = _crm("C008", "Aisha", "Bello", "aisha.bello@harborline.com",
                     "Harborline Logistics", "XX", "web", 95)
    bad_source = _crm("C009", "Thomas", "Reed", "thomas.reed@blueslate.com",
                      "Blueslate Finance", "MA", "carrier-pigeon", 40)
    bad_employees = _crm("C010", "Nina", "Park", "nina.park@ironpeak.com",
                         "Ironpeak Manufacturing", "IL", "referral", "many")
    return clean + [missing_email, bad_state, bad_source, bad_employees]


def crm_to_jsonl(rows: List[Dict]) -> str:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
