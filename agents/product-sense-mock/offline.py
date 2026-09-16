"""A deterministic interviewer that runs without an API key.

This drives the same ``InterviewState`` as the live agent, but replaces the
model with scripted questions and a transparent scoring heuristic. It exists so
that the flow is runnable and testable by anyone who clones the repository,
including in CI, and so the web page can be tried without spending credits.

The heuristic is crude on purpose. It measures whether an answer *looks* like
it engages a dimension -- length, a keyword, a sign of specificity -- not
whether the thinking behind it is any good. It cannot tell a sharp segment
choice from a confident wrong one. Read its scores as a check that the machinery
works, never as feedback on your product sense. For that, run the live agent.

``OfflineSession`` has the same shape as ``session.LiveSession`` -- ``start``,
``answer``, ``quit``, ``resume``, ``done``, ``awaiting_answer`` -- and returns
the same events, including tool events, so the terminal and the web page treat
both modes identically.
"""

import re

from interview import MAX_SCORE, PROMPTS, InterviewState

# Two questions per stage: the opening, and one follow-up used when the opening
# answer scores below "solid" and the probe budget allows.
STAGE_QUESTIONS = {
    "framing": (
        "Before you design anything: how are you reading this problem, and what "
        "are you actually trying to achieve?",
        "What are you deliberately leaving out of scope, and why that boundary?",
    ),
    "users": (
        "Who specifically is this for? Pick one group rather than listing several.",
        "What does that group find hard today? Be concrete about the moment it "
        "goes wrong for them.",
    ),
    "solution": (
        "What would you build for them?",
        "If you could only ship one of those, which one, and what makes it first?",
    ),
    "tradeoffs": (
        "What does that choice cost you? Who is worse off after you ship it?",
        "What would have to be true for this to be the wrong call?",
    ),
    "metrics": (
        "How would you know it worked?",
        "What would tell you it was quietly doing harm, even while your main "
        "metric went up?",
    ),
}

# Words that suggest an answer is at least reaching for the dimension.
KEYWORDS = {
    "problem_framing": (
        "goal", "assume", "scope", "clarify", "constraint", "success",
        "context", "problem", "define", "objective",
    ),
    "user_segmentation": (
        "segment", "persona", "audience", "users who", "people who",
        "first-time", "new user", "power user", "cohort", "specifically",
    ),
    "pain_points": (
        "pain", "friction", "frustrat", "struggl", "blocker", "confus",
        "drop off", "abandon", "hard to", "annoy", "give up",
    ),
    "solution": (
        "build", "feature", "prototype", "ship", "priorit", "first", "mvp",
        "instead", "flow", "screen", "nudge",
    ),
    "tradeoffs": (
        "tradeoff", "trade-off", "cost", "risk", "downside", "give up",
        "worse off", "however", "expense", "sacrifice", "cannibal",
    ),
    "metrics": (
        "metric", "measure", "rate", "retention", "conversion", "counter",
        "guardrail", "baseline", "%", "percent", "north star",
    ),
}

# Markers that an answer commits to something rather than gesturing at it.
SPECIFICITY = ("because", "so that", "for example", "instead of", "rather than")

MIN_SUBSTANTIAL_WORDS = 25
SOLID = 3


class OfflineError(ValueError):
    """Raised when an offline session is asked to do something its state does not allow."""


def heuristic_score(dimension, answer):
    """Score one answer against one dimension. Returns (score, evidence, gap).

    Three independent checks, each worth a point on top of a floor of 1:
    length, a dimension keyword, and a marker of specificity or a number.
    """
    text = (answer or "").strip()
    if not text:
        return 1, "(no answer given)", "Any answer at all would score higher than silence."

    lowered = text.lower()
    words = len(text.split())

    substantial = words >= MIN_SUBSTANTIAL_WORDS
    on_topic = any(k in lowered for k in KEYWORDS[dimension])
    specific = any(m in lowered for m in SPECIFICITY) or bool(re.search(r"\d", text))

    score = min(1 + sum((substantial, on_topic, specific)), MAX_SCORE)

    missing = []
    if not substantial:
        missing.append("more than a sentence of detail")
    if not on_topic:
        missing.append("language that engages %s directly" % dimension.replace("_", " "))
    if not specific:
        missing.append("a number, an example, or a stated reason")

    gap = (
        ""
        if score == MAX_SCORE
        else "This heuristic looked for %s and did not find it." % " and ".join(missing)
    )
    evidence = text if len(text) <= 140 else text[:137].rstrip() + "..."
    return score, evidence, gap


