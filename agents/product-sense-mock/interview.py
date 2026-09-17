"""Interview structure for the Product Sense Mock agent.

Pure data, validation, and state transitions. No network calls, no Anthropic
SDK import, and no printing. Both the live agent (``session.py``) and the
offline interviewer (``offline.py``) drive the same state machine from here,
which is what makes the whole flow testable without an API key.
"""

from dataclasses import dataclass, field

MIN_SCORE = 1
MAX_SCORE = 4

SCORE_LABELS = {
    1: "missing",
    2: "partial",
    3: "solid",
    4: "strong",
}

# Each interview type (a Track, below) has its own rubric: one dimension per
# stage, in scorecard order. Dimension keys are unique across tracks.
PRODUCT_SENSE_DIMENSIONS = {
    "clarifying": (
        "Asks only questions whose answers would change what gets built, and states "
        "product context as assumptions instead of asking the interviewer to decide."
    ),
    "strategy": (
        "Ties the opportunity to the company's mission and strategy, and explains why "
        "this company would build it now."
    ),
    "user_segmentation": (
        "Segments users by what the product enables, picks one group quickly, and gives "
        "a logical rationale with rough sizing."
    ),
    "pain_points": (
        "Finds genuinely distinct pain points, prioritizes one, and names the root "
        "problem behind it."
    ),
    "solutions": (
        "Generates meaningfully different ideas anchored to the root problem, including "
        "a moonshot."
    ),
    "mvp": (
        "Defines the smallest version that delivers real value, names what waits and "
        "why, and says how success would be measured, including a counter-metric."
    ),
}


@dataclass(frozen=True)
class Stage:
    """One phase of the interview, targeting one rubric dimension.

    ``probe_budget`` is the number of candidate messages the interviewer may
    spend here. When it runs out, the tool result says so and the interviewer
    has to move on. That budget is the reason this is a state machine and not
    just a long system prompt: the limit is enforced by the harness rather than
    requested of the model.
    """

    key: str
    label: str
    focus: tuple
    brief: str
    probe_budget: int


PRODUCT_SENSE_STAGES = (
    Stage(
        "clarify",
        "Clarify",
        ("clarifying",),
        "The candidate asks you questions. Answer them from the company brief. If they ask "
        "you to decide product context for them, ask what they would assume instead.",
        3,
    ),
    Stage(
        "strategy",
        "Strategy",
        ("strategy",),
        "Ask why this company would build this, and why now: mission, strategy, and "
        "competitive position.",
        2,
    ),
    Stage(
        "users",
        "Users",
        ("user_segmentation",),
        "Ask them to segment the users and commit to one group, with a rationale and rough "
        "sizing.",
        2,
    ),
    Stage(
        "pain_points",
        "Pain points",
        ("pain_points",),
        "Ask for that group's pain points, then which one they would solve and the root "
        "problem behind it.",
        2,
    ),
    Stage(
        "solutions",
        "Solutions",
        ("solutions",),
        "Ask for solutions that are genuinely different from each other, tied to the root "
        "problem. Probe for a moonshot if none comes up.",
        2,
    ),
    Stage(
        "mvp",
        "MVP",
        ("mvp",),
        "Ask for the smallest version worth building and what waits, then how they would "
        "know it worked and what would tell them it was doing harm.",
        2,
    ),
)


@dataclass(frozen=True)
class Level:
    """The seniority the candidate is practising for.

    It changes the bar the interviewer judges against, not the stages or the
    questions. ``bars`` holds one bar per track, keyed by track key.
    """

    key: str
    label: str
    bars: dict

    def bar_for(self, track_key):
        return self.bars[track_key]

    @property
    def bar(self):
        """The product sense bar, kept under the old name."""
        return self.bars["product-sense"]


