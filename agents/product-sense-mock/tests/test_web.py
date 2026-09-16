"""Tests for the local web server, over real HTTP on a random port.

Offline sessions need nothing; live sessions use a fake client injected through
``client_factory``, so no API key or network is involved.
"""

import http.client
import json
import threading
import unittest
from types import SimpleNamespace as NS

from interview import DIMENSIONS, STAGES
from web import InterviewServer

GOOD_ANSWER = (
    "I would focus on first-time buyers in their first 14 days, because that is where "
    "80% of the drop off happens. The specific pain is that rebuilding a basket from "
    "scratch takes far too long, so they simply give up instead of reordering."
)


class FakeClient:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        return NS(stop_reason="end_turn", content=[NS(type="text", text="What is the goal?")])


class WebServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = InterviewServer(("127.0.0.1", 0), client_factory=FakeClient)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        all_headers = dict(headers or {})
        payload = None
        if body is not None:
            payload = json.dumps(body)
            all_headers.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=all_headers)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        content_type = response.getheader("Content-Type", "")
        data = json.loads(raw) if content_type.startswith("application/json") else raw.decode("utf-8")
        return response, data

    # --- static and config ---------------------------------------------------

    def test_serves_the_page_and_its_assets(self):
        for path, marker in (("/", "<title>Product Sense Mock</title>"), ("/app.js", "api("), ("/style.css", ":root")):
            response, body = self.request("GET", path)
            self.assertEqual(response.status, 200, path)
            self.assertIn(marker, body)

    def test_does_not_serve_arbitrary_files(self):
        for path in ("/web.py", "/../interview.py", "/index.html", "/tests/test_web.py"):
            response, _ = self.request("GET", path)
            self.assertEqual(response.status, 404, path)

    def test_config_lists_prompts_without_exposing_any_key(self):
        response, data = self.request("GET", "/api/config")
        self.assertEqual(response.status, 200)
        self.assertEqual(len(data["prompts"]), 4)
        self.assertEqual(data["default_prompt"], "grocery-reorder")
        self.assertNotIn("sk-ant", json.dumps(data))

    # --- protections -----------------------------------------------------------

    def test_rejects_requests_addressed_to_another_host(self):
        response, data = self.request("GET", "/api/config", headers={"Host": "evil.example"})
        self.assertEqual(response.status, 403)
        response, _ = self.request(
            "POST", "/api/sessions", {"mode": "offline"}, headers={"Host": "evil.example"}
        )
        self.assertEqual(response.status, 403)

    def test_rejects_posts_that_are_not_json(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(
            "POST",
            "/api/sessions",
            body="mode=offline",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = conn.getresponse()
        response.read()
        conn.close()
        self.assertEqual(response.status, 415)

    def test_rejects_unknown_prompts_and_modes(self):
        response, _ = self.request("POST", "/api/sessions", {"prompt": "nope", "mode": "offline"})
        self.assertEqual(response.status, 400)
        response, _ = self.request("POST", "/api/sessions", {"mode": "psychic"})
        self.assertEqual(response.status, 400)

    def test_unknown_session_is_a_404(self):
        response, data = self.request("POST", "/api/sessions/doesnotexist/answer", {"text": "hi"})
        self.assertEqual(response.status, 404)
        self.assertIn("no longer exists", data["error"])

    # --- a whole interview -------------------------------------------------------

    def test_offline_interview_end_to_end(self):
        response, data = self.request(
            "POST", "/api/sessions", {"prompt": "grocery-reorder", "mode": "offline"}
        )
        self.assertEqual(response.status, 201)
        session_id = data["id"]
        self.assertTrue(data["session"]["awaiting_answer"])
        self.assertNotIn("scorecard", data["session"])

        response, _ = self.request("GET", "/api/sessions/%s/debrief.md" % session_id)
        self.assertEqual(response.status, 409)

        for _ in STAGES:
            response, data = self.request(
                "POST", "/api/sessions/%s/answer" % session_id, {"text": GOOD_ANSWER}
            )
            self.assertEqual(response.status, 200)

        view = data["session"]
        self.assertTrue(view["done"])
        self.assertEqual(view["scorecard"]["assessed"], len(DIMENSIONS))
        self.assertTrue(view["debrief"]["headline"])

        response, markdown = self.request("GET", "/api/sessions/%s/debrief.md" % session_id)
        self.assertEqual(response.status, 200)
        self.assertIn("attachment", response.getheader("Content-Disposition"))
        self.assertIn("# Product sense debrief", markdown)

        response, data = self.request(
            "POST", "/api/sessions/%s/answer" % session_id, {"text": GOOD_ANSWER}
        )
        self.assertEqual(response.status, 409)

    def test_quit_returns_a_debrief(self):
        _, data = self.request("POST", "/api/sessions", {"mode": "offline"})
        response, data = self.request("POST", "/api/sessions/%s/quit" % data["id"], {})
        self.assertEqual(response.status, 200)
        self.assertTrue(data["session"]["done"])
        self.assertEqual(data["session"]["debrief"]["strengths"], [])

    def test_empty_answer_is_refused_without_losing_the_session(self):
        _, data = self.request("POST", "/api/sessions", {"mode": "offline"})
        response, _ = self.request("POST", "/api/sessions/%s/answer" % data["id"], {"text": "  "})
        self.assertEqual(response.status, 409)
        response, data = self.request(
            "POST", "/api/sessions/%s/answer" % data["id"], {"text": GOOD_ANSWER}
        )
        self.assertEqual(response.status, 200)

    def test_live_interview_starts_through_the_client(self):
        response, data = self.request("POST", "/api/sessions", {"mode": "live"})
        self.assertEqual(response.status, 201)
        self.assertEqual(data["session"]["mode"], "live")
        self.assertEqual(data["events"], [{"kind": "interviewer", "text": "What is the goal?"}])


if __name__ == "__main__":
    unittest.main()