class OfflineSession:
    """A scripted interview with keyword scoring. No model, no key, no network."""

    mode = "offline"

    def __init__(self, state):
        self.state = state
        self.started = False
        self.awaiting_answer = False
        self.ended_reason = None
        # Best (score, evidence, gap) heard so far for each dimension in the
        # current stage, and how many questions this stage has asked.
        self._best = {}
        self._asked_in_stage = 0

    @property
    def done(self):
        return self.state.finished

    def start(self):
        if self.started:
            raise OfflineError("This interview has already started.")
        self.started = True
        events = [
            {
                "kind": "notice",
                "text": "Offline mode: scripted questions and keyword scoring, no model "
                "involved. The scores check that the flow works; they are not "
                "feedback on your answers.",
            }
        ]
        events.extend(self._ask())
        return events

    def answer(self, text):
        if not self.started:
            raise OfflineError("This interview has not started.")
        if self.done:
            raise OfflineError("This interview is over.")
        if not self.awaiting_answer:
            raise OfflineError("The interviewer is not waiting for an answer right now.")
        text = (text or "").strip()
        if not text:
            raise OfflineError("An answer cannot be empty.")

        self.awaiting_answer = False
        self.state.note_answer()
        stage = self.state.stage
        for dimension in stage.focus:
            candidate = heuristic_score(dimension, text)
            if dimension not in self._best or candidate[0] > self._best[dimension][0]:
                self._best[dimension] = candidate

        thin = any(self._best[d][0] < SOLID for d in stage.focus)
        if thin and self._asked_in_stage == 1 and self.state.probes_remaining > 0:
            return self._ask()

        events = self._record_stage()
        events.append(self._tool("advance_stage", {"reason": "Scripted stage complete."}))
        if self.state.past_last_stage:
            events.extend(self._file_debrief())
        else:
            events.extend(self._ask())
        return events

    def quit(self):
        """End now. Whatever was heard in the current stage still gets scored."""
        if self.done:
            return []
        if not self.started:
            raise OfflineError("This interview has not started.")
        self.awaiting_answer = False
        events = self._record_stage()
        events.extend(self._file_debrief())
        return events

    def resume(self):
        return []

    # --- internals -------------------------------------------------------

    def _ask(self):
        stage = self.state.stage
        opening, follow_up = STAGE_QUESTIONS[stage.key]
        question = opening if self._asked_in_stage == 0 else follow_up
        self._asked_in_stage += 1
        self.awaiting_answer = True
        return [{"kind": "interviewer", "text": question}]

    def _record_stage(self):
        events = []
        for dimension, (score, evidence, gap) in self._best.items():
            events.append(
                self._tool(
                    "record_signal",
                    {"dimension": dimension, "score": score, "evidence": evidence, "gap": gap},
                )
            )
        self._best = {}
        self._asked_in_stage = 0
        return events

    def _tool(self, name, tool_input):
        method = getattr(self.state, name)
        result = method(**tool_input)
        return {
            "kind": "tool",
            "name": name,
            "input": tool_input,
            "result": result,
            "is_error": False,
        }

    def _file_debrief(self):
        state = self.state
        card = state.scorecard()
        strong = [r for r in card["rows"] if r["score"] is not None and r["score"] >= SOLID]
        weak = [r for r in card["rows"] if r["score"] is not None and r["score"] < SOLID]

        if not card["assessed"]:
            headline = "The interview ended before any answer was scored."
        elif card["total"] >= card["possible"] * 0.75:
            headline = "Your answers engaged most of what was assessed, at length."
        elif card["total"] >= card["possible"] * 0.5:
            headline = "Your answers reached about half of what was assessed with any substance."
        else:
            headline = "Most answers were too short or too general for this heuristic to credit."

        if strong:
            strengths = [
                "%s: %s" % (r["dimension"].replace("_", " "), r["evidence"]) for r in strong
            ]
        elif card["assessed"]:
            strengths = ["Nothing scored solid, but these scores are a baseline for your next run."]
        else:
            strengths = []

        improvements = [
            "%s -- %s" % (r["dimension"].replace("_", " "), r["gap"]) for r in weak
        ]
        if not card["assessed"]:
            improvements = ["Answer at least the first question to get a scored debrief."]
        elif not improvements:
            improvements = ["Run the live agent; this heuristic has nothing further to say."]

        weakest = state.weakest()
        alternatives = [k for k in PROMPTS if k != state.prompt.key]
        suggestion = PROMPTS[alternatives[0]].question if alternatives else state.prompt.question
        if weakest and state.signals[weakest].score == MAX_SCORE:
            next_prompt = (
                "Everything assessed scored at the top of this heuristic, which says more "
                "about the heuristic than about you. Try the live interviewer on: %s" % suggestion
            )
        elif weakest:
            next_prompt = (
                "Your lowest dimension was %s. Try this prompt next and answer it with "
                "that dimension in mind: %s" % (weakest.replace("_", " "), suggestion)
            )
        else:
            next_prompt = suggestion

        return [
            self._tool(
                "end_interview",
                {
                    "headline": headline,
                    "strengths": strengths,
                    "improvements": improvements,
                    "next_prompt": next_prompt,
                },
            )
        ]


def run_offline(state, ask, say):
    """Run a whole offline interview through callbacks.

    ``ask(question)`` returns the candidate's answer, or None to stop early.
    ``say(text)`` delivers anything else the interviewer says.
    """
    session = OfflineSession(state)
    pending = session.start()
    while True:
        question = None
        for event in pending:
            if event["kind"] == "interviewer":
                question = event["text"]
            elif event["kind"] == "notice":
                say(event["text"])
        if session.done:
            return state
        answer = ask(question)
        if answer is None or not answer.strip():
            session.quit()
            return state
        pending = session.answer(answer)


def new_state(prompt_key):
    """Convenience constructor used by the CLI, the web server, and the tests."""
    if prompt_key not in PROMPTS:
        raise KeyError(prompt_key)
    return InterviewState(prompt=PROMPTS[prompt_key])
