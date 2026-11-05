import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import (EXIT_ERROR, EXIT_FAIL, EXIT_OK, load_records,
                 main as cli_main, make_server)
from generator import (crm_to_jsonl, generate_crm_records, generate_leads,
                       leads_to_jsonl)
from router import route_payload
from validation import validate_records


def _run(argv):
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        code = cli_main(argv)
    return code, out.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gtm-cli-")
        self.leads_path = os.path.join(self.tmp, "leads.jsonl")
        with open(self.leads_path, "w", encoding="utf-8") as fh:
            fh.write(leads_to_jsonl(generate_leads()))
        self.crm_path = os.path.join(self.tmp, "crm.jsonl")
        with open(self.crm_path, "w", encoding="utf-8") as fh:
            fh.write(crm_to_jsonl(generate_crm_records()))

    def test_load_csv_matches_jsonl(self):
        import generator
        csv_path = os.path.join(self.tmp, "leads.csv")
        with open(csv_path, "w", encoding="utf-8") as fh:
            fh.write(generator.leads_to_csv(generate_leads()))
        self.assertEqual(load_records(csv_path),
                         load_records(self.leads_path))

    def test_dedupe_command_with_truth(self):
        truth = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "fixtures", "ground_truth.json")
        code, text = _run(["dedupe", "--input", self.leads_path,
                           "--truth", truth])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(text)
        self.assertEqual(payload["metrics"]["precision"], 1.0)
        self.assertEqual(payload["metrics"]["recall"], 0.9412)

    def test_dedupe_command_without_truth(self):
        code, text = _run(["dedupe", "--input", self.leads_path])
        self.assertEqual(code, EXIT_OK)
        self.assertIsNone(json.loads(text)["metrics"])

    def test_route_command(self):
        code, text = _run(["route", "--input", self.leads_path])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(text)
        self.assertEqual(payload["summary"]["total"], 33)

    def test_validate_command_and_sink(self):
        sink = os.path.join(self.tmp, "sink.json")
        code, text = _run(["validate", "--input", self.crm_path,
                           "--sink", sink])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(text)
        self.assertEqual((payload["valid_count"],
                          payload["invalid_count"]), (6, 4))
        with open(sink, encoding="utf-8") as fh:
            sunk = json.loads(fh.read())
        self.assertEqual(len(sunk), 6)

    def test_report_command(self):
        code, text = _run(["report", "--input", self.leads_path])
        self.assertEqual(code, EXIT_OK)
        report = json.loads(text)
        self.assertEqual(report["routing"]["accuracy"], 1.0)
        self.assertIn("Schema gate: 6 of 10", report["narrative"])

    def test_check_exit_codes(self):
        code, _ = _run(["check", "--input", self.leads_path])
        self.assertEqual(code, EXIT_OK)
        code, _ = _run(["check", "--input", self.leads_path,
                        "--min-recall", "0.99"])
        self.assertEqual(code, EXIT_FAIL)
        code, _ = _run(["check", "--input", "/tmp/no-such-leads-xyz.jsonl"])
        self.assertEqual(code, EXIT_ERROR)

    def test_missing_input_is_exit_2(self):
        code, _ = _run(["dedupe", "--input", "/tmp/nope-xyz.jsonl"])
        self.assertEqual(code, EXIT_ERROR)


class TestServe(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _req(self, path, payload=None, method="GET"):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health(self):
        status, body = self._req("/health")
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_post_route_matches_local(self):
        leads = generate_leads()[:6]
        status, body = self._req("/route", {"leads": leads}, method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(body, route_payload(leads))

    def test_post_validate_matches_local(self):
        records = generate_crm_records()
        status, body = self._req("/validate", {"records": records},
                                 method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(body, validate_records(records))

    def test_unknown_endpoint_404(self):
        status, _ = self._req("/nope")
        self.assertEqual(status, 404)
        status, _ = self._req("/route")  # GET not supported
        self.assertEqual(status, 404)

    def test_bad_body_400(self):
        status, body = self._req("/route", {"wrong": []}, method="POST")
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