LEVELS = {
    level.key: level
    for level in (
        Level(
            "pm",
            "PM",
            {
                "product-sense": (
                    "Below Senior PM. In Strategy, a clear mission and a sensible north star, "
                    "covered briefly, is a solid answer; do not mark them down for skipping "
                    "competitive analysis or a long-term arc. Elsewhere, reward clear structure "
                    "and decisiveness over depth of market knowledge."
                ),
                "ai-pm": (
                    "Below Senior PM. A clear scope, one sensible success metric with at least "
                    "one guardrail, a working prompt with some narration, and a concrete list of "
                    "what the model must not do alone is a solid answer. Do not mark them down "
                    "for missing organisational detail such as approval chains."
                ),
            },
        ),
        Level(
            "senior",
            "Senior PM+",
            {
                "product-sense": (
                    "Senior PM and above. In Strategy, a solid answer also explains why this "
                    "company specifically, names the competitive gap, and sketches the longer "
                    "arc; at this level Strategy often decides the interview. Expect sizing with "
                    "stated reasoning in Users, and specific, justified cuts in MVP."
                ),
                "ai-pm": (
                    "Senior PM and above. Expect scope tied to a business outcome, guardrails "
                    "with explicit stop thresholds, and a prompt iteration grounded in what the "
                    "output actually showed. In Risk & judgment, a solid answer shows ownership: "
                    "who approves what, how trust is earned before the model is given more "
                    "autonomy, and how they would bring legal, operations, or other stakeholders "
                    "along. Reward judgment over knowledge of particular models."
                ),
            },
        ),
    )
}

DEFAULT_LEVEL = "pm"


@dataclass(frozen=True)
class Prompt:
    """A practice question, plus private material for the interviewer only.

    ``context`` tells the interviewer what strong answers tend to cover.
    ``brief`` is the company situation the interviewer answers clarifying
    questions from. Neither is shown to the candidate unless asked.
    """

    key: str
    question: str
    context: str
    brief: str
    track: str = "product-sense"


