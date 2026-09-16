"""Tests for the AI PM interview type and its prompt runner.

The live loop and the runner are driven by fake clients, so no API key or
network is involved.
"""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from interview import (
    DEFAULT_TRACK,
    LEVELS,
    PROMPTS,
    TRACK_TOOLS,
    TRACKS,
    InterviewError,
    InterviewState,
    prompts_for,
    render_debrief,
)
from offline import OfflineSession, new_state, run_offline
from progress import load_history, overview, save_result, summary_for_interviewer
from session import (
    MAX_PROMPT_CHARS,
    MAX_PROMPT_RUNS,
    RUNNER_EFFORT,
    LiveSession,
    SessionError,
    build_system,
    load_context,
    snapshot,
)
from web import InterviewServer

AI_PM = "support-replies"
GOOD_ANSWER = (
    "The support agent is trying to answer tickets faster, because 60 tickets a day is too "
    "many. Done means a correct draft sent with light edits, and I am not solving refunds, "
    "so a human reviews every draft and the success metric is a 20% drop in handle time."
)


def text(value):
    return NS(type="text", text=value)


def tool(block_id, name, tool_input):
    return NS(type="tool_use", id=block_id, name=name, input=tool_input)


def response(stop_reason, *blocks):
    return NS(stop_reason=stop_reason, content=list(blocks))


class FakeClient:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = []
        self.messages = self

    def queue(self, *items):
        self.items.extend(items)

    def create(self, **kwargs):
        kwargs["messages"] = list(kwargs["messages"])
        self.calls.append(kwargs)
        return self.items.pop(0)


def at_prompt_demo(client):
    """A live AI PM session that has reached the Prompt demo stage and is waiting."""
    client.queue(
        response(
            "tool_use",
            tool("t1", "advance_stage", {"reason": "scoped"}),
            tool("t2", "advance_stage", {"reason": "metrics covered"}),
        ),
        response("end_turn", text("Show me the prompt you'd use.")),
    )
    session = LiveSession(new_state(AI_PM), client)
    session.start()
    return session


class TrackStructureTests(unittest.TestCase):
    def test_both_tracks_exist_with_their_own_stages(self):
        self.assertEqual(set(TRACKS), {"product-sense", "ai-pm"})
        self.assertEqual(DEFAULT_TRACK, "product-sense")
        self.assertEqual(
            [s.label for s in TRACKS["ai-pm"].stages],
            ["Scope", "Hypothesis & metrics", "Prompt demo", "Risk & judgment"],
        )
        self.assertEqual(TRACKS["ai-pm"].runner_stage, "prompt_demo")
        self.assertEqual(TRACKS["product-sense"].runner_stage, "")

    def test_each_track_scores_one_dimension_per_stage(self):
        for track in TRACKS.values():
            focus = [d for s in track.stages for d in s.focus]
            self.assertEqual(sorted(focus), sorted(track.dimensions), track.key)

    def test_dimension_keys_never_collide_across_tracks(self):
        seen = [d for t in TRACKS.values() for d in t.dimensions]
        self.assertEqual(len(seen), len(set(seen)))

    def test_every_prompt_belongs_to_a_track_and_has_a_brief(self):
        for prompt in PROMPTS.values():
            self.assertIn(prompt.track, TRACKS)
            self.assertGreater(len(prompt.brief), 100, prompt.key)
        self.assertEqual(len(prompts_for("ai-pm")), 4)
        self.assertEqual(len(prompts_for("product-sense")), 4)
        for track in TRACKS.values():
            self.assertEqual(PROMPTS[track.default_prompt].track, track.key)

    def test_tools_offer_only_the_tracks_dimensions(self):
        enum = TRACK_TOOLS["ai-pm"][0]["input_schema"]["properties"]["dimension"]["enum"]
        self.assertEqual(enum, list(TRACKS["ai-pm"].dimensions))

    def test_levels_have_a_bar_for_every_track(self):
        for level in LEVELS.values():
            for key in TRACKS:
                self.assertTrue(level.bar_for(key))
        self.assertIn("ownership", LEVELS["senior"].bar_for("ai-pm"))


