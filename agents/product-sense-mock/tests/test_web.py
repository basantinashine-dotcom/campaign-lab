"""Tests for the local web server, over real HTTP on a random port.

Offline sessions need nothing; live sessions use a fake client injected through
``client_factory``, so no API key or network is involved.
"""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from interview import DIMENSIONS, LEVELS, STAGES
from session import STOP_REQUEST
from web import InterviewServer

GOOD_ANSWER = (
    "I would focus on first-time buyers in their first 14 days, because that is where "
    "80% of the drop off happens. The specific pain is that rebuilding a basket from "
    "scratch takes far too long, so they simply give up instead of reordering."
)


class FakeRepo:
    """Stands in for sync.PrivateRepo so no test runs git against anything real."""

    def __init__(self, is_repo=True):
        self._is_repo = is_repo
        self.background = []
        self.saved = []

    def is_repo(self):
        return self._is_repo

    def status(self):
        return {"is_repo": self._is_repo, "changes": 0, "changed_files": [], "pending": False, "last": None}

    def save(self, message):
        self.saved.append(message)
        return {"status": "saved", "detail": "Saved to GitHub."}

    def save_in_background(self, message):
        self.background.append(message)


class ScriptedClient:
    """Asks one question, then ends the interview with a score when asked to stop."""

    calls = []

    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        ScriptedClient.calls.append(kwargs)
        last = kwargs["messages"][-1]
        if last["role"] == "user" and last["content"] == STOP_REQUEST:
            return NS(
                stop_reason="tool_use",
                content=[
                    NS(
                        type="tool_use",
                        id="t1",
                        name="record_signal",
                        input={"dimension": "clarifying", "score": 2, "evidence": "asked one question", "gap": "ask what changes the build"},
                    ),
                    NS(
                        type="tool_use",
                        id="t2",
                        name="end_interview",
                        input={"headline": "Short run.", "strengths": ["asked a question"], "improvements": ["go further"], "next_prompt": "Try again."},
                    ),
                ],
            )
        return NS(stop_reason="end_turn", content=[NS(type="text", text="What would you like to ask?")])


class FakeClient:
    calls = []

    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        FakeClient.calls.append(kwargs)
        return NS(stop_reason="end_turn", content=[NS(type="text", text="What is the goal?")])


class WebServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        context = Path(cls.tmp.name)
        (context / "private").mkdir()
        (context / "README.md").write_text("about the folder", encoding="utf-8")
        (context / "private" / "tips.md").write_text("Always include a moonshot.", encoding="utf-8")

        cls.server = InterviewServer(
            ("127.0.0.1", 0),
            client_factory=FakeClient,
            context_dir=context,
            progress_dir=context / "private" / "progress",
            private_repo=FakeRepo(),
        )
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

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
        self.assertEqual(len(data["prompts"]), 8)
        self.assertEqual(
            sorted({p["track"] for p in data["prompts"]}), ["ai-pm", "product-sense"]
        )
        self.assertEqual(data["default_prompt"], "grocery-reorder")
        self.assertNotIn("sk-ant", json.dumps(data))

    def test_config_lists_levels_stages_and_context_file_names(self):
        _, data = self.request("GET", "/api/config")
        self.assertEqual([l["key"] for l in data["levels"]], ["pm", "senior"])
        self.assertEqual(data["default_level"], "pm")
        self.assertEqual([s["label"] for s in data["stages"]], [s.label for s in STAGES])
        self.assertEqual(data["context_files"], ["private/tips.md"])
        # Names only: the page never receives the reference material itself.
        self.assertNotIn("moonshot", json.dumps(data))

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

    def test_rejects_unknown_prompts_levels_and_modes(self):
        response, _ = self.request("POST", "/api/sessions", {"prompt": "nope", "mode": "offline"})
        self.assertEqual(response.status, 400)
        response, _ = self.request("POST", "/api/sessions", {"level": "intern", "mode": "offline"})
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

        # One answer per stage, plus one extra in Clarify for the company brief.
        for _ in range(len(STAGES) + 1):
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

    def test_live_interview_gets_the_level_and_the_context_files(self):
        FakeClient.calls.clear()
        response, data = self.request("POST", "/api/sessions", {"mode": "live", "level": "senior"})
        self.assertEqual(response.status, 201)
        self.assertEqual(data["session"]["level"]["label"], "Senior PM+")
        system = FakeClient.calls[-1]["system"][0]["text"]
        self.assertIn("Always include a moonshot.", system)
        self.assertIn(LEVELS["senior"].bar, system)
        self.assertNotIn("about the folder", system)


