"""A deterministic interviewer that runs without an API key.

This drives the same ``InterviewState`` as the live agent, but replaces the
model with scripted questions and a transparent scoring heuristic. It exists so
that the flow is runnable and testable by anyone who clones the repository,
including in CI.

The heuristic is crude on purpose. It measures whether an answer *looks* like
it engages a dimension -- length, a keyword, a sign of specificity -- not
whether the thinking behind it is any good. It cannot tell a sharp segment
choice from a confident wrong one. Read its scores as a check that the machinery
works, never as feedback on your product sense. For that, run the live agent.
"""

import re

from interview import DIMENSIONS, MAX_SCORE, InterviewState, PROMPTS

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

    score = 1 + sum((substantial, on_topic, specific))
    score = min(score, MAX_SCORE)

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


def run_offline(state, ask, say):
    """Run a full scripted interview.

    ``ask(question) -> str`` collects one candidate answer; ``say(text)``
    delivers interviewer speech. Passing these in keeps this module free of
    stdin and stdout so tests can drive it directly.
    """
    say(
        "Offline mode: scripted questions and keyword scoring, no model involved.\n"
        "Your prompt:\n\n  %s\n" % state.prompt.question
    )

    while not state.past_last_stage:
        stage = state.stage
        opening, follow_up = STAGE_QUESTIONS[stage.key]

        answer = ask(opening)
        state.note_answer()
        best = {}
        for dimension in stage.focus:
            best[dimension] = heuristic_score(dimension, answer)

        needs_more = any(best[d][0] < SOLID for d in stage.focus)
        if needs_more and state.probes_remaining > 0:
            answer = ask(follow_up)
            state.note_answer()
            for dimension in stage.focus:
                candidate = heuristic_score(dimension, answer)
                if candidate[0] > best[dimension][0]:
                    best[dimension] = candidate

        for dimension in stage.focus:
            score, evidence, gap = best[dimension]
            state.record_signal(dimension, score, evidence, gap)

        state.advance_stage("Scripted stage complete.")

    _file_debrief(state)
    return state


def _file_debrief(state):
    """Synthesize a debrief from the recorded signals, with no model involved."""
    card = state.scorecard()
    strong = [r for r in card["rows"] if r["score"] is not None and r["score"] >= SOLID]
    weak = [r for r in card["rows"] if r["score"] is not None and r["score"] < SOLID]

    if card["possible"] and card["total"] >= card["possible"] * 0.75:
        headline = "Your answers engaged most of the rubric at length."
    elif card["possible"] and card["total"] >= card["possible"] * 0.5:
        headline = "Your answers reached about half the rubric with any substance."
    else:
        headline = "Most answers were too short or too general for this heuristic to credit."

    strengths = [
        "%s: %s" % (r["dimension"].replace("_", " "), r["evidence"]) for r in strong
    ] or ["Nothing scored solid, but you completed every stage of the interview."]

    improvements = [
        "%s -- %s" % (r["dimension"].replace("_", " "), r["gap"]) for r in weak
    ] or ["Run the live agent; this heuristic has nothing further to say."]

    weakest = state.weakest()
    alternatives = [k for k in PROMPTS if k != state.prompt.key]
    suggestion = PROMPTS[alternatives[0]].question if alternatives else state.prompt.question
    if weakest:
        next_prompt = (
            "Your lowest dimension was %s. Try this prompt next and answer it with that "
            "dimension in mind: %s"
            % (weakest.replace("_", " "), suggestion)
        )
    else:
        next_prompt = suggestion

    state.end_interview(
        headline=headline,
        strengths=strengths,
        improvements=improvements,
        next_prompt=next_prompt,
    )


def new_state(prompt_key):
    """Convenience constructor used by the CLI and the tests."""
    if prompt_key not in PROMPTS:
        raise KeyError(prompt_key)
    return InterviewState(prompt=PROMPTS[prompt_key])


__all__ = [
    "DIMENSIONS",
    "STAGE_QUESTIONS",
    "heuristic_score",
    "new_state",
    "run_offline",
]
