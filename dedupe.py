"""Deduplication / entity resolution for messy lead records.

Pipeline: normalise (case, punctuation, email domain, company
suffixes such as Inc / LLC), apply pairwise matching rules, then
cluster with union-find. Quality is scored against the labelled
ground truth as pair precision / recall — a predicted pair counts
only if both records truly are the same person.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

# Legal / corporate suffixes that carry no identity signal.
COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation",
                    "co", "company", "group", "holdings"}

# Fixed, deliberately small nickname map (canonical -> variants are
# stored variant -> canonical). Anything outside this map (e.g.
# Kate / Katherine) is NOT resolved — a documented limit, pinned by
# the evals as a recall miss rather than patched with a one-off rule.
NICKNAMES = {"bob": "robert", "rob": "robert", "tom": "thomas",
             "mike": "michael", "dave": "david", "jim": "james",
             "liz": "elizabeth"}

# Free-mail domains say nothing about which company a lead is from.
GENERIC_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com",
                   "hotmail.com", "icloud.com"}

_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _clean(text) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(_PUNCT.sub(" ", text.lower()).split())


def normalize_company(name) -> str:
    """Lowercase, drop punctuation, strip trailing legal suffixes."""
    tokens = _clean(name).split()
    while tokens and tokens[-1] in COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_email(email) -> str:
    if not isinstance(email, str):
        return ""
    return email.strip().lower()


def email_domain(email) -> str:
    norm = normalize_email(email)
    if "@" not in norm:
        return ""
    return norm.rsplit("@", 1)[1]


def normalize_name_part(part) -> str:
    return _clean(part)


def full_name(record: Dict) -> str:
    first = normalize_name_part(record.get("first_name", ""))
    last = normalize_name_part(record.get("last_name", ""))
    return " ".join(p for p in (first, last) if p)


def canonical_first(first_norm: str) -> str:
    return NICKNAMES.get(first_norm, first_norm)


def canonical_full_name(record: Dict) -> str:
    first = canonical_first(normalize_name_part(record.get("first_name", "")))
    last = normalize_name_part(record.get("last_name", ""))
    return " ".join(p for p in (first, last) if p)


def levenshtein(a: str, b: str) -> int:
    """Classic edit distance (insert / delete / substitute)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (0 if ca == cb else 1)))
        prev = cur
    return prev[-1]


def is_duplicate(a: Dict, b: Dict) -> bool:
    """Pairwise matching rules, in order. Company identity is the
    anchor: a name match alone never merges (two different companies
    can employ two people with the same name)."""
    ea, eb = normalize_email(a.get("email", "")), normalize_email(b.get("email", ""))
    if ea and ea == eb:
        return True
    ca, cb = normalize_company(a.get("company", "")), normalize_company(b.get("company", ""))
    na, nb = full_name(a), full_name(b)
    if ca and ca == cb and na and nb:
        if na == nb or canonical_full_name(a) == canonical_full_name(b):
            return True
        la = normalize_name_part(a.get("last_name", ""))
        lb = normalize_name_part(b.get("last_name", ""))
        fa = normalize_name_part(a.get("first_name", ""))
        fb = normalize_name_part(b.get("first_name", ""))
        # Initial for a first name ("J." Ellis) with the same surname.
        if la and la == lb and fa and fb \
                and (fa[0] == fb[0]) and (len(fa) == 1 or len(fb) == 1):
            return True
        # One-edit typo in the full name at the same company.
        if levenshtein(na, nb) <= 1:
            return True
    da, db = email_domain(a.get("email", "")), email_domain(b.get("email", ""))
    if da and da == db and da not in GENERIC_DOMAINS and na and na == nb:
        return True
    return False


class _UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[max(rx, ry)] = min(rx, ry)


def cluster_leads(records: List[Dict]) -> List[List[str]]:
    """Transitive clusters of lead_ids, sorted deterministically."""
    ids = [r["lead_id"] for r in records]
    uf = _UnionFind(ids)
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if is_duplicate(records[i], records[j]):
                uf.union(ids[i], ids[j])
    groups: Dict[str, List[str]] = {}
    for lead_id in ids:
        groups.setdefault(uf.find(lead_id), []).append(lead_id)
    clusters = [sorted(members) for members in groups.values()]
    clusters.sort(key=lambda members: members[0])
    return clusters


def pairs_of(clusters: List[List[str]]) -> Set[Tuple[str, str]]:
    pairs: Set[Tuple[str, str]] = set()
    for members in clusters:
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pairs.add((members[i], members[j]))
    return pairs


def truth_pairs(truth: Dict) -> Set[Tuple[str, str]]:
    return {(a, b) for a, b in truth["pairs"]}


def pair_metrics(predicted: Set[Tuple[str, str]],
                 truth: Set[Tuple[str, str]]) -> Dict:
    tp = len(predicted & truth)
    fp = len(predicted - truth)
    fn = len(truth - predicted)
    precision = round(tp / (tp + fp), 4) if (tp + fp) else 1.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) else 1.0
    return {"precision": precision, "recall": recall,
            "true_positives": tp, "false_positives": fp,
            "false_negatives": fn}


def dedupe_payload(records: List[Dict], truth: Dict = None) -> Dict:
    clusters = cluster_leads(records)
    payload = {
        "record_count": len(records),
        "cluster_count": len(clusters),
        "clusters": [
            {"cluster": f"D{idx + 1}", "lead_ids": members,
             "size": len(members)}
            for idx, members in enumerate(clusters)
        ],
        "metrics": None,
    }
    if truth is not None:
        payload["metrics"] = pair_metrics(pairs_of(clusters),
                                          truth_pairs(truth))
    return payload