class ProgressAndSavingTests(unittest.TestCase):
    """A finished Claude interview is saved, uploaded, and fed into the next one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.context = Path(self.tmp.name)
        self.progress = self.context / "private" / "progress"
        self.repo = FakeRepo()
        self.server = InterviewServer(
            ("127.0.0.1", 0),
            client_factory=ScriptedClient,
            context_dir=self.context,
            progress_dir=self.progress,
            private_repo=self.repo,
        )
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        ScriptedClient.calls.clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    request = WebServerTests.request

    def finish_live_interview(self, level="pm"):
        _, data = self.request("POST", "/api/sessions", {"mode": "live", "level": level})
        session_id = data["id"]
        self.request("POST", "/api/sessions/%s/answer" % session_id, {"text": "Do we mean first order ever?"})
        return self.request("POST", "/api/sessions/%s/quit" % session_id, {})

    def test_finished_live_interview_is_saved_and_uploaded_once(self):
        response, data = self.finish_live_interview()

        self.assertEqual(response.status, 200)
        self.assertTrue(data["session"]["done"])
        self.assertTrue(data["progress"]["saved"])
        self.assertTrue(data["progress"]["uploading"])
        files = list(self.progress.glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text(encoding="utf-8"))["scores"]["clarifying"], 2)
        self.assertEqual(self.repo.background, ["Save interview: grocery-reorder, 2/4 (PM)"])

        # Asking again after the end must not save a duplicate.
        self.request("POST", "/api/sessions/%s/retry" % data["id"], {})
        self.assertEqual(len(list(self.progress.glob("*.json"))), 1)
        self.assertEqual(len(self.repo.background), 1)

    def test_without_a_private_repo_the_result_stays_local(self):
        self.repo._is_repo = False
        _, data = self.finish_live_interview()
        self.assertTrue(data["progress"]["saved"])
        self.assertFalse(data["progress"]["uploading"])
        self.assertEqual(self.repo.background, [])

    def test_offline_interviews_are_not_saved(self):
        _, data = self.request("POST", "/api/sessions", {"mode": "offline"})
        self.request("POST", "/api/sessions/%s/answer" % data["id"], {"text": "A question?"})
        response, data = self.request("POST", "/api/sessions/%s/quit" % data["id"], {})
        self.assertEqual(data["progress"], {"saved": False})
        self.assertFalse(self.progress.exists())
        self.assertEqual(self.repo.background, [])

    def test_progress_page_data(self):
        _, empty = self.request("GET", "/api/progress")
        self.assertEqual(empty["interviews"], 0)

        self.finish_live_interview()
        _, data = self.request("GET", "/api/progress")
        self.assertEqual(data["interviews"], 1)
        (section,) = data["tracks"]
        self.assertEqual(section["key"], "product-sense")
        self.assertEqual(section["weakest"], "Clarify")
        self.assertEqual(section["history"][0]["total"], 2)

    def test_next_interview_is_told_about_the_history(self):
        self.finish_live_interview()
        ScriptedClient.calls.clear()
        self.request("POST", "/api/sessions", {"mode": "live"})
        system = ScriptedClient.calls[0]["system"][0]["text"]
        self.assertIn("1 previous interview.", system)
        self.assertIn("Weakest stage so far: Clarify.", system)

    def test_context_status_and_manual_save(self):
        _, status = self.request("GET", "/api/context/status")
        self.assertTrue(status["is_repo"])

        response, data = self.request("POST", "/api/context/save", {})
        self.assertEqual(response.status, 200)
        self.assertEqual(data["result"]["status"], "saved")
        self.assertEqual(self.repo.saved, ["Update private context"])

    def test_manual_save_is_protected_like_everything_else(self):
        response, _ = self.request("POST", "/api/context/save", {}, headers={"Host": "evil.example"})
        self.assertEqual(response.status, 403)
        self.assertEqual(self.repo.saved, [])


if __name__ == "__main__":
    unittest.main()
