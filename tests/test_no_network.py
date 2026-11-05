"""No-network enforcement: with sockets blocked, deduping, routing,
validating and reporting must all still work. (``serve`` is the only
intentional exception — it binds loopback on demand, and is not used
here.)"""

import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Blocker:
    def __init__(self, *a, **k):
        raise RuntimeError("network access blocked in hermetic test")


class TestNoNetwork(unittest.TestCase):
    def setUp(self):
        self._real_socket = socket.socket
        socket.socket = _Blocker
        import urllib.request as urlreq
        self._real_urlopen = urlreq.urlopen
        urlreq.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("network access blocked in hermetic test"))

    def tearDown(self):
        socket.socket = self._real_socket
        import urllib.request as urlreq
        urlreq.urlopen = self._real_urlopen

    def test_full_pipeline_offline(self):
        from dedupe import dedupe_payload
        from generator import (generate_crm_records, generate_ground_truth,
                               generate_leads, generate_routing_golden)
        from report import build_report
        leads = generate_leads()
        payload = dedupe_payload(leads, generate_ground_truth())
        self.assertEqual(payload["metrics"]["precision"], 1.0)
        report = build_report(leads, generate_ground_truth(),
                              generate_routing_golden(),
                              generate_crm_records())
        self.assertEqual(report["routing"]["accuracy"], 1.0)

    def test_no_module_opens_sockets_at_import(self):
        for mod in ("generator", "dedupe", "router", "validation",
                    "report", "cli", "demo"):
            sys.modules.pop(mod, None)
        import cli, dedupe, demo, generator, report, router  # noqa: F401
        import validation  # noqa: F401
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
