"""CLI: dedupe | route | validate | report | check | demo | serve.

SYNTHETIC DATA ONLY — every dataset handled here is fabricated
sample data (fictional companies and people).

Exit codes:
  check : 0 = pass, 1 = quality breach (dedupe precision / recall or
          routing accuracy below its threshold), 2 = usage / IO error
  others: 0 = success, 2 = usage / IO error
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dedupe import dedupe_payload  # noqa: E402
from report import build_report  # noqa: E402
from router import route_payload  # noqa: E402
from validation import validate_records, write_sink  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2
DEFAULT_MIN_PRECISION = 0.90
DEFAULT_MIN_RECALL = 0.90
DEFAULT_MIN_ROUTING = 0.90

_HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_TRUTH = os.path.join(_HERE, "fixtures", "ground_truth.json")
FIXTURE_GOLDEN = os.path.join(_HERE, "fixtures", "routing_golden.json")
FIXTURE_CRM = os.path.join(_HERE, "fixtures", "crm_records.jsonl")


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def _coerce(row: Dict) -> Dict:
    out = dict(row)
    value = out.get("employees")
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        out["employees"] = int(value.strip())
    return out


def load_records(path: str) -> List[Dict]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    stripped = text.strip()
    if not stripped:
        return []
    if path.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        return [_coerce(dict(row)) for row in reader]
    if stripped.startswith("["):
        return [_coerce(dict(x)) for x in json.loads(stripped)]
    return [_coerce(json.loads(line))
            for line in stripped.splitlines() if line.strip()]


def load_json_file(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _load_or_error(path: str) -> Optional[List[Dict]]:
    try:
        return load_records(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
    return None


def _load_json_or_error(path: str):
    try:
        return load_json_file(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
    return None


def _write_out(args, payload, summary: str) -> int:
    text = canonical(payload) + "\n"
    if getattr(args, "out", None):
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(summary)
    else:
        print(text, end="")
    return EXIT_OK


def cmd_dedupe(args) -> int:
    rows = _load_or_error(args.input)
    if rows is None:
        return EXIT_ERROR
    truth = None
    if args.truth:
        truth = _load_json_or_error(args.truth)
        if truth is None:
            return EXIT_ERROR
    payload = dedupe_payload(rows, truth)
    return _write_out(args, payload,
                      f"dedupe: {payload['record_count']} records -> "
                      f"{payload['cluster_count']} clusters -> {args.out}")


def cmd_route(args) -> int:
    rows = _load_or_error(args.input)
    if rows is None:
        return EXIT_ERROR
    payload = route_payload(rows)
    return _write_out(args, payload,
                      f"route: {payload['summary']['assigned']}/"
                      f"{payload['summary']['total']} assigned -> {args.out}")


def cmd_validate(args) -> int:
    rows = _load_or_error(args.input)
    if rows is None:
        return EXIT_ERROR
    payload = validate_records(rows)
    if getattr(args, "sink", None):
        try:
            clean = write_sink(rows, args.sink)
        except OSError as exc:
            print(f"error: cannot write sink {args.sink}: {exc}",
                  file=sys.stderr)
            return EXIT_ERROR
        payload = dict(payload)
        payload["sink"] = {"path": os.path.basename(args.sink),
                           "written": len(clean)}
    return _write_out(args, payload,
                      f"validate: {payload['valid_count']} valid, "
                      f"{payload['invalid_count']} rejected -> {args.out}")


def _load_report_inputs(args):
    rows = _load_or_error(args.input)
    if rows is None:
        return None
    truth = _load_json_or_error(args.truth)
    golden = _load_json_or_error(args.golden)
    crm = _load_or_error(args.crm)
    if truth is None or golden is None or crm is None:
        return None
    return rows, truth, golden, crm


def cmd_report(args) -> int:
    loaded = _load_report_inputs(args)
    if loaded is None:
        return EXIT_ERROR
    rows, truth, golden, crm = loaded
    report = build_report(rows, truth, golden, crm)
    return _write_out(args, report, f"report -> {args.out}")


def cmd_check(args) -> int:
    loaded = _load_report_inputs(args)
    if loaded is None:
        return EXIT_ERROR
    rows, truth, golden, crm = loaded
    report = build_report(rows, truth, golden, crm)
    m = report["dedupe"]["metrics"]
    acc = report["routing"]["accuracy"]
    print(f"records={report['dedupe']['record_count']} "
          f"precision={m['precision']} recall={m['recall']} "
          f"routing_accuracy={acc} "
          f"gate_valid={report['gate']['valid_count']}/"
          f"{report['gate']['valid_count'] + report['gate']['invalid_count']}")
    breaches = []
    if m["precision"] < args.min_precision:
        breaches.append(f"precision {m['precision']} below "
                        f"{args.min_precision}")
    if m["recall"] < args.min_recall:
        breaches.append(f"recall {m['recall']} below {args.min_recall}")
    if acc < args.min_routing_accuracy:
        breaches.append(f"routing accuracy {acc} below "
                        f"{args.min_routing_accuracy}")
    if breaches:
        for breach in breaches:
            print(f"check FAIL: {breach}")
        return EXIT_FAIL
    print("check PASS")
    return EXIT_OK


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


# ------------------------------------------------------------------- serve

class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: Any) -> None:
        body = (canonical(payload) + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw.strip() else {}
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    @staticmethod
    def _records_of(body: Dict, keys) -> List[Dict]:
        for key in keys:
            if key in body:
                value = body[key]
                if isinstance(value, dict):
                    return [_coerce(value)]
                return [_coerce(dict(x)) for x in value]
        raise ValueError(f"body must contain one of {list(keys)}")

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        return self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):  # noqa: N802
        try:
            if self.path == "/route":
                leads = self._records_of(self._read_body(), ("leads", "lead"))
                return self._send_json(200, route_payload(leads))
            if self.path == "/validate":
                records = self._records_of(self._read_body(),
                                           ("records", "leads", "record"))
                return self._send_json(200, validate_records(records))
            return self._send_json(404, {"error": "unknown endpoint"})
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json(400, {"error": f"bad request: {exc}"})

    def log_message(self, *a: Any) -> None:
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args) -> int:
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  "
          f"(POST /route, POST /validate, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gtm-engineering-automation-kit",
        description="Go-to-market engineering automation: lead dedupe, "
                    "rules-based routing, schema contract gate "
                    "(synthetic sample data only).")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dedupe", help="deduplicate leads; score vs truth")
    d.add_argument("--input", required=True)
    d.add_argument("--truth", default=None)
    d.add_argument("--out", default=None)
    d.set_defaults(func=cmd_dedupe)

    r = sub.add_parser("route", help="route leads to reps by the rules")
    r.add_argument("--input", required=True)
    r.add_argument("--out", default=None)
    r.set_defaults(func=cmd_route)

    v = sub.add_parser("validate", help="schema gate; optionally write sink")
    v.add_argument("--input", required=True)
    v.add_argument("--sink", default=None)
    v.add_argument("--out", default=None)
    v.set_defaults(func=cmd_validate)

    rp = sub.add_parser("report", help="combined dedupe/route/gate report")
    rp.add_argument("--input", required=True)
    rp.add_argument("--truth", default=FIXTURE_TRUTH)
    rp.add_argument("--golden", default=FIXTURE_GOLDEN)
    rp.add_argument("--crm", default=FIXTURE_CRM)
    rp.add_argument("--out", default=None)
    rp.set_defaults(func=cmd_report)

    c = sub.add_parser("check", help="CI gate: exit 0 pass / 1 breach / 2 error")
    c.add_argument("--input", required=True)
    c.add_argument("--truth", default=FIXTURE_TRUTH)
    c.add_argument("--golden", default=FIXTURE_GOLDEN)
    c.add_argument("--crm", default=FIXTURE_CRM)
    c.add_argument("--min-precision", type=float, default=DEFAULT_MIN_PRECISION)
    c.add_argument("--min-recall", type=float, default=DEFAULT_MIN_RECALL)
    c.add_argument("--min-routing-accuracy", type=float,
                   default=DEFAULT_MIN_ROUTING)
    c.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="localhost JSON API")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
