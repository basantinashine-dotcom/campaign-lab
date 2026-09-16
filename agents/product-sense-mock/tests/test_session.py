"""Tests for the live agent loop and the step-by-step offline interviewer.

The live loop is driven by a fake client that returns scripted responses, so
these cover the real request/tool/result cycle without an API key or network.
"""

import json
import unittest
from types import SimpleNamespace as NS

from interview import DIMENSIONS, STAGES, TOOLS, InterviewState, PROMPTS
from offline import OfflineError, OfflineSession
from session import (
    KICKOFF,
    STOP_REQUEST,
    LiveSession,
    SessionError,
    explain_api_error,
    snapshot,
)

GOOD_ANSWER = (
    "I would focus on first-time buyers in their first 14 days, because that is where "
    "80% of the drop off happens. The specific pain is that rebuilding a basket from "
    "scratch takes far too long, so they simply give up instead of reordering."
)
THIN_ANSWER = "Not sure."


def text(value):
    return NS(type="text", text=value)


def tool(block_id, name, tool_input):
    return NS(type="tool_use", id=block_id, name=name, input=tool_input)


def response(stop_reason, *blocks):
    return NS(stop_reason=stop_reason, content=list(blocks))


def signal(score=3, dimension="problem_framing", gap="name a constraint"):
    return {"dimension": dimension, "score": score, "evidence": "scoped it to week one", "gap": gap}


def debrief(strengths=("framed it well",)):
    return {
        "headline": "Solid start.",
        "strengths": list(strengths),
        "improvements": ["say what you would measure"],
        "next_prompt": "Try the grocery prompt.",
    }


