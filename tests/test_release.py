import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "advanced"))

import capture
import demo_config
import run_evidence


class ConfigurationTests(unittest.TestCase):
    def test_endpoint_requires_explicit_https_workspace_origin(self):
        invalid = [
            "", "http://example.grafana.azure.com",
            "https://example.com", "https://example.grafana.azure.com/path",
            "https://user:password@example.grafana.azure.com",
            "https://example.grafana.azure.com?token=example",
        ]
        for value in invalid:
            with self.subTest(value=value), patch.dict(os.environ, {"ACNS_GRAFANA_ENDPOINT": value}):
                with self.assertRaises(ValueError):
                    demo_config.endpoint_from_env("ACNS_GRAFANA_ENDPOINT", ".grafana.azure.com")

    def test_endpoint_accepts_base_url_with_trailing_slash(self):
        with patch.dict(os.environ, {"ACNS_GRAFANA_ENDPOINT": "https://example.grafana.azure.com/"}):
            self.assertEqual(
                demo_config.endpoint_from_env("ACNS_GRAFANA_ENDPOINT", ".grafana.azure.com"),
                "https://example.grafana.azure.com",
            )

    def test_cli_failure_does_not_report_captured_output(self):
        result = subprocess.CompletedProcess([], 1, "private-output", "private-error")
        with patch.object(demo_config.shutil, "which", return_value="az"), \
                patch.object(demo_config.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError) as error:
                demo_config.run_command(["az", "account", "show"])
        self.assertNotIn("private-output", str(error.exception))
        self.assertNotIn("private-error", str(error.exception))

    def test_cli_timeout_does_not_report_arguments(self):
        with patch.object(demo_config.shutil, "which", return_value="az"), \
                patch.object(demo_config.subprocess, "run", side_effect=subprocess.TimeoutExpired(["private-argument"], 1)):
            with self.assertRaises(RuntimeError) as error:
                demo_config.run_command(["az", "account", "show"])
        self.assertNotIn("private-argument", str(error.exception))

    def test_empty_token_is_an_error(self):
        with patch.object(capture, "run_command", return_value=""):
            with self.assertRaises(RuntimeError):
                capture.get_token()

    def test_capture_requires_configuration_before_acquiring_token(self):
        with patch.dict(os.environ, {"ACNS_GRAFANA_ENDPOINT": ""}), \
                patch.object(capture, "get_token") as token:
            with self.assertRaises(ValueError):
                capture.capture([("unused.png", "/d/example")])
            token.assert_not_called()


class EvidenceTests(unittest.TestCase):
    def test_failed_scenario_attempts_reset_and_does_not_report_done(self):
        output = io.StringIO()
        with patch.object(run_evidence, "endpoint_from_env"), \
                patch.object(run_evidence, "get_token", return_value="unused-test-token"), \
                patch.object(run_evidence, "demo", side_effect=["", RuntimeError("injected failure"), ""]) as demo, \
                patch.object(run_evidence, "kubectl"), \
                patch.object(run_evidence, "shot"), \
                patch.object(run_evidence.time, "sleep"), contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                run_evidence.main()
        self.assertEqual([call.args[0] for call in demo.call_args_list], ["Reset", "PolicyBreak", "Reset"])
        self.assertNotIn("DONE", output.getvalue())

    def test_missing_configuration_does_not_change_workloads(self):
        with patch.dict(os.environ, {"ACNS_GRAFANA_ENDPOINT": ""}), \
                patch.object(run_evidence, "demo") as demo:
            with self.assertRaises(ValueError):
                run_evidence.main()
            demo.assert_not_called()


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.playwright = ModuleType("playwright")
        self.sync_api = ModuleType("playwright.sync_api")
        self.sync_api.sync_playwright = MagicMock()
        runtime = self.sync_api.sync_playwright.return_value.__enter__.return_value
        self.browser = runtime.chromium.launch.return_value
        self.context = self.browser.new_context.return_value
        self.page = self.context.new_page.return_value
        self.page.goto.return_value.status = 200

    def capture(self):
        with patch.dict(sys.modules, {"playwright": self.playwright, "playwright.sync_api": self.sync_api}), \
                patch.dict(os.environ, {"ACNS_GRAFANA_ENDPOINT": "https://example.grafana.azure.com"}), \
                contextlib.redirect_stdout(io.StringIO()):
            capture.capture([("unused.png", "/d/example")], token="unused-test-token", settle=0)

    def test_bearer_header_is_only_added_to_configured_origin(self):
        self.capture()
        self.assertNotIn("extra_http_headers", self.browser.new_context.call_args.kwargs)
        authorize = self.context.route.call_args.args[1]
        route = MagicMock()
        route.request.url = "https://example.grafana.azure.com/api/ds/query"
        route.request.headers = {"authorization": "previous"}
        route.fetch.return_value.status = 200
        authorize(route)
        route.abort.assert_not_called()
        self.assertEqual(route.fetch.call_args.kwargs["headers"], {"Authorization": "Bearer unused-test-token"})
        self.assertEqual(route.fetch.call_args.kwargs["max_redirects"], 0)
        route.fulfill.assert_called_once()

    def test_third_party_request_is_blocked(self):
        self.capture()
        authorize = self.context.route.call_args.args[1]
        route = MagicMock()
        route.request.url = "https://external.example/"
        authorize(route)
        route.abort.assert_called_once()
        route.fetch.assert_not_called()

    def test_redirect_cannot_forward_bearer_header(self):
        self.capture()
        authorize = self.context.route.call_args.args[1]
        route = MagicMock()
        route.request.url = "https://example.grafana.azure.com/d/example"
        route.request.headers = {}
        route.fetch.return_value.status = 302
        with self.assertRaises(RuntimeError):
            authorize(route)
        self.assertEqual(route.fetch.call_args.kwargs["max_redirects"], 0)
        route.abort.assert_called_once()
        route.fulfill.assert_not_called()

    def test_http_error_does_not_save_success_shaped_screenshot(self):
        self.page.goto.return_value.status = 403
        with self.assertRaises(RuntimeError):
            self.capture()
        self.page.screenshot.assert_not_called()


class DashboardTests(unittest.TestCase):
    def test_dashboard_is_reproducible(self):
        generator = ROOT / "advanced" / "grafana" / "gen_dashboard.py"
        expected = json.loads(generator.with_name("acns-incident-dashboard.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="acns-dashboard-test-") as directory:
            subprocess.run([sys.executable, str(generator)], cwd=directory, check=True, capture_output=True)
            actual = json.loads((Path(directory) / "acns-incident-dashboard.json").read_text(encoding="utf-8"))
        self.assertEqual(expected, actual)
        ids = [panel["id"] for panel in actual["panels"]]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
