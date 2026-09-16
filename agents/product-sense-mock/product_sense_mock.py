#!/usr/bin/env python3
"""Product sense mock interview agent.

Claude plays the interviewer; you answer. It works through five stages, scores
six rubric dimensions as it goes, and files a debrief at the end.

The agent loop here is written by hand rather than handed to the SDK's tool
runner, for one specific reason: an interview has to stop and wait for a human
between turns. The tool runner drives a conversation to completion without
yielding, which is the wrong shape for this. Everything else -- the rubric, the
stages, the probe budget -- lives in interview.py.

    python product_sense_mock.py                    # live, needs ANTHROPIC_API_KEY
    python product_sense_mock.py --offline          # scripted, no key needed
    python product_sense_mock.py --list-prompts
"""

import argparse
import json
import sys
from datetime import date

from interview import (
    DEFAULT_PROMPT,
    DIMENSIONS,
    PROMPTS,
    STAGES,
    TOOLS,
    InterviewError,
    InterviewState,
    dispatch,
    render_debrief,
)
from offline import run_offline

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

# A ceiling on model turns so a loop that stops converging cannot bill forever.
# A complete interview is normally 20-30 turns.
MAX_TURNS = 80

HELP = """
Commands
  /help     show this
  /quit     end the interview early and get the debrief for what you covered

Answers can run over several lines. Finish one with a blank line.
"""


def build_system(prompt):
    stage_lines = "\n".join(
        "  %d. %s -- %s (budget: %d answer%s)"
        % (i + 1, s.key, s.brief, s.probe_budget, "" if s.probe_budget == 1 else "s")
        for i, s in enumerate(STAGES)
    )
    rubric_lines = "\n".join(
        "  %s: %s" % (k, v) for k, v in DIMENSIONS.items()
    )
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
- If they ask to stop early, call end_interview with whatever you have.

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


def say(text):
    print("\ninterviewer > %s" % text)


def read_answer():
    """Collect one multi-line answer. Returns None if the candidate wants to stop."""
    print("\nyou > (blank line to send, /quit to stop)")
    lines = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            print()
            return "\n".join(lines).strip() or None
        stripped = line.strip()
        if stripped in ("/quit", "/stop"):
            return None
        if stripped == "/help":
            print(HELP)
            continue
        if not stripped:
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines).strip() or None


def create_message(client, anthropic, args, system, history):
    """One API call, with the error cases spelled out separately."""
    try:
        return client.messages.create(
            model=args.model,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            output_config={"effort": args.effort},
            messages=history,
        )
    except anthropic.AuthenticationError:
        raise SystemExit(
            "Authentication failed. Set ANTHROPIC_API_KEY in your environment, or run\n"
            "the interview with --offline to practice the flow without a key."
        )
    except anthropic.NotFoundError:
        raise SystemExit(
            "Model %r was not found for this account. Try --model claude-sonnet-5."
            % args.model
        )
    except anthropic.RateLimitError as exc:
        retry = exc.response.headers.get("retry-after", "60")
        raise SystemExit("Rate limited. Try again in about %s seconds." % retry)
    except anthropic.APIStatusError as exc:
        raise SystemExit("API error %s: %s" % (exc.status_code, exc.message))
    except anthropic.APIConnectionError:
        raise SystemExit("Could not reach the API. Check your network connection.")


def run_live(state, args):
    try:
        import anthropic
    except ImportError:
        raise SystemExit(
            "The anthropic package is not installed.\n"
            "  pip install -r requirements.txt\n"
            "Or run with --offline to practice the flow without it."
        )

    client = anthropic.Anthropic()
    system = build_system(state.prompt)
    history = [{"role": "user", "content": "I'm ready. Ask me your first question."}]

    print("Prompt: %s\n" % state.prompt.question)
    print("Five stages, six rubric dimensions. Type /help for commands.")

    turns = 0
    while turns < MAX_TURNS and not state.finished:
        turns += 1
        response = create_message(client, anthropic, args, system, history)

        if response.stop_reason == "refusal":
            print("\nThe model declined to continue this interview.")
            break

        history.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if block.type == "text" and block.text.strip():
                say(block.text.strip())

        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    payload = json.dumps(dispatch(state, block.name, block.input))
                    is_error = False
                except InterviewError as exc:
                    payload = json.dumps({"error": str(exc)})
                    is_error = True
                if args.trace:
                    _trace(block, payload, is_error)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": payload,
                        "is_error": is_error,
                    }
                )
            history.append({"role": "user", "content": results})
            continue

        if response.stop_reason == "max_tokens":
            print("\nThe response hit the token limit. Ending here.")
            break

        if state.finished:
            break

        answer = read_answer()
        if answer is None:
            history.append(
                {
                    "role": "user",
                    "content": "I'd like to stop here. Please end the interview and "
                    "give me the debrief for what we covered.",
                }
            )
            continue

        state.note_answer()
        history.append({"role": "user", "content": answer})

    if turns >= MAX_TURNS and not state.finished:
        print("\nHit the %d turn ceiling without a debrief being filed." % MAX_TURNS)
    return state


def _trace(block, payload, is_error):
    """Show the tool traffic. This is a learning repo; the loop is the point."""
    marker = "!" if is_error else "-"
    print("\n  %s %s(%s)" % (marker, block.name, json.dumps(block.input)))
    print("    %s" % payload)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Practice a product sense interview against Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        choices=sorted(PROMPTS),
        help="which practice prompt to use (default: %(default)s)",
    )
    parser.add_argument(
        "--list-prompts", action="store_true", help="print the prompts and exit"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run the scripted interviewer with no API key and no model",
    )
    parser.add_argument(
        "--model", default=MODEL, help="model id (default: %(default)s)"
    )
    parser.add_argument(
        "--effort",
        default="high",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="thinking effort (default: %(default)s)",
    )
    parser.add_argument(
        "--trace",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="show each tool call and its result (default: on)",
    )
    parser.add_argument(
        "--save", metavar="PATH", help="also write the debrief to a Markdown file"
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_prompts:
        for key in sorted(PROMPTS):
            print("%s\n  %s\n" % (key, PROMPTS[key].question))
        return 0

    state = InterviewState(prompt=PROMPTS[args.prompt])

    if args.offline:
        run_offline(state, ask=_offline_ask, say=say)
    else:
        run_live(state, args)

    report = render_debrief(state, when=date.today().isoformat())
    print("\n" + "-" * 68 + "\n")
    print(report)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as handle:
            handle.write(report + "\n")
        print("\nSaved to %s" % args.save)
    return 0


def _offline_ask(question):
    say(question)
    answer = read_answer()
    return answer or ""


if __name__ == "__main__":
    sys.exit(main())
