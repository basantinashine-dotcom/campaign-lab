"""One live interview, independent of how it is displayed.

The terminal (``product_sense_mock.py``) and the web page (``web.py``) both
drive a ``LiveSession``. Neither of them talks to Claude directly, so they
cannot drift apart.

A session never reads input or prints. Each call runs the agent loop until the
interviewer needs the candidate, then returns a list of events describing what
happened in between:

    {"kind": "interviewer", "text": "..."}
    {"kind": "tool", "name": "...", "input": {...}, "result": {...}, "is_error": False}
    {"kind": "notice", "text": "..."}

The Anthropic client is passed in rather than created here, which is what lets
the tests drive the loop with a fake client and no API key.
"""

import json

from interview import DIMENSIONS, STAGES, TOOLS, InterviewError, dispatch

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

# A ceiling on model turns so a loop that stops converging cannot bill forever.
# A complete interview is normally 20-30 turns.
MAX_TURNS = 80

KICKOFF = "I'm ready. Ask me your first question."
STOP_REQUEST = (
    "I'd like to stop here. Please end the interview and give me the debrief for "
    "what we covered."
)


class SessionError(ValueError):
    """Raised when a session is asked to do something its state does not allow."""


def build_system(prompt):
    stage_lines = "\n".join(
        "  %d. %s -- %s (budget: %d answer%s)"
        % (i + 1, s.key, s.brief, s.probe_budget, "" if s.probe_budget == 1 else "s")
        for i, s in enumerate(STAGES)
    )
    rubric_lines = "\n".join("  %s: %s" % (k, v) for k, v in DIMENSIONS.items())
    return """You are running a practice product sense interview. The person you are \
talking to is rehearsing, not being hired.

THE PROMPT YOU ARE INTERVIEWING ON
%s

PRIVATE NOTES -- context for you only, never read these out
%s

HOW TO RUN IT
- Ask exactly one question, then stop and wait. Never stack two questions into one turn.
- Stay in role. Do not coach, hint, praise, or evaluate out loud while the interview is
  running. Every judgement goes into record_signal; all feedback waits for the debrief.
- Call record_signal as soon as you can judge a dimension. Do not save it all for the end.
- Tool results tell you what is still uncovered and how many probes remain. When the probes
  are gone, score what you actually heard and call advance_stage. Do not argue with the
  budget and do not ask for more turns.
- After the final stage, thank them in one line, then call end_interview.
- If they ask to stop early, call end_interview with whatever you have. If they never
  answered anything, say so plainly and do not invent strengths.

STAGES
%s

RUBRIC
%s

SCORING
1 missing, 2 partial, 3 solid, 4 strong. A 3 is a genuinely good answer. Reserve 4 for
something you would repeat to a colleague. Inflated scores make this exercise worthless,
so score what was said, not what you think they meant.

TONE
Warm, direct, unhurried. Press once on a vague answer -- "which one?", "why that group?"
-- then take what you get and move on. Not sycophantic, not hostile. A short question is
usually better than a long one.""" % (
        prompt.question,
        prompt.context,
        stage_lines,
        rubric_lines,
    )


