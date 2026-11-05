"""End-to-end demo: load messy leads -> dedupe -> route -> validate
-> report -> check -> serve.

SYNTHETIC DATA ONLY (fictional companies and people). Runs fully
offline; the serve round-trip is loopback-only on an ephemeral port.
Every stage asserts.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import (EXIT_FAIL, EXIT_OK, load_json_file, load_records,  # noqa: E402
                 main as cli_main, make_server)
from dedupe import dedupe_payload  # noqa: E402
from generator import (crm_to_jsonl, generate_crm_records,  # noqa: E402
                       generate_ground_truth, generate_leads,
                       generate_routing_golden, leads_to_jsonl)
from report import build_report  # noqa: E402
from router import route_leads, route_payload, routing_accuracy  # noqa: E402
from validation import validate_records, write_sink  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")


def _request(port: int, path: str, payload=None, method: str = "GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> None:
    print("== 1. messy leads: generator determinism + bundled fixtures ==")
    leads = generate_leads()
    assert leads == generate_leads(), "generator must be deterministic"
    fixture_leads = load_records(os.path.join(FIXTURES, "leads.jsonl"))
    assert fixture_leads == leads, "fixture leads must match the generator"
    truth = load_json_file(os.path.join(FIXTURES, "ground_truth.json"))
    assert truth == generate_ground_truth()
    golden = load_json_file(os.path.join(FIXTURES, "routing_golden.json"))
    assert golden == generate_routing_golden()
    crm = load_records(os.path.join(FIXTURES, "crm_records.jsonl"))
    assert crm == generate_crm_records()
    print(f"   {len(leads)} messy leads, {len(truth['pairs'])} labelled "
          f"duplicate pairs across {len(truth['clusters'])} true clusters")

    print("\n== 2. dedupe: normalise -> match -> cluster, scored vs truth ==")
    payload = dedupe_payload(leads, truth)
    m = payload["metrics"]
    assert payload["cluster_count"] == 20, payload["cluster_count"]
    assert m["precision"] == 1.0 and m["recall"] == 0.9412, m
    print(f"   precision={m['precision']} recall={m['recall']} "
          f"(tp={m['true_positives']} fp={m['false_positives']} "
          f"fn={m['false_negatives']} — the one miss is the pinned "
          f"Kate/Katherine + 'Ptrs' pair, see README)")

    print("\n== 3. routing: ownership -> territory round-robin -> capacity ==")
    golden_leads = [c["lead"] for c in golden["cases"]]
    assignments = route_leads(golden_leads)
    acc = routing_accuracy(assignments, golden)
    assert acc == {"correct": 13, "total": 13, "accuracy": 1.0}, acc
    for a in assignments:
        print(f"   {a['lead_id']} -> {a['rep_id']} ({a['reason']})")

    print("\n== 4. schema gate: 6 clean pass, 4 rejected with reasons ==")
    gate = validate_records(crm)
    assert gate["valid_count"] == 6 and gate["invalid_count"] == 4, gate
    for result in gate["results"]:
        if not result["valid"]:
            reasons = "; ".join(f"{e['field']}: {e['reason']}"
                                for e in result["errors"])
            print(f"   {result['lead_id']} REJECTED — {reasons}")
    tmp = tempfile.mkdtemp(prefix="gtm-demo-")
    sink_path = os.path.join(tmp, "crm_sink.json")
    written = write_sink(crm, sink_path)
    assert [r["lead_id"] for r in written] == \
        ["C001", "C002", "C003", "C004", "C005", "C006"]
    print(f"   sink holds only the {len(written)} valid records")

    print("\n== 5. combined report: deterministic narrative ==")
    report = build_report(leads, truth, golden, crm)
    assert report == build_report(leads, truth, golden, crm)
    print("   " + report["narrative"])

    print("\n== 6. CLI check gate exit codes ==")
    leads_path = os.path.join(tmp, "leads.jsonl")
    with open(leads_path, "w", encoding="utf-8") as fh:
        fh.write(leads_to_jsonl(leads))
    code_ok = cli_main(["check", "--input", leads_path])
    code_breach = cli_main(["check", "--input", leads_path,
                            "--min-recall", "0.99"])
    code_err = cli_main(["check", "--input", "/tmp/no-such-leads-xyz.jsonl"])
    print(f"   normal={code_ok} impossible-threshold={code_breach} "
          f"missing-file={code_err}")
    assert code_ok == EXIT_OK and code_breach == EXIT_FAIL and code_err == 2
    assert crm_to_jsonl(crm).startswith('{"company": "Northwind Labs"')

    print("\n== 7. live localhost serve round-trip ==")
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, health = _request(port, "/health")
        assert status == 200 and health == {"status": "ok"}
        status, served = _request(port, "/route",
                                  payload={"leads": golden_leads},
                                  method="POST")
        assert status == 200 and served == route_payload(golden_leads)
        status, served_gate = _request(port, "/validate",
                                       payload={"records": crm},
                                       method="POST")
        assert status == 200 and served_gate == gate
        print("   POST /route and POST /validate match local computation")
    finally:
        server.shutdown()
        server.server_close()

    print("\nDemo OK: dedupe, route, validate, report, check and serve "
          "verified.")


if __name__ == "__main__":
    main()