PROMPTS = {
    p.key: p
    for p in (
        Prompt(
            "grocery-reorder",
            "Design a feature that helps first-time grocery delivery customers place a "
            "second order.",
            "Strong answers separate the reasons a first order does not repeat (basket "
            "rebuild effort, delivery slot friction, substitution disappointment, price "
            "shock at checkout) and pick one instead of solving all four.",
            "Fictional company: Basket, a grocery delivery app in 12 metro areas, about 1.5 "
            "million monthly customers, partnered with regional supermarket chains. Mission: "
            "give people their evenings back. Competes with larger national delivery apps "
            "on price and speed and cannot win either outright. Only 38% of first-time "
            "customers order again within 30 days. Growth has come from heavy first-order "
            "discounts, which the board wants reduced this year. Mobile apps on iOS and "
            "Android; no hardware. Timeline is open; a small team of about 8.",
        ),
        Prompt(
            "small-creators",
            "How would you improve Instagram for creators with fewer than 1,000 followers?",
            "Strong answers resist the pull of 'more reach' and get specific about what a "
            "small creator actually lacks: feedback signal, a reason to post again, and a "
            "sense that the next post is worth the effort. Watch for metrics that would be "
            "gamed by posting more.",
            "Instagram, part of Meta. Instagram's mission: bring you closer to the people "
            "and things you love. Competes for creators with TikTok, YouTube Shorts, and "
            "Snapchat, where small accounts can break out through recommendation feeds. "
            "For this exercise, assume most accounts that post have fewer than 1,000 "
            "followers and many stop posting within their first few months; these are "
            "practice assumptions, not published figures. Treat this as the core Instagram app, all "
            "markets, no fixed deadline. The candidate may assume reasonable figures if "
            "they state them.",
        ),
        Prompt(
            "notes-decline",
            "Weekly active users of a note-taking app fell 8% month over month. Work out "
            "why, then decide what to do about it.",
            "This is a diagnosis prompt, not a design one. Strong answers segment before "
            "theorising (new versus existing users, platform, cohort), separate a "
            "measurement artifact from a real decline, and say what evidence would change "
            "their mind.",
            "Fictional company: Jotter, a freemium note-taking app with about 4 million "
            "weekly active users across web, iOS, Android, and desktop. Mission: help people "
            "remember what matters. Competes with larger all-in-one workspace tools and with "
            "built-in phone notes apps. Six weeks ago it shipped a redesigned mobile editor "
            "and changed how 'active' is logged on desktop. School term ended in several "
            "large markets last month. Paid conversion is steady. If asked for data the "
            "candidate would not have, say it is available and ask what they would look for.",
        ),
        Prompt(
            "commute-podcasts",
            "Design something for people who listen to podcasts during a commute.",
            "Strong answers use the constraint of the commute itself: hands busy, eyes busy, "
            "a duration that is fixed and known in advance, interruptions, patchy "
            "connectivity. Weak answers design a generic podcast app.",
            "Fictional company: Earshot, an independent podcast app with about 3 million "
            "monthly listeners, strongest in North America and Europe. Mission: make every "
            "spare minute worth listening to. Competes with the large music-and-podcast "
            "streaming apps and the phone makers' built-in podcast apps. Revenue is a "
            "premium subscription. It has integrations with major car systems and "
            "smartwatches, but no hardware of its own. No fixed timeline.",
        ),
        Prompt(
            "support-replies",
            "Design an AI assistant that drafts replies for a customer support team.",
            "Strong answers keep a human sending by default and treat drafts as the product, "
            "not auto-replies. Good metrics: share of drafts sent with light edits, handle "
            "time; guardrails: customer satisfaction, reopened tickets, and replies that "
            "promise refunds or exceptions the policy does not allow. A good prompt demo "
            "grounds the draft in a help-centre article and the ticket, not the model's "
            "general knowledge. Refunds, account changes, and policy exceptions should never "
            "be the model's call alone.",
            "Fictional company: Helpline, customer support software used by about 2,000 "
            "mid-size online retailers. Mission: make every customer feel answered. Competes "
            "with large helpdesk suites that are all adding AI features. Agents handle about "
            "60 tickets a day; median first response is 9 hours. Refunds and account changes "
            "need a team lead's approval. Available data: past tickets with agent replies, "
            "help-centre articles, and each retailer's tone guidelines. Retailers' legal teams "
            "worry about the assistant promising things the policy does not allow.",
            "ai-pm",
        ),
        Prompt(
            "visit-summaries",
            "Add AI-written summaries of doctor visit notes to a patient health app.",
            "The highest-stakes prompt. Strong answers say plainly that the summary must not "
            "add medical advice or anything not in the note, keep clinicians accountable, and "
            "design escalation for anything alarming or unclear. Good metrics: patients "
            "understanding their next steps, fewer 'what does this mean' calls; guardrails: "
            "summary errors against the source note, and patients acting on something the "
            "note did not say. A good prompt demo summarises a sample note and checks it "
            "against the original. Stakeholders include clinicians and compliance.",
            "Fictional company: CareBridge, a patient portal used by 40 clinics and about "
            "600,000 patients. Mission: help patients understand and act on their care. "
            "Clinicians' visit notes are written for other clinicians and full of jargon, and "
            "clinics get many calls asking what notes mean. Clinicians are legally "
            "responsible for medical advice and have no time to review extra documents. "
            "Health privacy rules apply. The portal is used in English and Spanish.",
            "ai-pm",
        ),
        Prompt(
            "expense-reconciliation",
            "Build an AI agent that helps small businesses categorize and reconcile their "
            "expenses.",
            "An agent close to money and taxes. Strong answers have the agent suggest rather "
            "than post, use confidence thresholds and an audit trail, and leave anything that "
            "moves money or affects filings to a person. Good metrics: time owners spend on "
            "books, share of suggestions accepted; guardrails: corrections found by the "
            "accountant, reversed entries. A good prompt demo categorises a few messy bank "
            "transactions and says how it would handle uncertainty.",
            "Fictional company: Ledgerly, a bookkeeping app for about 250,000 small "
            "businesses with bank feeds connected. Mission: give owners back the hours they "
            "spend on their books. Owners spend about 5 hours a month categorising "
            "transactions; many have an accountant who reviews the books each quarter. "
            "Mistakes can change tax filings. Competes with large accounting suites that use "
            "rule-based auto-categorisation.",
            "ai-pm",
        ),
        Prompt(
            "job-matching",
            "Use an LLM to match job seekers to open roles in a hiring marketplace.",
            "Strong answers keep the model recommending and ranking, never rejecting "
            "candidates on its own, and treat fairness as a first-class guardrail with regular "
            "checks for different outcomes across groups. Good metrics: interviews per "
            "application, time to hire; guardrails: outcome gaps between groups, employer "
            "complaints about poor matches. A good prompt demo matches one candidate profile "
            "to a few roles and explains why. Stakeholders include legal and employers.",
            "Fictional company: Shortlist, a hiring marketplace for hourly and entry-level "
            "roles with about 3 million job seekers and 40,000 employers. Mission: get people "
            "into good work faster. Seekers apply to 30 or more jobs on average; employers "
            "complain about applicants who are not qualified. Anti-discrimination law applies "
            "to hiring decisions, and some places regulate automated hiring tools. Profiles "
            "include work history, availability, and location.",
            "ai-pm",
        ),
    )
}


