"""Tests for the interview state machine and the offline interviewer.

Run from agents/product-sense-mock:

    python -m unittest discover -s tests -t .

No API key and no network needed: interview.py and offline.py never import the
Anthropic SDK.
"""

import unittest

from interview import (
    DIMENSIONS,
    MAX_SCORE,
    PROMPTS,
    STAGES,
    InterviewError,
    InterviewState,
    dispatch,
    render_debrief,
)
from offline import heuristic_score, new_state, run_offline

GOOD_ANSWER = (
    "I would focus on first-time buyers in their first 14 days, because that is where "
    "80% of the drop off happens. The specific pain is that rebuilding a basket from "
    "scratch takes far too long, so they simply give up instead of reordering."
)
THIN_ANSWER = "Not sure."


class RecordSignalTests(unittest.TestCase):
    def setUp(self):
        self.state = InterviewState(prompt=PROMPTS["grocery-reorder"])

    def test_rejects_unknown_dimension(self):
        with self.assertRaises(InterviewError):
            self.state.record_signal("charisma", 3, "said something", "more detail")

    def test_rejects_out_of_range_score(self):
        for bad in (0, 5, -1):
            with self.assertRaises(InterviewError):
                self.state.record_signal("problem_framing", bad, "evidence", "gap")

    def test_rejects_non_integer_score(self):
        for bad in ("3", 3.5, True, None):
            with self.assertRaises(InterviewError):
                self.state.record_signal("problem_framing", bad, "evidence", "gap")

    def test_rejects_empty_evidence(self):
        with self.assertRaises(InterviewError):
            self.state.record_signal("problem_framing", 3, "   ", "gap")

    def test_requires_gap_below_top_score(self):
        with self.assertRaises(InterviewError):
            self.state.record_signal("problem_framing", 3, "evidence", "")

    def test_top_score_may_omit_gap(self):
        result = self.state.record_signal("problem_framing", MAX_SCORE, "evidence", "")
        self.assertEqual(result["recorded"]["label"], "strong")

    def test_reports_uncovered_dimensions_in_stage(self):
        self.state.stage_index = 1  # users: segmentation + pain points
        result = self.state.record_signal("user_segmentation", 3, "picked new buyers", "why")
        self.assertEqual(result["stage_uncovered"], ["pain_points"])


class ProbeBudgetTests(unittest.TestCase):
    def setUp(self):
        self.state = InterviewState(prompt=PROMPTS["grocery-reorder"])

    def test_budget_decrements_with_each_answer(self):
        budget = STAGES[0].probe_budget
        self.assertEqual(self.state.probes_remaining, budget)
        self.state.note_answer()
        self.assertEqual(self.state.probes_remaining, budget - 1)

    def test_exhausted_budget_tells_interviewer_to_advance(self):
        self.state.stage_index = 1
        for _ in range(STAGES[1].probe_budget):
            self.state.note_answer()
        result = self.state.record_signal("user_segmentation", 2, "vague", "be specific")
        self.assertEqual(result["probes_remaining"], 0)
        self.assertIn("advance_stage", result["guidance"])

    def test_budget_never_goes_negative(self):
        for _ in range(STAGES[0].probe_budget + 5):
            self.state.note_answer()
        self.assertEqual(self.state.probes_remaining, 0)


class AdvanceStageTests(unittest.TestCase):
    def setUp(self):
        self.state = InterviewState(prompt=PROMPTS["grocery-reorder"])

    def test_requires_a_reason(self):
        with self.assertRaises(InterviewError):
            self.state.advance_stage("  ")

    def test_resets_the_probe_budget(self):
        self.state.note_answer()
        result = self.state.advance_stage("covered")
        self.assertEqual(result["stage"], STAGES[1].key)
        self.assertEqual(self.state.probes_remaining, STAGES[1].probe_budget)

    def test_reports_dimensions_left_unassessed(self):
        result = self.state.advance_stage("out of time")
        self.assertEqual(result["left_unassessed"], ["problem_framing"])

    def test_past_final_stage_points_at_debrief(self):
        for _ in range(len(STAGES)):
            result = self.state.advance_stage("next")
        self.assertEqual(result["stage"], "debrief")
        self.assertTrue(self.state.past_last_stage)

    def test_advancing_past_debrief_is_an_error(self):
        for _ in range(len(STAGES)):
            self.state.advance_stage("next")
        with self.assertRaises(InterviewError):
            self.state.advance_stage("again")


class ScorecardTests(unittest.TestCase):
    def setUp(self):
        self.state = InterviewState(prompt=PROMPTS["grocery-reorder"])

    def test_unassessed_dimensions_are_marked_not_scored_zero(self):
        self.state.record_signal("problem_framing", 3, "evidence", "gap")
        card = self.state.scorecard()
        self.assertEqual(len(card["rows"]), len(DIMENSIONS))
        self.assertEqual(card["assessed"], 1)
        self.assertEqual(card["total"], 3)
        self.assertEqual(card["possible"], MAX_SCORE)
        unassessed = [r for r in card["rows"] if r["score"] is None]
        self.assertEqual(len(unassessed), len(DIMENSIONS) - 1)
        self.assertEqual(unassessed[0]["label"], "not assessed")

    def test_weakest_returns_lowest_and_breaks_ties_in_rubric_order(self):
        self.state.record_signal("problem_framing", 2, "evidence", "gap")
        self.state.record_signal("metrics", 2, "evidence", "gap")
        self.state.record_signal("solution", 4, "evidence", "")
        self.assertEqual(self.state.weakest(), "problem_framing")

    def test_weakest_is_none_before_anything_is_recorded(self):
        self.assertIsNone(self.state.weakest())


