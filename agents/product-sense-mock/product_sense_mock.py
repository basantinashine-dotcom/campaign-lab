#!/usr/bin/env python3
"""Product sense mock interview agent, in the terminal.

Claude plays the interviewer; you answer. It works through five stages, scores
six rubric dimensions as it goes, and files a debrief at the end.

This file only handles the terminal: reading answers and printing. The agent
loop lives in session.py and the offline interviewer in offline.py, shared with
the web page in web.py.

    python product_sense_mock.py                    # live, needs ANTHROPIC_API_KEY
    python product_sense_mock.py --offline          # scripted, no key needed
    python product_sense_mock.py --list-prompts
    python web.py                                   # the same interview in a browser
"""

import argparse
import json
import sys
from datetime import date

from interview import DEFAULT_PROMPT, PROMPTS, render_debrief
from offline import OfflineSession, new_state
from session import MODEL, LiveSession, explain_api_error

HELP = """
Commands
  /help     show this
  /quit     end the interview early and get the debrief for what you covered

Answers can run over several lines. Finish one with a blank line.
"""


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


def show(events, trace):
    for event in events:
        if event["kind"] == "interviewer":
            say(event["text"])
        elif event["kind"] == "notice":
            print("\n[%s]" % event["text"])
        elif event["kind"] == "tool" and trace:
            marker = "!" if event["is_error"] else "-"
            print("\n  %s %s(%s)" % (marker, event["name"], json.dumps(event["input"])))
            print("    %s" % json.dumps(event["result"]))


def drive(session, trace, anthropic=None, model=None):
    """Run a session to completion from the terminal."""

    def step(action, *args):
        try:
            return action(*args)
        except Exception as exc:
            explained = anthropic and explain_api_error(anthropic, exc, model)
            if not explained:
                raise
            raise SystemExit(explained[0])

    show(step(session.start), trace)
    while not session.done:
        if not session.awaiting_answer:
            break
        answer = read_answer()
        if answer is None:
            show(step(session.quit), trace)
        else:
            show(step(session.answer, answer), trace)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Practice a product sense interview against Claude."
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
    parser.add_argument("--model", default=MODEL, help="model id (default: %(default)s)")
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

    state = new_state(args.prompt)

    if args.offline:
        print("Prompt: %s" % state.prompt.question)
        drive(OfflineSession(state), args.trace)
    else:
        try:
            import anthropic
        except ImportError:
            raise SystemExit(
                "The anthropic package is not installed.\n"
                "  pip install -r requirements.txt\n"
                "Or run with --offline to practice the flow without it."
            )
        print("Prompt: %s\n" % state.prompt.question)
        print("Five stages, six rubric dimensions. Type /help for commands.")
        session = LiveSession(
            state, anthropic.Anthropic(), model=args.model, effort=args.effort
        )
        drive(session, args.trace, anthropic=anthropic, model=args.model)

    report = render_debrief(state, when=date.today().isoformat())
    print("\n" + "-" * 68 + "\n")
    print(report)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as handle:
            handle.write(report + "\n")
        print("\nSaved to %s" % args.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