AI_PM_DIMENSIONS = {
    "scope": (
        "Scopes the problem out loud before solving: what the user is trying to do, what "
        "done looks like, and what is deliberately not being solved."
    ),
    "hypothesis_metrics": (
        "States a hypothesis, one main success metric, and guardrail metrics with an "
        "explicit condition for stopping the test."
    ),
    "prompt_demo": (
        "Writes a small, clean prompt, runs it, narrates what they are doing and seeing, and "
        "says what they would change next."
    ),
    "risk_judgment": (
        "Names what the model must not act on alone, and how they would manage risk, build "
        "trust, weigh tradeoffs, and align stakeholders."
    ),
}

AI_PM_STAGES = (
    Stage(
        "scope",
        "Scope",
        ("scope",),
        "Ask them to scope the problem out loud: what the user is trying to do, what done "
        "looks like, and what they are deliberately not solving.",
        2,
    ),
    Stage(
        "hypothesis",
        "Hypothesis & metrics",
        ("hypothesis_metrics",),
        "Ask for their hypothesis, the one metric that would show it worked, and the "
        "guardrail metrics that would make them stop the test.",
        2,
    ),
    Stage(
        "prompt_demo",
        "Prompt demo",
        ("prompt_demo",),
        "Ask them to write a small prompt for the core AI behaviour and run it with the "
        "prompt runner on their screen, narrating as they go, then say what they would "
        "change next.",
        3,
    ),
    Stage(
        "risk",
        "Risk & judgment",
        ("risk_judgment",),
        "Ask what they would not let the model act on alone, and how they would manage "
        "risk, earn trust, weigh tradeoffs, and align stakeholders.",
        2,
    ),
)


@dataclass(frozen=True)
class Track:
    """One kind of interview: its own stages, rubric, and practice questions.

    ``runner_stage`` names the stage, if any, where the candidate can run their
    own prompt against a model and the interviewer judges the result.
    """

    key: str
    label: str
    description: str
    dimensions: dict
    stages: tuple
    default_prompt: str
    runner_stage: str = ""


TRACKS = {
    track.key: track
    for track in (
        Track(
            "product-sense",
            "Product sense",
            "a practice product sense interview",
            PRODUCT_SENSE_DIMENSIONS,
            PRODUCT_SENSE_STAGES,
            "grocery-reorder",
        ),
        Track(
            "ai-pm",
            "AI PM",
            "a practice AI product management interview",
            AI_PM_DIMENSIONS,
            AI_PM_STAGES,
            "support-replies",
            runner_stage="prompt_demo",
        ),
    )
}

DEFAULT_TRACK = "product-sense"
DEFAULT_PROMPT = TRACKS[DEFAULT_TRACK].default_prompt

# The product sense rubric and stages, kept under their original names.
DIMENSIONS = PRODUCT_SENSE_DIMENSIONS
STAGES = PRODUCT_SENSE_STAGES


def prompts_for(track_key):
    return [p for p in PROMPTS.values() if p.track == track_key]


class InterviewError(ValueError):
    """Raised when a tool call carries input the state machine cannot accept.

    The agent loop turns this into an ``is_error`` tool result so the model can
    correct itself, rather than crashing the interview.
    """


@dataclass
class Signal:
    """One recorded judgement about one rubric dimension."""

    dimension: str
    score: int
    evidence: str
    gap: str