class FakeClient:
    """Stands in for anthropic.Anthropic(). Pops one scripted item per call."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls = []
        self.messages = self

    def queue(self, *items):
        self.items.extend(items)

    def create(self, **kwargs):
        kwargs["messages"] = list(kwargs["messages"])
        self.calls.append(kwargs)
        if not self.items:
            raise AssertionError("The loop made more API calls than the test scripted.")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def live(client, **kwargs):
    return LiveSession(InterviewState(prompt=PROMPTS["grocery-reorder"]), client, **kwargs)


class LiveStartTests(unittest.TestCase):
    def test_start_returns_the_first_question_and_waits(self):
        client = FakeClient(response("end_turn", text("What are you optimising for?")))
        session = live(client, model="claude-test", effort="medium")

        events = session.start()

        self.assertEqual(events, [{"kind": "interviewer", "text": "What are you optimising for?"}])
        self.assertTrue(session.awaiting_answer)
        self.assertFalse(session.done)
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-test")
        self.assertEqual(call["output_config"], {"effort": "medium"})
        self.assertIs(call["tools"], TOOLS)
        self.assertEqual(call["messages"], [{"role": "user", "content": KICKOFF}])
        self.assertIn(PROMPTS["grocery-reorder"].question, call["system"])

    def test_cannot_start_twice(self):
        session = live(FakeClient(response("end_turn", text("Q1"))))
        session.start()
        with self.assertRaises(SessionError):
            session.start()


class LiveAnswerTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(response("end_turn", text("Q1")))
        self.session = live(self.client)
        self.session.start()

    def test_rejects_empty_answers(self):
        with self.assertRaises(SessionError):
            self.session.answer("   ")

    def test_rejects_answers_before_start(self):
        with self.assertRaises(SessionError):
            live(FakeClient()).answer("hello")

    def test_tool_calls_run_against_state_and_results_go_back_to_the_model(self):
        self.client.queue(
            response("tool_use", text("Noted."), tool("t1", "record_signal", signal())),
            response("end_turn", text("Who is it for?")),
        )

        events = self.session.answer("I'd scope it to the first week.")

        self.assertEqual(self.session.state.probes_used, 1)
        self.assertEqual(self.session.state.signals["problem_framing"].score, 3)
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds, ["interviewer", "tool", "interviewer"])
        tool_event = events[1]
        self.assertEqual(tool_event["name"], "record_signal")
        self.assertFalse(tool_event["is_error"])

        # The follow-up request carries the tool result, matched by id.
        tool_results = self.client.calls[-1]["messages"][-1]
        self.assertEqual(tool_results["role"], "user")
        result_block = tool_results["content"][0]
        self.assertEqual(result_block["type"], "tool_result")
        self.assertEqual(result_block["tool_use_id"], "t1")
        self.assertFalse(result_block["is_error"])
        self.assertEqual(json.loads(result_block["content"])["recorded"]["score"], 3)
        self.assertTrue(self.session.awaiting_answer)

    def test_rejected_tool_input_goes_back_as_an_error_and_the_loop_continues(self):
        self.client.queue(
            response("tool_use", tool("t1", "record_signal", signal(score=2, gap=""))),
            response("end_turn", text("Say more about the goal?")),
        )

        events = self.session.answer("Something vague.")

        tool_event = [e for e in events if e["kind"] == "tool"][0]
        self.assertTrue(tool_event["is_error"])
        self.assertIn("gap", tool_event["result"]["error"])
        self.assertTrue(self.client.calls[-1]["messages"][-1]["content"][0]["is_error"])
        self.assertEqual(self.session.state.signals, {})
        self.assertTrue(self.session.awaiting_answer)

    def test_several_tool_calls_in_one_turn_return_in_one_message(self):
        self.client.queue(
            response(
                "tool_use",
                tool("t1", "record_signal", signal()),
                tool("t2", "advance_stage", {"reason": "framing covered"}),
            ),
            response("end_turn", text("Who is it for?")),
        )

        self.session.answer("Goal is repeat orders within 14 days.")

        results = self.client.calls[-1]["messages"][-1]["content"]
        self.assertEqual([r["tool_use_id"] for r in results], ["t1", "t2"])
        self.assertEqual(self.session.state.stage.key, "users")

    def test_cannot_answer_twice_without_a_new_question(self):
        self.client.queue(response("end_turn", text("Q2")))
        self.session.answer("first")
        self.session.awaiting_answer = False
        with self.assertRaises(SessionError):
            self.session.answer("second")


class LiveEndingTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(response("end_turn", text("Q1")))
        self.session = live(self.client)
        self.session.start()

    def test_end_interview_finishes_without_another_api_call(self):
        self.client.queue(
            response(
                "tool_use",
                text("Thanks, that's time."),
                tool("t1", "record_signal", signal()),
                tool("t2", "end_interview", debrief()),
            )
        )

        self.session.answer("My answer.")

        self.assertTrue(self.session.done)
        self.assertFalse(self.session.awaiting_answer)
        self.assertEqual(len(self.client.calls), 2)
        with self.assertRaises(SessionError):
            self.session.answer("too late")

    def test_quit_asks_the_model_to_end_and_files_an_honest_debrief(self):
        self.client.queue(response("tool_use", tool("t1", "end_interview", debrief(strengths=()))))

        self.session.quit()

        self.assertEqual(self.client.calls[-1]["messages"][-1], {"role": "user", "content": STOP_REQUEST})
        self.assertTrue(self.session.done)
        self.assertEqual(self.session.state.debrief["strengths"], [])
        self.assertEqual(self.session.quit(), [])

    def test_refusal_ends_the_session(self):
        self.client.queue(response("refusal"))
        events = self.session.answer("My answer.")
        self.assertEqual(self.session.ended_reason, "refusal")
        self.assertTrue(self.session.done)
        self.assertEqual(events[-1]["kind"], "notice")

    def test_max_tokens_ends_the_session(self):
        self.client.queue(response("max_tokens", text("partial")))
        self.session.answer("My answer.")
        self.assertEqual(self.session.ended_reason, "max_tokens")
        self.assertTrue(self.session.done)

    def test_turn_ceiling_stops_a_loop_that_never_asks(self):
        client = FakeClient(
            response("tool_use", tool("t1", "advance_stage", {"reason": "a"})),
            response("tool_use", tool("t2", "advance_stage", {"reason": "b"})),
        )
        session = live(client, max_turns=2)

        events = session.start()

        self.assertEqual(session.ended_reason, "turn_limit")
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(events[-1]["kind"], "notice")


class LiveRecoveryTests(unittest.TestCase):
    def test_resume_after_an_api_error_does_not_resend_the_answer(self):
        client = FakeClient(response("end_turn", text("Q1")))
        session = live(client)
        session.start()

        client.queue(RuntimeError("network blip"))
        with self.assertRaises(RuntimeError):
            session.answer("My one and only answer.")

        self.assertFalse(session.awaiting_answer)
        client.queue(response("end_turn", text("Q2")))
        events = session.resume()

        self.assertEqual(events, [{"kind": "interviewer", "text": "Q2"}])
        sent = [m for m in client.calls[-1]["messages"] if m["content"] == "My one and only answer."]
        self.assertEqual(len(sent), 1)
        self.assertEqual(session.state.probes_used, 1)

    def test_resume_is_a_no_op_while_waiting_for_an_answer(self):
        client = FakeClient(response("end_turn", text("Q1")))
        session = live(client)
        session.start()
        self.assertEqual(session.resume(), [])
        self.assertEqual(len(client.calls), 1)


class ExplainApiErrorTests(unittest.TestCase):
    def setUp(self):
        class APIStatusError(Exception):
            def __init__(self, status_code, message="boom", headers=None):
                super().__init__(message)
                self.status_code = status_code
                self.message = message
                self.response = NS(headers=headers or {})

        class AuthenticationError(APIStatusError):
            pass

        class NotFoundError(APIStatusError):
            pass

        class RateLimitError(APIStatusError):
            pass

        class APIConnectionError(Exception):
            pass

        self.sdk = NS(
            APIStatusError=APIStatusError,
            AuthenticationError=AuthenticationError,
            NotFoundError=NotFoundError,
            RateLimitError=RateLimitError,
            APIConnectionError=APIConnectionError,
        )

    def test_authentication_is_not_retryable(self):
        message, retryable = explain_api_error(self.sdk, self.sdk.AuthenticationError(401), "m")
        self.assertIn("ANTHROPIC_API_KEY", message)
        self.assertFalse(retryable)

    def test_rate_limit_is_retryable_and_reports_the_wait(self):
        exc = self.sdk.RateLimitError(429, headers={"retry-after": "12"})
        message, retryable = explain_api_error(self.sdk, exc, "m")
        self.assertIn("12", message)
        self.assertTrue(retryable)

    def test_server_errors_are_retryable_client_errors_are_not(self):
        self.assertTrue(explain_api_error(self.sdk, self.sdk.APIStatusError(529), "m")[1])
        self.assertFalse(explain_api_error(self.sdk, self.sdk.APIStatusError(400), "m")[1])

    def test_unrelated_exceptions_are_not_explained(self):
        self.assertIsNone(explain_api_error(self.sdk, ValueError("bug"), "m"))


class SnapshotTests(unittest.TestCase):
    def test_scores_are_hidden_until_the_interview_is_over(self):
        client = FakeClient(
            response("tool_use", tool("t1", "record_signal", signal())),
            response("end_turn", text("Q1")),
        )
        session = live(client)
        session.start()

        view = snapshot(session)
        self.assertNotIn("scorecard", view)
        self.assertNotIn("debrief", view)
        self.assertEqual(view["stages"], [s.key for s in STAGES])

        client.queue(response("tool_use", tool("t2", "end_interview", debrief())))
        session.quit()
        view = snapshot(session)
        self.assertEqual(view["scorecard"]["assessed"], 1)
        self.assertEqual(view["debrief"]["headline"], "Solid start.")


class OfflineSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = OfflineSession(InterviewState(prompt=PROMPTS["grocery-reorder"]))

    def questions(self, events):
        return [e["text"] for e in events if e["kind"] == "interviewer"]

    def test_start_explains_itself_and_asks_the_opening_question(self):
        events = self.session.start()
        self.assertEqual(events[0]["kind"], "notice")
        self.assertEqual(len(self.questions(events)), 1)
        self.assertTrue(self.session.awaiting_answer)

    def test_strong_answers_take_one_question_per_stage(self):
        asked = len(self.questions(self.session.start()))
        tools = []
        while not self.session.done:
            events = self.session.answer(GOOD_ANSWER)
            asked += len(self.questions(events))
            tools += [e["name"] for e in events if e["kind"] == "tool"]

        self.assertEqual(asked, len(STAGES))
        self.assertEqual(tools.count("record_signal"), len(DIMENSIONS))
        self.assertEqual(tools.count("advance_stage"), len(STAGES))
        self.assertEqual(tools.count("end_interview"), 1)
        self.assertEqual(self.session.state.scorecard()["assessed"], len(DIMENSIONS))

    def test_a_thin_answer_gets_a_follow_up_in_the_same_stage(self):
        self.session.start()
        events = self.session.answer(THIN_ANSWER)
        self.assertEqual(self.session.state.stage.key, "framing")
        self.assertEqual(len(self.questions(events)), 1)
        self.assertEqual([e for e in events if e["kind"] == "tool"], [])

        self.session.answer(THIN_ANSWER)
        self.assertEqual(self.session.state.stage.key, "users")

    def test_quit_before_answering_ends_immediately_with_nothing_assessed(self):
        # The terminal bug this rework fixes: /quit used to skip one question
        # at a time instead of ending the interview.
        self.session.start()
        self.session.quit()

        self.assertTrue(self.session.done)
        self.assertFalse(self.session.awaiting_answer)
        self.assertEqual(self.session.state.scorecard()["assessed"], 0)
        self.assertEqual(self.session.state.debrief["strengths"], [])

    def test_quit_mid_stage_still_scores_what_was_heard(self):
        self.session.start()
        self.session.answer(THIN_ANSWER)  # framing, follow-up pending
        self.session.quit()
        self.assertIn("problem_framing", self.session.state.signals)
        self.assertTrue(self.session.done)

    def test_rejects_empty_answers_and_answers_after_the_end(self):
        self.session.start()
        with self.assertRaises(OfflineError):
            self.session.answer("  ")
        self.session.quit()
        with self.assertRaises(OfflineError):
            self.session.answer(GOOD_ANSWER)


if __name__ == "__main__":
    unittest.main()
