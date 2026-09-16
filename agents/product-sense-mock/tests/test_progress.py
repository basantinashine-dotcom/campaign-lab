"""Tests for saving interview results and summarizing progress."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS

from interview import DIMENSIONS, PROMPTS, InterviewState
from progress import (
    RECENT,
    commit_message,
    load_history,
    overview,
    save_result,
    should_save,
    summarize,
    summary_for_interviewer,
)
from session import build_system


def finished_session(mode="live", scores=None, level="pm"):
    """A session-shaped object whose state has finished with the given scores."""
    from interview import LEVELS

    state = InterviewState(prompt=PROMPTS["grocery-reorder"], level=LEVELS[level])
    for dimension, score in (scores or {}).items():
        state.record_signal(dimension, score, "said something", "" if score == 4 else "more")
    state.end_interview(
        "verdict",
        ["good"] if scores else [],
        ["better"],
        "next",
    )
    return NS(mode=mode, state=state)


def record(finished_at, **scores):
    full = {d: None for d in DIMENSIONS}
    full.update(scores)
    return {"finished_at": finished_at, "scores": full}


class ShouldSaveTests(unittest.TestCase):
    def test_saves_only_finished_live_interviews_that_scored_something(self):
        self.assertTrue(should_save(finished_session(scores={"clarifying": 3})))
        self.assertFalse(should_save(finished_session(mode="offline", scores={"clarifying": 3})))
        self.assertFalse(should_save(finished_session(scores={})))

        unfinished = NS(mode="live", state=InterviewState(prompt=PROMPTS["grocery-reorder"]))
        unfinished.state.record_signal("clarifying", 3, "x", "y")
        self.assertFalse(should_save(unfinished))


class SaveResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "progress"

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_one_json_file_with_scores_level_and_debrief(self):
        session = finished_session(scores={"clarifying": 3, "mvp": 2}, level="senior")
        when = datetime(2026, 9, 16, 14, 5, 22)

        path = save_result(session, self.dir, model="claude-opus-5", now=when)

        self.assertEqual(path.name, "2026-09-16T14-05-22_grocery-reorder.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["scores"]["clarifying"], 3)
        self.assertEqual(data["scores"]["mvp"], 2)
        self.assertIsNone(data["scores"]["strategy"])
        self.assertEqual(data["level"]["label"], "Senior PM+")
        self.assertEqual((data["total"], data["possible"], data["assessed"]), (5, 8, 2))
        self.assertEqual(data["gaps"]["mvp"], "more")
        self.assertNotIn("strategy", data["gaps"])
        self.assertEqual(data["model"], "claude-opus-5")

    def test_never_overwrites_an_earlier_result(self):
        when = datetime(2026, 9, 16, 14, 5, 22)
        first = save_result(finished_session(scores={"clarifying": 3}), self.dir, now=when)
        second = save_result(finished_session(scores={"clarifying": 4}), self.dir, now=when)
        self.assertNotEqual(first, second)
        self.assertEqual(len(list(self.dir.glob("*.json"))), 2)

    def test_skipped_sessions_write_nothing(self):
        self.assertIsNone(save_result(finished_session(mode="offline", scores={"clarifying": 3}), self.dir))
        self.assertFalse(self.dir.exists())

    def test_results_are_json_so_they_never_leak_into_reference_context(self):
        path = save_result(finished_session(scores={"clarifying": 3}), self.dir)
        self.assertEqual(path.suffix, ".json")

    def test_commit_message_names_the_prompt_score_and_level(self):
        path = save_result(finished_session(scores={"clarifying": 3}), self.dir)
        self.assertEqual(commit_message(path), "Save interview: grocery-reorder, 3/4 (PM)")


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_folder_is_empty_history(self):
        self.assertEqual(load_history(self.dir / "nope"), [])

    def test_loads_oldest_first_and_skips_unreadable_files(self):
        (self.dir / "b.json").write_text(json.dumps(record("2026-09-17T09:00:00", clarifying=4)))
        (self.dir / "a.json").write_text(json.dumps(record("2026-09-15T09:00:00", clarifying=2)))
        (self.dir / "broken.json").write_text("{not json")
        (self.dir / "list.json").write_text("[1, 2]")
        (self.dir / "notes.md").write_text("ignored")

        history = load_history(self.dir)

        self.assertEqual([r["scores"]["clarifying"] for r in history], [2, 4])


class SummaryTests(unittest.TestCase):
    def test_averages_recent_scores_and_weakest_stage(self):
        history = [
            record("1", clarifying=2, pain_points=2),
            record("2", clarifying=4, pain_points=1),
            record("3", clarifying=3),
        ]
        summary = summarize(history)

        stages = {s["dimension"]: s for s in summary["stages"]}
        self.assertEqual(summary["interviews"], 3)
        self.assertEqual(stages["clarifying"]["average"], 3.0)
        self.assertEqual(stages["clarifying"]["recent"], [2, 4, 3])
        self.assertEqual(stages["pain_points"]["average"], 1.5)
        self.assertIsNone(stages["strategy"]["average"])
        self.assertEqual(summary["weakest"], "Pain points")

    def test_recent_keeps_only_the_latest_scores(self):
        history = [record(str(i), mvp=1 + i % 4) for i in range(RECENT + 3)]
        stage = [s for s in summarize(history)["stages"] if s["dimension"] == "mvp"][0]
        self.assertEqual(len(stage["recent"]), RECENT)
        self.assertEqual(stage["count"], RECENT + 3)

    def test_no_history_has_no_weakest_stage(self):
        self.assertIsNone(summarize([])["weakest"])

    def test_interviewer_summary(self):
        self.assertEqual(summary_for_interviewer([]), "")
        text = summary_for_interviewer([record("1", clarifying=2), record("2", clarifying=3)])
        self.assertIn("2 previous interviews.", text)
        self.assertIn("Clarify: average 2.5 over 2; most recent 2, 3", text)
        self.assertIn("Strategy: never assessed", text)
        self.assertIn("Weakest stage so far: Clarify.", text)

    def test_overview_lists_interviews_newest_first(self):
        old = dict(record("2026-09-15T09:00:00", clarifying=2), total=2, possible=4)
        new = dict(record("2026-09-17T09:00:00", clarifying=4), total=4, possible=4)
        data = overview([old, new])
        self.assertEqual([h["total"] for h in data["history"]], [4, 2])
        self.assertEqual(data["history"][0]["scores"][0], {"label": "Clarify", "score": 4})


class InstructionsHistoryTests(unittest.TestCase):
    def test_history_goes_in_with_the_rule_that_it_never_changes_a_score(self):
        state = InterviewState(prompt=PROMPTS["grocery-reorder"])
        text = build_system(state, history_summary="3 previous interviews.\nWeakest stage so far: MVP.")
        self.assertIn("Weakest stage so far: MVP.", text)
        self.assertIn("It must never change a score.", text)
        self.assertIn("No previous interviews.", build_system(state))


if __name__ == "__main__":
    unittest.main()