@dataclass
class InterviewState:
    """Live state of a single interview.

    Every mutation goes through one of the three tool methods below, so the
    live agent and the offline interviewer cannot drift apart.
    """

    prompt: Prompt
    level: Level = field(default_factory=lambda: LEVELS[DEFAULT_LEVEL])
    stage_index: int = 0
    probes_used: int = 0
    signals: dict = field(default_factory=dict)
    debrief: dict = None

    # --- read-only views -------------------------------------------------

    @property
    def track(self):
        return TRACKS[self.prompt.track]

    @property
    def finished(self):
        return self.debrief is not None

    @property
    def past_last_stage(self):
        return self.stage_index >= len(self.track.stages)

    @property
    def stage(self):
        """The current stage, or None once every stage has been advanced past."""
        if self.past_last_stage:
            return None
        return self.track.stages[self.stage_index]

    @property
    def probes_remaining(self):
        stage = self.stage
        if stage is None:
            return 0
        return max(0, stage.probe_budget - self.probes_used)

    def uncovered(self):
        """Dimensions in the current stage that have no signal recorded yet."""
        stage = self.stage
        if stage is None:
            return []
        return [d for d in stage.focus if d not in self.signals]

    def note_answer(self):
        """Count one candidate message against the current stage's probe budget."""
        self.probes_used += 1

    # --- tool implementations --------------------------------------------

    def record_signal(self, dimension, score, evidence, gap):
        if dimension not in self.track.dimensions:
            raise InterviewError(
                "Unknown dimension %r. Valid dimensions: %s"
                % (dimension, ", ".join(self.track.dimensions))
            )
        if isinstance(score, bool) or not isinstance(score, int):
            raise InterviewError("Score must be an integer, got %r." % (score,))
        if not MIN_SCORE <= score <= MAX_SCORE:
            raise InterviewError(
                "Score must be between %d and %d, got %d."
                % (MIN_SCORE, MAX_SCORE, score)
            )
        if not evidence or not evidence.strip():
            raise InterviewError(
                "Evidence cannot be empty. Quote or closely paraphrase what the candidate "
                "said."
            )
        if score < MAX_SCORE and (not gap or not gap.strip()):
            raise InterviewError(
                "A score below %d needs a gap: say what a higher score would have required."
                % MAX_SCORE
            )

        self.signals[dimension] = Signal(
            dimension=dimension,
            score=score,
            evidence=evidence.strip(),
            gap=(gap or "").strip(),
        )

        stage = self.stage
        uncovered = self.uncovered()
        remaining = self.probes_remaining

        if stage is None:
            guidance = "Every stage is done. Call end_interview."
        elif uncovered and remaining > 0:
            guidance = (
                "Still uncovered in this stage: %s. You have %d probe(s) left, so ask "
                "another question." % (", ".join(uncovered), remaining)
            )
        elif uncovered and remaining == 0:
            guidance = (
                "Out of probes for this stage. Score %s from what you have already heard, "
                "then call advance_stage." % ", ".join(uncovered)
            )
        else:
            guidance = "Every dimension in this stage is recorded. Call advance_stage."

        return {
            "recorded": {
                "dimension": dimension,
                "score": score,
                "label": SCORE_LABELS[score],
            },
            "stage": stage.key if stage else "debrief",
            "stage_uncovered": uncovered,
            "probes_remaining": remaining,
            "guidance": guidance,
        }

    def advance_stage(self, reason):
        if self.past_last_stage:
            raise InterviewError("Already past the final stage. Call end_interview instead.")
        if not reason or not reason.strip():
            raise InterviewError("Give a one-sentence reason for advancing.")

        left_uncovered = self.uncovered()
        self.stage_index += 1
        self.probes_used = 0

        stage = self.stage
        if stage is None:
            return {
                "stage": "debrief",
                "left_unassessed": left_uncovered,
                "guidance": "Every stage is done. Thank the candidate, then call end_interview.",
            }

        return {
            "stage": stage.key,
            "focus": list(stage.focus),
            "brief": stage.brief,
            "probe_budget": stage.probe_budget,
            "probes_remaining": stage.probe_budget,
            "stages_remaining": len(self.track.stages) - self.stage_index - 1,
            "left_unassessed": left_uncovered,
            "guidance": "Open the %s stage with one question." % stage.label,
        }

    def end_interview(self, headline, strengths, improvements, next_prompt):
        if self.finished:
            raise InterviewError("This interview has already been ended.")
        if not headline or not headline.strip():
            raise InterviewError("Headline cannot be empty.")
        for name, items in (("strengths", strengths), ("improvements", improvements)):
            if not isinstance(items, list):
                raise InterviewError("%s must be a list." % name)
            if any(not str(i).strip() for i in items):
                raise InterviewError("%s cannot contain blank entries." % name)
        if not improvements:
            raise InterviewError("improvements must name at least one change.")
        # Strengths have to be earned by something the candidate said. With
        # nothing assessed there is nothing to praise, and requiring an entry
        # anyway pushes the model into inventing one.
        if self.signals and not strengths:
            raise InterviewError(
                "strengths cannot be empty once something has been assessed."
            )
        if not self.signals and strengths:
            raise InterviewError(
                "Nothing was assessed, so there is no evidence for strengths. "
                "Pass an empty list."
            )

        self.debrief = {
            "headline": headline.strip(),
            "strengths": [str(i).strip() for i in strengths],
            "improvements": [str(i).strip() for i in improvements],
            "next_prompt": (next_prompt or "").strip(),
        }
        return {"status": "debrief_filed", "scorecard": self.scorecard()}

    # --- reporting --------------------------------------------------------

    def scorecard(self):
        """Every dimension, in rubric order, with unassessed ones marked.

        The total is out of the assessed dimensions only. Advancing a stage
        early can leave a dimension unscored, and silently counting that as a
        zero would be a worse lie than saying it was never assessed.
        """
        rows = []
        for dimension, description in self.track.dimensions.items():
            signal = self.signals.get(dimension)
            rows.append(
                {
                    "dimension": dimension,
                    "label_text": dimension_label(dimension),
                    "description": description,
                    "score": signal.score if signal else None,
                    "label": SCORE_LABELS[signal.score] if signal else "not assessed",
                    "evidence": signal.evidence if signal else "",
                    "gap": signal.gap if signal else "",
                }
            )
        assessed = [r for r in rows if r["score"] is not None]
        return {
            "rows": rows,
            "assessed": len(assessed),
            "total": sum(r["score"] for r in assessed),
            "possible": MAX_SCORE * len(assessed),
        }

    def weakest(self):
        """The lowest-scoring assessed dimension, or None if nothing is assessed.

        Ties break in rubric order, which favours the dimension that came up
        earlier in the interview.
        """
        if not self.signals:
            return None
        ordered = [d for d in self.track.dimensions if d in self.signals]
        return min(ordered, key=lambda d: self.signals[d].score)