class EndInterviewTests(unittest.TestCase):
    def setUp(self):
        self.state = InterviewState(prompt=PROMPTS["grocery-reorder"])

    def test_rejects_empty_lists(self):
        with self.assertRaises(InterviewError):
            self.state.end_interview("verdict", [], ["do better"], "next")

    def test_rejects_blank_entries(self):
        with self.assertRaises(InterviewError):
            self.state.end_interview("verdict", ["good"], ["   "], "next")

    def test_cannot_end_twice(self):
        self.state.end_interview("verdict", ["good"], ["better"], "next")
        self.assertTrue(self.state.finished)
        with self.assertRaises(InterviewError):
            self.state.end_interview("verdict", ["good"], ["better"], "next")


class DispatchTests(unittest.TestCase):
    def test_unknown_tool_raises(self):
        state = InterviewState(prompt=PROMPTS["grocery-reorder"])
        with self.assertRaises(InterviewError):
            dispatch(state, "make_coffee", {})

    def test_routes_record_signal(self):
        state = InterviewState(prompt=PROMPTS["grocery-reorder"])
        result = dispatch(
            state,
            "record_signal",
            {
                "dimension": "problem_framing",
                "score": 3,
                "evidence": "scoped it",
                "gap": "name a goal",
            },
        )
        self.assertEqual(result["recorded"]["score"], 3)


class RenderTests(unittest.TestCase):
    def test_reports_total_over_assessed_only(self):
        state = InterviewState(prompt=PROMPTS["grocery-reorder"])
        state.record_signal("problem_framing", 3, "evidence", "gap")
        state.record_signal("metrics", 4, "evidence", "")
        state.end_interview("verdict", ["good"], ["better"], "next")
        report = render_debrief(state, when="2026-09-16")
        self.assertIn("**Score: 7 / 8** across 2 assessed dimensions.", report)
        self.assertIn("not assessed", report)
        self.assertIn("2026-09-16", report)

    def test_escapes_pipes_so_the_table_survives(self):
        state = InterviewState(prompt=PROMPTS["grocery-reorder"])
        state.record_signal("problem_framing", 2, "a | b", "more | detail")
        state.end_interview("verdict", ["good"], ["better"], "next")
        report = render_debrief(state)
        self.assertIn("a \\| b", report)


class HeuristicTests(unittest.TestCase):
    def test_empty_answer_scores_the_floor(self):
        score, evidence, gap = heuristic_score("problem_framing", "")
        self.assertEqual(score, 1)
        self.assertTrue(evidence)
        self.assertTrue(gap)

    def test_substantial_specific_on_topic_answer_scores_the_ceiling(self):
        score, _, gap = heuristic_score("pain_points", GOOD_ANSWER)
        self.assertEqual(score, MAX_SCORE)
        self.assertEqual(gap, "")

    def test_thin_answer_scores_below_solid(self):
        score, _, _ = heuristic_score("pain_points", THIN_ANSWER)
        self.assertLess(score, 3)

    def test_every_dimension_has_keywords(self):
        for dimension in DIMENSIONS:
            score, _, _ = heuristic_score(dimension, GOOD_ANSWER)
            self.assertGreaterEqual(score, 1)
            self.assertLessEqual(score, MAX_SCORE)

    def test_long_evidence_is_truncated(self):
        _, evidence, _ = heuristic_score("solution", "word " * 200)
        self.assertLessEqual(len(evidence), 140)


class OfflineRunTests(unittest.TestCase):
    def test_full_run_assesses_every_dimension_and_files_a_debrief(self):
        state = new_state("grocery-reorder")
        run_offline(state, ask=lambda q: GOOD_ANSWER, say=lambda t: None)

        self.assertTrue(state.finished)
        self.assertTrue(state.past_last_stage)
        card = state.scorecard()
        self.assertEqual(card["assessed"], len(DIMENSIONS))
        self.assertEqual(card["possible"], MAX_SCORE * len(DIMENSIONS))
        self.assertTrue(state.debrief["strengths"])
        self.assertTrue(state.debrief["improvements"])

    def test_thin_answers_trigger_the_follow_up_question(self):
        asked = []

        def ask(question):
            asked.append(question)
            return THIN_ANSWER

        state = new_state("grocery-reorder")
        run_offline(state, ask=ask, say=lambda t: None)

        # One opening per stage, plus a follow-up wherever the opening scored thin.
        self.assertGreater(len(asked), len(STAGES))
        self.assertTrue(state.finished)

    def test_strong_answers_skip_the_follow_up(self):
        asked = []

        def ask(question):
            asked.append(question)
            return GOOD_ANSWER

        state = new_state("grocery-reorder")
        run_offline(state, ask=ask, say=lambda t: None)
        self.assertEqual(len(asked), len(STAGES))

    def test_unknown_prompt_key_raises(self):
        with self.assertRaises(KeyError):
            new_state("no-such-prompt")

    def test_debrief_renders_for_every_prompt(self):
        for key in PROMPTS:
            state = new_state(key)
            run_offline(state, ask=lambda q: GOOD_ANSWER, say=lambda t: None)
            report = render_debrief(state)
            self.assertIn("# Product sense debrief", report)
            self.assertIn(state.prompt.question, report)


if __name__ == "__main__":
    unittest.main()
