"""Golden evals for gtm-engineering-automation-kit.

SYNTHETIC DATA ONLY (fictional companies and people). Every eval is
deterministic: run_evals.py writes eval_report.json and the file
must be byte-identical across runs. No timestamps, ports, or temp
paths enter the report — only names, booleans, pinned counts and
values.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import (EXIT_ERROR, EXIT_FAIL, EXIT_OK, load_json_file,  # noqa: E402
                 load_records, main as cli_main, make_server)
from dedupe import (cluster_leads, dedupe_payload, is_duplicate,  # noqa: E402
                    normalize_company, pairs_of, truth_pairs)
from generator import (generate_crm_records, generate_ground_truth,  # noqa: E402
                       generate_leads, generate_routing_golden,
                       leads_to_jsonl)
from report import build_report  # noqa: E402
from router import route_leads, route_payload, routing_accuracy  # noqa: E402
from validation import validate_records, valid_records  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(ROOT, "fixtures")
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def main():
    print("== golden evals: gtm-engineering-automation-kit ==")
    leads = generate_leads()
    truth = generate_ground_truth()
    golden = generate_routing_golden()
    crm = generate_crm_records()
    by_id = {r["lead_id"]: r for r in leads}

    # E1: generator determinism (bytes pinned)
    text1 = leads_to_jsonl(generate_leads())
    text2 = leads_to_jsonl(generate_leads())
    md5 = hashlib.md5(text1.encode()).hexdigest()
    check("E1 generator determinism (seed=42, 33 messy leads)",
          text1 == text2 and len(leads) == 33
          and md5 == "d4d80634071976a1dddb5c59565c817d",
          f"jsonl_md5={md5}")

    # E2 (headline 1): dedupe precision / recall vs the labelled pairs.
    payload = dedupe_payload(leads, truth)
    m = payload["metrics"]
    check("E2 dedupe headline pinned (precision 1.0, recall 0.9412)",
          m["precision"] == 1.0 and m["recall"] == 0.9412
          and m["true_positives"] == 16 and m["false_positives"] == 0
          and m["false_negatives"] == 1 and payload["cluster_count"] == 20,
          f"precision={m['precision']} recall={m['recall']}")

    # E3 (headline 2): routing accuracy on the golden assignment set.
    golden_leads = [c["lead"] for c in golden["cases"]]
    acc = routing_accuracy(route_leads(golden_leads), golden)
    check("E3 routing golden accuracy pinned (13/13)",
          acc == {"correct": 13, "total": 13, "accuracy": 1.0},
          f"accuracy={acc['accuracy']}")

    # E4: schema gate — invalid rejected with per-field reasons; the
    # sink set is exactly the valid set.
    gate = validate_records(crm)
    by_cid = {r["lead_id"]: r for r in gate["results"]}
    check("E4 schema gate pinned (6 pass, 4 rejected, 1 reason each)",
          gate["valid_count"] == 6 and gate["invalid_count"] == 4
          and all(len(by_cid[c]["errors"]) == 1
                  for c in ("C007", "C008", "C009", "C010"))
          and by_cid["C007"]["errors"][0]["field"] == "email"
          and by_cid["C008"]["errors"][0]["field"] == "state"
          and by_cid["C009"]["errors"][0]["field"] == "source"
          and by_cid["C010"]["errors"][0]["field"] == "employees"
          and [r["lead_id"] for r in valid_records(crm)]
          == ["C001", "C002", "C003", "C004", "C005", "C006"],
          f"valid={gate['valid_count']} invalid={gate['invalid_count']}")

    # E5: normalisation pins — suffix / case / punctuation variants of
    # the same company collapse to one key.
    variants = ["Northwind Labs, Inc.", "NORTHWIND LABS", "Northwind Labs LLC",
                "northwind  labs!"]
    check("E5 company normalisation collapses variants",
          {normalize_company(v) for v in variants} == {"northwind labs"}
          and normalize_company("Acme Corp.") == "acme"
          and normalize_company("Acme Corporation") == "acme")

    # E6: ownership beats territory; an owner at capacity falls
    # through to the territory round-robin instead of dropping.
    owned = [{"lead_id": f"A{i}", "first_name": "A", "last_name": f"{i}",
              "email": f"a{i}@asterrobotics.com", "company": "Aster Robotics",
              "state": "NY", "source": "web"} for i in range(3)]
    owned.append({"lead_id": "A9", "first_name": "A", "last_name": "9",
                  "email": "a9@asterrobotics.com",
                  "company": "Aster Robotics", "state": "NY",
                  "source": "web"})
    got = route_leads(owned)
    check("E6 ownership override + at-capacity fallthrough",
          got[-1]["rep_id"] == "omar_haddad"
          and got[-1]["reason"] == "owner_at_capacity_territory"
          and all(a["rep_id"] == "cara_lind" for a in got[:-1]))

    # E7: capacity is a hard limit and round-robin alternates.
    west = [{"lead_id": f"W{i}", "first_name": "W", "last_name": f"{i}",
             "email": f"w{i}@quartzpeak.com",
             "company": "Quartz Peak Software", "state": "CA",
             "source": "web"} for i in range(8)]
    reps = [a["rep_id"] for a in route_leads(west)]
    check("E7 round-robin alternation + capacity hard limit (6 of 8)",
          reps == ["ana_ruiz", "sam_whitaker"] * 3 + [None, None],
          f"assigned={sum(1 for r in reps if r)}")

    # E8: hard negatives never merge, and the one known miss is the
    # ONLY missed pair (pinned limitation, not a hidden gap).
    clusters = cluster_leads(leads)
    missed = truth_pairs(truth) - pairs_of(clusters)
    extra = pairs_of(clusters) - truth_pairs(truth)
    check("E8 no false merges; single pinned miss (Kate/Katherine)",
          extra == set() and missed == {("L032", "L033")}
          and not is_duplicate(by_id["L025"], by_id["L026"]))

    # E9: CLI check exit codes 0 / 1 / 2.
    import tempfile
    tmp = tempfile.mkdtemp(prefix="gtm-evals-")
    leads_path = os.path.join(tmp, "leads.jsonl")
    with open(leads_path, "w", encoding="utf-8") as fh:
        fh.write(leads_to_jsonl(leads))
    codes = (_run_cli(["check", "--input", leads_path]),
             _run_cli(["check", "--input", leads_path,
                       "--min-recall", "0.99"]),
             _run_cli(["check", "--input", "/tmp/no-such-leads-xyz.jsonl"]))
    check("E9 CLI check exit codes 0/1/2",
          codes == (EXIT_OK, EXIT_FAIL, EXIT_ERROR), f"codes={codes}")

    # E10: serve round-trip matches local computation.
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                    timeout=10) as resp:
            health = json.loads(resp.read())

        def _post(path, payload):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())

        serve_ok = health == {"status": "ok"} \
            and _post("/route", {"leads": golden_leads}) \
            == route_payload(golden_leads) \
            and _post("/validate", {"records": crm}) == gate
    finally:
        server.shutdown()
        server.server_close()
    check("E10 serve round-trip matches local route + validate", serve_ok)

    # E11: bundled fixtures pinned (counts + generator equality).
    fixture_leads = load_records(os.path.join(FIXTURES, "leads.jsonl"))
    fixture_csv = load_records(os.path.join(FIXTURES, "leads.csv"))
    fixture_truth = load_json_file(os.path.join(FIXTURES, "ground_truth.json"))
    fixture_golden = load_json_file(os.path.join(FIXTURES, "routing_golden.json"))
    fixture_crm = load_records(os.path.join(FIXTURES, "crm_records.jsonl"))
    check("E11 fixtures pinned (33 leads, 17 pairs, 19 clusters, 10 CRM)",
          fixture_leads == leads and fixture_csv == leads
          and fixture_truth == truth and fixture_golden == golden
          and fixture_crm == crm
          and len(truth["pairs"]) == 17 and len(truth["clusters"]) == 19)

    # E12: report determinism — canonical JSON identical across builds.
    r1 = json.dumps(build_report(leads, truth, golden, crm), sort_keys=True)
    r2 = json.dumps(build_report(leads, truth, golden, crm), sort_keys=True)
    check("E12 report determinism (canonical JSON identical)",
          r1 == r2, f"report_md5={hashlib.md5(r1.encode()).hexdigest()}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total_count = len(RESULTS)
    summary_doc = {"passed": passed, "total": total_count,
                   "all_passed": passed == total_count, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_doc, sort_keys=True) + "\n")
    print(f"\n{passed}/{total_count} evals passed -> evals/eval_report.json")
    return 0 if passed == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