def dimension_label(dimension):
    """Human name for a dimension: the label of the stage that scores it."""
    for track in TRACKS.values():
        for stage in track.stages:
            if dimension in stage.focus:
                return stage.label
    return dimension.replace("_", " ")


# --- tool schemas --------------------------------------------------------
#
# ``strict`` makes the API guarantee these inputs validate against the schema,
# which is why every object sets ``additionalProperties: False`` and lists all
# of its properties in ``required``. The state machine still validates on top
# of that, because a JSON schema cannot express "a score below 4 needs a gap".

def _build_tools(dimensions):
        return [
        {
            "name": "record_signal",
            "description": (
                "Record what the candidate demonstrated on ONE rubric dimension. Call this as "
                "soon as you can judge a dimension, before deciding whether to probe again. The "
                "result tells you which dimensions in this stage are still uncovered and how "
                "many probes you have left."
            ),
            "strict": True,
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "dimension": {
                        "type": "string",
                        "enum": list(dimensions),
                        "description": "Which rubric dimension this judgement is about.",
                    },
                    "score": {
                        "type": "integer",
                        "enum": [1, 2, 3, 4],
                        "description": "1 missing, 2 partial, 3 solid, 4 strong.",
                    },
                    "evidence": {
                        "type": "string",
                        "description": (
                            "A short quote or close paraphrase of what the candidate actually "
                            "said, not your opinion of it."
                        ),
                    },
                    "gap": {
                        "type": "string",
                        "description": (
                            "What a higher score would have required. Pass an empty string only "
                            "for a score of 4."
                        ),
                    },
                },
                "required": ["dimension", "score", "evidence", "gap"],
            },
        },
        {
            "name": "advance_stage",
            "description": (
                "Move the interview to the next stage. Call this once the current stage's "
                "dimension is recorded, or when a tool result tells you the probe budget is "
                "spent. The result gives you the next stage's focus and budget."
            ),
            "strict": True,
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "One sentence on why this stage is done.",
                    }
                },
                "required": ["reason"],
            },
        },
        {
            "name": "end_interview",
            "description": (
                "End the interview and file the debrief. Call this after the final stage has "
                "been advanced past, or if the candidate asks to stop early."
            ),
            "strict": True,
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "headline": {
                        "type": "string",
                        "description": "One sentence verdict on the interview overall.",
                    },
                    "strengths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Two or three things the candidate did well, each tied to something "
                            "they actually said. Pass an empty list if nothing was assessed."
                        ),
                    },
                    "improvements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Two or three specific changes that would raise a score, each naming "
                            "the stage it would move."
                        ),
                    },
                    "next_prompt": {
                        "type": "string",
                        "description": (
                            "A different practice prompt aimed at their weakest stage."
                        ),
                    },
                },
                "required": ["headline", "strengths", "improvements", "next_prompt"],
            },
        },
    ]