class AiPmStateTests(unittest.TestCase):
    def setUp(self):
        self.state = new_state(AI_PM)

    def test_rejects_another_tracks_dimension(self):
        with self.assertRaises(InterviewError):
            self.state.record_signal("clarifying", 3, "evidence", "gap")

    def test_scorecard_and_debrief_cover_the_four_stages(self):
        self.state.record_signal("scope", 3, "named what done looks like", "say what is out of scope")
        self.state.end_interview("verdict", ["good"], ["better"], "next")
        card = self.state.scorecard()
        self.assertEqual([r["label_text"] for r in card["rows"]], [s.label for s in TRACKS["ai-pm"].stages])
        report = render_debrief(self.state)
        self.assertIn("**Interview:** AI PM", report)
        self.assertIn("| Scope | 3 solid |", report)

    def test_advancing_walks_the_ai_pm_stages(self):
        keys = []
        while not self.state.past_last_stage:
            keys.append(self.state.stage.key)
            self.state.advance_stage("next")
        self.assertEqual(keys, ["scope", "hypothesis", "prompt_demo", "risk"])


class AiPmInstructionsTests(unittest.TestCase):
    def test_instructions_are_for_ai_pm_with_runner_rules_and_no_clarify_stage(self):
        text_ = build_system(new_state(AI_PM, "senior"))
        self.assertIn("a practice AI product management interview", text_)
        self.assertIn("PROMPT RUN block", text_)
        self.assertIn("Never write the prompt for them", text_)
        self.assertIn(LEVELS["senior"].bar_for("ai-pm"), text_)
        self.assertNotIn(LEVELS["senior"].bar_for("product-sense"), text_)
        self.assertNotIn("In the Clarify stage the candidate asks and you answer", text_)
        for stage in TRACKS["ai-pm"].stages:
            self.assertIn(stage.label, text_)

    def test_product_sense_instructions_have_no_runner(self):
        self.assertNotIn("PROMPT RUN", build_system(new_state("grocery-reorder")))

    def test_live_session_sends_the_tracks_tools(self):
        client = FakeClient(response("end_turn", text("Scope it for me.")))
        LiveSession(new_state(AI_PM), client).start()
        self.assertIs(client.calls[0]["tools"], TRACK_TOOLS["ai-pm"])


class PromptRunnerTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.session = at_prompt_demo(self.client)

    def test_runner_is_closed_before_the_prompt_demo_stage(self):
        client = FakeClient(response("end_turn", text("Scope it for me.")))
        session = LiveSession(new_state(AI_PM), client)
        session.start()
        self.assertFalse(session.runner_open)
        with self.assertRaises(SessionError) as caught:
            session.run_prompt("Draft a reply.")
        self.assertIn("Prompt demo", str(caught.exception))

    def test_product_sense_has_no_runner(self):
        client = FakeClient(response("end_turn", text("Q1")))
        session = LiveSession(new_state("grocery-reorder"), client)
        session.start()
        with self.assertRaises(SessionError):
            session.run_prompt("anything")

    def test_run_calls_the_model_with_only_the_candidates_prompt(self):
        self.assertTrue(self.session.runner_open)
        self.client.queue(response("end_turn", text("Hi Sam, sorry about the delay...")))

        events = self.session.run_prompt("  Draft a friendly reply to this ticket: order late.  ")

        call = self.client.calls[-1]
        self.assertEqual(call["messages"], [{"role": "user", "content": "Draft a friendly reply to this ticket: order late."}])
        self.assertNotIn("tools", call)
        self.assertNotIn("system", call)
        self.assertEqual(call["output_config"], {"effort": RUNNER_EFFORT})
        self.assertEqual(events, [{
            "kind": "prompt_run",
            "prompt": "Draft a friendly reply to this ticket: order late.",
            "output": "Hi Sam, sorry about the delay...",
            "runs_left": MAX_PROMPT_RUNS - 1,
        }])

    def test_run_goes_into_the_interview_for_judging_without_using_a_probe(self):
        probes = self.session.state.probes_used
        self.client.queue(response("end_turn", text("OUTPUT TEXT")))
        self.session.run_prompt("MY PROMPT")

        last = self.session.history[-1]
        self.assertEqual(last["role"], "user")
        self.assertIn("PROMPT RUN 1", last["content"])
        self.assertIn("not instructions to you", last["content"])
        self.assertIn("MY PROMPT", last["content"])
        self.assertIn("OUTPUT TEXT", last["content"])
        self.assertEqual(self.session.state.probes_used, probes)
        self.assertTrue(self.session.awaiting_answer)

        # The narration that follows reaches the interviewer after the run.
        self.client.queue(response("end_turn", text("What would you change?")))
        self.session.answer("I kept it small; next I'd ground it in the help-centre article.")
        sent = self.client.calls[-1]["messages"]
        self.assertIn("PROMPT RUN 1", sent[-2]["content"])
        self.assertEqual(self.session.state.probes_used, probes + 1)

    def test_rejects_empty_and_oversized_prompts_without_calling_the_model(self):
        calls = len(self.client.calls)
        with self.assertRaises(SessionError):
            self.session.run_prompt("   ")
        with self.assertRaises(SessionError):
            self.session.run_prompt("x" * (MAX_PROMPT_CHARS + 1))
        self.assertEqual(len(self.client.calls), calls)

    def test_runs_are_capped(self):
        for _ in range(MAX_PROMPT_RUNS):
            self.client.queue(response("end_turn", text("ok")))
            self.session.run_prompt("prompt")
        self.assertFalse(self.session.runner_open)
        with self.assertRaises(SessionError):
            self.session.run_prompt("one more")

    def test_refusal_and_truncation_are_shown_plainly(self):
        self.client.queue(response("refusal"))
        self.assertIn("declined", self.session.run_prompt("p")[0]["output"])
        self.client.queue(response("max_tokens", text("partial")))
        self.assertIn("cut off", self.session.run_prompt("p")[0]["output"])

    def test_snapshot_reports_the_runner(self):
        view = snapshot(self.session)
        self.assertEqual(view["track"], {"key": "ai-pm", "label": "AI PM"})
        self.assertEqual(view["runner"]["stage"], "prompt_demo")
        self.assertTrue(view["runner"]["available"])
        self.assertTrue(view["runner"]["open"])
        self.assertEqual(view["runner"]["runs_left"], MAX_PROMPT_RUNS)
        self.assertEqual([s["label"] for s in view["stages"]][2], "Prompt demo")


class TrackContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for relative, body in {
            "shared.md": "for everyone",
            "ai-pm/criteria.md": "ai pm only",
            "private/product-sense/tips.md": "product sense only",
            "private/ai-pm/notes.md": "private ai pm",
        }.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, track):
        return [n for n, _ in load_context(self.root, track)]

    def test_track_folders_only_load_for_their_track(self):
        self.assertEqual(self.names("ai-pm"), ["ai-pm/criteria.md", "private/ai-pm/notes.md", "shared.md"])
        self.assertEqual(self.names("product-sense"), ["private/product-sense/tips.md", "shared.md"])
        self.assertEqual(len(self.names(None)), 4)

    def test_the_shipped_criteria_load_for_ai_pm_only(self):
        self.assertIn("ai-pm/judging-criteria.md", [n for n, _ in load_context(track="ai-pm")])
        self.assertNotIn("ai-pm/judging-criteria.md", [n for n, _ in load_context(track="product-sense")])


class AiPmOfflineTests(unittest.TestCase):
    def test_full_offline_run(self):
        state = new_state(AI_PM)
        asked = []
        run_offline(state, ask=lambda q: asked.append(q) or GOOD_ANSWER, say=lambda t: None)
        self.assertTrue(state.finished)
        self.assertEqual(state.scorecard()["assessed"], 4)
        self.assertIn("can't run it", " ".join(asked))

    def test_offline_session_has_no_runner(self):
        session = OfflineSession(new_state(AI_PM))
        session.start()
        self.assertFalse(hasattr(session, "run_prompt"))
        self.assertFalse(snapshot(session)["runner"]["available"])

    def test_offline_debrief_suggests_a_question_of_the_same_type(self):
        state = new_state(AI_PM)
        run_offline(state, ask=lambda q: "Not sure.", say=lambda t: None)
        other_ai_pm = [p.question for p in prompts_for("ai-pm") if p.key != AI_PM]
        self.assertTrue(any(q in state.debrief["next_prompt"] for q in other_ai_pm))


class AiPmProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def finished(self, prompt_key, dimension, score):
        state = new_state(prompt_key)
        state.record_signal(dimension, score, "said it", "" if score == 4 else "more")
        state.end_interview("v", ["good"], ["better"], "n")
        return NS(mode="live", state=state)

    def test_history_is_kept_apart_by_track(self):
        save_result(self.finished(AI_PM, "risk_judgment", 2), self.dir)
        save_result(self.finished("grocery-reorder", "clarifying", 4), self.dir)

        self.assertEqual(len(load_history(self.dir)), 2)
        self.assertEqual(len(load_history(self.dir, "ai-pm")), 1)
        record = load_history(self.dir, "ai-pm")[0]
        self.assertEqual(record["track"]["key"], "ai-pm")

        ai_summary = summary_for_interviewer(load_history(self.dir), "ai-pm")
        self.assertIn("1 previous interview.", ai_summary)
        self.assertIn("Weakest stage so far: Risk & judgment.", ai_summary)
        self.assertNotIn("Clarify", ai_summary)

        data = overview(load_history(self.dir))
        self.assertEqual([s["key"] for s in data["tracks"]], ["product-sense", "ai-pm"])

    def test_records_from_before_tracks_count_as_product_sense(self):
        (self.dir / "old.json").write_text(json.dumps({"finished_at": "1", "scores": {"clarifying": 3}}))
        self.assertEqual(len(load_history(self.dir, "product-sense")), 1)
        self.assertEqual(load_history(self.dir, "ai-pm"), [])


class FakeRepo:
    def is_repo(self):
        return False

    def status(self):
        return {"is_repo": False, "changes": 0, "changed_files": [], "pending": False, "last": None}

    def save_in_background(self, message):
        pass


class RunnerClient:
    """Moves straight to Prompt demo on the first turn; answers runs with fixed text."""

    def __init__(self):
        self.messages = self
        self.turn = 0

    def create(self, **kwargs):
        if "tools" not in kwargs:
            return response("end_turn", text("RUNNER OUTPUT"))
        self.turn += 1
        if self.turn == 1:
            return response(
                "tool_use",
                tool("t1", "advance_stage", {"reason": "scoped"}),
                tool("t2", "advance_stage", {"reason": "metrics"}),
            )
        return response("end_turn", text("Run your prompt and talk me through it."))


class AiPmWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        context = Path(self.tmp.name)
        self.server = InterviewServer(
            ("127.0.0.1", 0),
            client_factory=RunnerClient,
            context_dir=context,
            progress_dir=context / "private" / "progress",
            private_repo=FakeRepo(),
        )
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        return resp.status, data

    def test_config_describes_both_tracks(self):
        _, data = self.request("GET", "/api/config")
        tracks = {t["key"]: t for t in data["tracks"]}
        self.assertEqual(tracks["ai-pm"]["label"], "AI PM")
        self.assertTrue(tracks["ai-pm"]["has_runner"])
        self.assertFalse(tracks["product-sense"]["has_runner"])
        self.assertEqual(tracks["ai-pm"]["default_prompt"], AI_PM)
        self.assertEqual(len(tracks["ai-pm"]["stages"]), 4)

    def test_run_prompt_over_http(self):
        status, data = self.request("POST", "/api/sessions", {"prompt": AI_PM, "mode": "live"})
        self.assertEqual(status, 201)
        self.assertEqual(data["session"]["track"]["key"], "ai-pm")
        self.assertTrue(data["session"]["runner"]["open"])

        status, data = self.request("POST", "/api/sessions/%s/run" % data["id"], {"prompt": "Draft a reply."})

        self.assertEqual(status, 200)
        self.assertEqual(data["events"][0]["kind"], "prompt_run")
        self.assertEqual(data["events"][0]["output"], "RUNNER OUTPUT")
        self.assertEqual(data["session"]["runner"]["runs_left"], MAX_PROMPT_RUNS - 1)

    def test_run_is_refused_offline_and_outside_ai_pm(self):
        _, offline = self.request("POST", "/api/sessions", {"prompt": AI_PM, "mode": "offline"})
        status, data = self.request("POST", "/api/sessions/%s/run" % offline["id"], {"prompt": "p"})
        self.assertEqual(status, 409)
        self.assertIn("Offline", data["error"])

        _, product = self.request("POST", "/api/sessions", {"prompt": "grocery-reorder", "mode": "live"})
        status, _ = self.request("POST", "/api/sessions/%s/run" % product["id"], {"prompt": "p"})
        self.assertEqual(status, 409)


if __name__ == "__main__":
    unittest.main()