class LiveSession:
    """An interview run by Claude through the Messages API."""

    mode = "live"

    def __init__(self, state, client, model=MODEL, effort="high", max_turns=MAX_TURNS):
        self.state = state
        self.client = client
        self.model = model
        self.effort = effort
        self.max_turns = max_turns
        self.system = build_system(state.prompt)
        self.history = []
        self.turns = 0
        self.started = False
        self.awaiting_answer = False
        self.ended_reason = None

    @property
    def done(self):
        return self.state.finished or self.ended_reason is not None

    def start(self):
        if self.started:
            raise SessionError("This interview has already started.")
        self.started = True
        self.history.append({"role": "user", "content": KICKOFF})
        return self._run()

    def answer(self, text):
        self._require_turn()
        text = (text or "").strip()
        if not text:
            raise SessionError("An answer cannot be empty.")
        self.state.note_answer()
        self.history.append({"role": "user", "content": text})
        self.awaiting_answer = False
        return self._run()

    def quit(self):
        if self.done:
            return []
        if not self.started:
            raise SessionError("This interview has not started.")
        self.history.append({"role": "user", "content": STOP_REQUEST})
        self.awaiting_answer = False
        return self._run()

    def resume(self):
        """Carry on after an API error, without repeating the candidate's last message.

        The history already holds whatever was sent before the failure, so this
        only re-runs the loop.
        """
        if self.done or self.awaiting_answer or not self.started:
            return []
        return self._run()

    def _require_turn(self):
        if not self.started:
            raise SessionError("This interview has not started.")
        if self.done:
            raise SessionError("This interview is over.")
        if not self.awaiting_answer:
            raise SessionError("The interviewer is not waiting for an answer right now.")

    def _run(self):
        events = []
        while not self.state.finished:
            if self.turns >= self.max_turns:
                self.ended_reason = "turn_limit"
                events.append(
                    {
                        "kind": "notice",
                        "text": "Hit the %d turn ceiling before a debrief was filed."
                        % self.max_turns,
                    }
                )
                break

            self.turns += 1
            # May raise an Anthropic API error. Nothing below has run yet, so the
            # history is still consistent and resume() can pick up from here.
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system,
                tools=TOOLS,
                output_config={"effort": self.effort},
                messages=self.history,
            )

            if response.stop_reason == "refusal":
                self.ended_reason = "refusal"
                events.append(
                    {"kind": "notice", "text": "The model declined to continue this interview."}
                )
                break

            self.history.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "text" and block.text.strip():
                    events.append({"kind": "interviewer", "text": block.text.strip()})

            if response.stop_reason == "tool_use":
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    try:
                        result = dispatch(self.state, block.name, block.input)
                        is_error = False
                    except InterviewError as exc:
                        result = {"error": str(exc)}
                        is_error = True
                    events.append(
                        {
                            "kind": "tool",
                            "name": block.name,
                            "input": block.input,
                            "result": result,
                            "is_error": is_error,
                        }
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                            "is_error": is_error,
                        }
                    )
                self.history.append({"role": "user", "content": results})
                continue

            if response.stop_reason == "max_tokens":
                self.ended_reason = "max_tokens"
                events.append(
                    {"kind": "notice", "text": "The response hit the token limit. Ending here."}
                )
                break

            if not self.state.finished:
                self.awaiting_answer = True
            break
        return events


def explain_api_error(anthropic, exc, model):
    """Turn an Anthropic SDK exception into (message, retryable).

    ``anthropic`` is the imported module, passed in so this file never imports
    the SDK itself.
    """
    if isinstance(exc, anthropic.AuthenticationError):
        return (
            "Authentication failed. Set ANTHROPIC_API_KEY in the terminal before "
            "starting, or use offline mode.",
            False,
        )
    if isinstance(exc, anthropic.NotFoundError):
        return ("Model %r was not found for this account." % model, False)
    if isinstance(exc, anthropic.RateLimitError):
        retry = exc.response.headers.get("retry-after", "60")
        return ("Rate limited. Try again in about %s seconds." % retry, True)
    if isinstance(exc, anthropic.APIStatusError):
        return (
            "API error %s: %s" % (exc.status_code, exc.message),
            exc.status_code >= 500,
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return ("Could not reach the API. Check your network connection.", True)
    return None


def snapshot(session):
    """A display-ready view of a session.

    Scores are deliberately left out until the interview is over. Seeing a 2
    mid-interview changes how people answer.
    """
    state = session.state
    view = {
        "mode": session.mode,
        "prompt": {"key": state.prompt.key, "question": state.prompt.question},
        "stages": [s.key for s in STAGES],
        "stage_index": state.stage_index,
        "awaiting_answer": session.awaiting_answer,
        "done": session.done,
        "ended_reason": session.ended_reason,
    }
    if session.done:
        view["scorecard"] = state.scorecard()
        view["debrief"] = state.debrief
    return view