TRACK_TOOLS = {key: _build_tools(track.dimensions) for key, track in TRACKS.items()}

# Product sense tools, kept under the old name.
TOOLS = TRACK_TOOLS["product-sense"]


def dispatch(state, name, tool_input):
    """Route one tool call to the state machine.

    Raises InterviewError for anything the state machine rejects. The caller is
    expected to hand that back to the model as an error tool result.
    """
    if name == "record_signal":
        return state.record_signal(
            dimension=tool_input.get("dimension"),
            score=tool_input.get("score"),
            evidence=tool_input.get("evidence", ""),
            gap=tool_input.get("gap", ""),
        )
    if name == "advance_stage":
        return state.advance_stage(reason=tool_input.get("reason", ""))
    if name == "end_interview":
        return state.end_interview(
            headline=tool_input.get("headline", ""),
            strengths=tool_input.get("strengths", []),
            improvements=tool_input.get("improvements", []),
            next_prompt=tool_input.get("next_prompt", ""),
        )
    raise InterviewError("Unknown tool: %r" % (name,))


def render_debrief(state, when=None):
    """Render the scorecard and debrief as Markdown."""
    card = state.scorecard()
    debrief = state.debrief or {}
    lines = ["# Product sense debrief", ""]
    lines.append("**Prompt:** %s" % state.prompt.question)
    lines.append("")
    lines.append("**Interview:** %s" % state.track.label)
    lines.append("")
    lines.append("**Level:** %s" % state.level.label)
    lines.append("")
    if when:
        lines.append("**Date:** %s" % when)
        lines.append("")

    if debrief.get("headline"):
        lines.append("> %s" % debrief["headline"])
        lines.append("")

    if card["assessed"]:
        lines.append(
            "**Score: %d / %d** across %d assessed stage%s."
            % (
                card["total"],
                card["possible"],
                card["assessed"],
                "" if card["assessed"] == 1 else "s",
            )
        )
    else:
        lines.append("**Score:** nothing was assessed before the interview ended.")
    lines.append("")

    lines.append("| Stage | Score | What you showed | What would raise it |")
    lines.append("| --- | --- | --- | --- |")
    for row in card["rows"]:
        score = (
            "%d %s" % (row["score"], row["label"])
            if row["score"] is not None
            else "not assessed"
        )
        lines.append(
            "| %s | %s | %s | %s |"
            % (
                row["label_text"],
                score,
                _cell(row["evidence"]),
                _cell(row["gap"]),
            )
        )
    lines.append("")

    if debrief.get("strengths"):
        lines.append("## What worked")
        lines.append("")
        lines.extend("- %s" % s for s in debrief["strengths"])
        lines.append("")
    if debrief.get("improvements"):
        lines.append("## What to change")
        lines.append("")
        lines.extend("- %s" % s for s in debrief["improvements"])
        lines.append("")
    if debrief.get("next_prompt"):
        lines.append("## Try this next")
        lines.append("")
        lines.append(debrief["next_prompt"])
        lines.append("")

    lines.append(
        "Scores are one interviewer's read of one practice conversation. They are not a "
        "hiring signal."
    )
    return "\n".join(lines)


def _cell(text):
    """Make a string safe for a Markdown table cell."""
    if not text:
        return "--"
    return text.replace("|", "\\|").replace("\n", " ").strip()
