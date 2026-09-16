# Product Sense Mock

Practice product sense interviews against an interviewer that has to decide, every turn, whether you have said enough.

Claude plays the interviewer. You answer. It works through five stages, scores six rubric dimensions as it goes, and files a debrief at the end saying what you showed and what would have scored higher.

## Run it in your browser

```sh
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # PowerShell: $env:ANTHROPIC_API_KEY = "..."
python web.py
```

A tab opens at http://127.0.0.1:8765. Pick a question, choose Claude or the offline script, and answer in the chat. `Ctrl+Enter` sends. The stage rail shows where you are; scores stay hidden until the debrief unless you turn on **Show interviewer's notes**. The debrief can be downloaded as Markdown.

Setting the key is only needed for Claude. The offline script needs neither the key nor `pip install`. Stop the server with `Ctrl+C`. Interviews live in the server's memory, so stopping it discards any that are unfinished.

Flags: `--port`, `--effort low|medium|high|xhigh|max`, `--model`, `--no-open`.

## Run it in the terminal

```sh
python product_sense_mock.py --offline     # scripted, no key
python product_sense_mock.py               # Claude, needs the key
```

Useful flags: `--prompt <key>` picks the question, `--list-prompts` shows them all, `--save debrief.md` writes the debrief to a file, `--no-trace` hides the tool traffic, `--effort` trades thinking depth against cost.

Answers can run over several lines. A blank line sends one. `/quit` ends early and still gives you a debrief for what you covered.

## Why this is an agent and not a prompt

The interviewer faces a real decision on every turn: *has this dimension been covered well enough to move on, or does it need another probe?* That decision is a tool call against live state, and the result changes what it does next.

| Tool | What it does | What it returns |
| --- | --- | --- |
| `record_signal` | Scores one rubric dimension 1-4 with evidence and the gap to a higher score | Which dimensions in this stage are still uncovered, and how many probes remain |
| `advance_stage` | Moves to the next stage | The next stage's focus, brief, and probe budget |
| `end_interview` | Files the debrief | The final scorecard |

Each stage carries a **probe budget** — the number of your answers the interviewer may spend there. When it runs out, the tool result says so and the interviewer has to move on. That limit is enforced by the harness in `interview.py`, not requested of the model in the system prompt, which is the difference between a constraint and a suggestion. It is also what stops an interview running forever.

The loop in `session.py` is written by hand rather than handed to the SDK's tool runner, for one specific reason: an interview has to stop and wait for a human between turns, and the tool runner drives a conversation to completion without yielding.

## How the code is organized

| File | Job | Knows about |
| --- | --- | --- |
| `interview.py` | Rubric, stages, probe budget, tool schemas, scorecard, Markdown debrief | Nothing else |
| `session.py` | The live agent loop: call Claude, run its tool calls, stop when it needs you | `interview.py`, and a client passed in |
| `offline.py` | The scripted interviewer, with the same shape and events as a live session | `interview.py` |
| `product_sense_mock.py` | Terminal front end | Sessions |
| `web.py` + `web/` | Browser front end: a standard-library server and a plain HTML/JS/CSS page | Sessions |

Neither front end talks to Claude directly. Both drive a session and render the events it returns, which is why the terminal and the browser cannot drift apart, and why the loop can be tested with a fake client.

## The rubric

Six dimensions, each scored 1 missing, 2 partial, 3 solid, 4 strong.

| Dimension | What it looks for |
| --- | --- |
| `problem_framing` | Clarifies the goal, scope, and constraints before proposing anything |
| `user_segmentation` | Names one specific segment and says why that one |
| `pain_points` | Grounds the segment in concrete, believable needs |
| `solution` | Proposes specific ideas and prioritizes among them |
| `tradeoffs` | Names what the idea costs, risks, or gives up |
| `metrics` | Defines success measures, including at least one counter-metric |

Five stages map onto them: framing, users, solution, tradeoffs, metrics.

A dimension the interviewer never got to is reported as **not assessed** rather than scored zero, and the total is out of the assessed dimensions only. Counting an unasked question as a failure would be a worse lie than admitting it was never asked.

## The prompts

| Key | Question |
| --- | --- |
| `grocery-reorder` (default) | Design a feature that helps first-time grocery delivery customers place a second order. |
| `small-creators` | How would you improve Instagram for creators with fewer than 1,000 followers? |
| `notes-decline` | Weekly active users of a note-taking app fell 8% month over month. Work out why, then decide what to do about it. |
| `commute-podcasts` | Design something for people who listen to podcasts during a commute. |

Each prompt carries private interviewer notes on what strong answers tend to cover. Those go in the system prompt and are never read out.

## What the tool traffic looks like

With `--trace` on (the default), each call and its result is printed as it happens. The result is what drives the next question:

```
  - record_signal({"dimension": "user_segmentation", "score": 3, "evidence": "...", "gap": "..."})
    {"recorded": {"dimension": "user_segmentation", "score": 3, "label": "solid"},
     "stage": "users", "stage_uncovered": ["pain_points"], "probes_remaining": 2,
     "guidance": "Still uncovered in this stage: pain_points. You have 2 probe(s) left, so ask another question."}
```

## Example debrief

Abridged from a real `--offline` run:

```markdown
# Product sense debrief

**Prompt:** Design a feature that helps first-time grocery delivery customers place a second order.

**Score: 16 / 24** across 6 assessed dimensions.

| Dimension | Score | What you showed | What would raise it |
| --- | --- | --- | --- |
| problem framing | 4 strong | My goal is to get first-time customers to a second order within 14 days, so I will scope this to the week after their first delivery... | -- |
| pain points | 2 partial | They have to rebuild the whole basket from scratch, which takes 20 minutes, so it is easier to go to the shop. | This heuristic looked for more than a sentence of detail and language that engages pain points directly and did not find it. |
| tradeoffs | 2 partial | It might cost us basket growth. | This heuristic looked for more than a sentence of detail and a number, an example, or a stated reason and did not find it. |
```

## Tests

```sh
python -m unittest discover -s tests -t .
```

75 tests, no API key and no network needed. From the repository root, `npm run test:product-sense` runs the same thing.

- `test_interview.py` covers the rubric, the probe budget, stage transitions, scorecard arithmetic, and the offline heuristic.
- `test_session.py` drives the live loop with a fake client: tool results matched back by id, rejected tool input returned as an error, several tool calls in one turn, quitting, refusals, the turn ceiling, and recovering from an API error without resending your answer.
- `test_web.py` runs the server on a random port and completes interviews over real HTTP, including the Host and JSON checks below.

## Required services

Live interviews call the Anthropic Messages API and need `ANTHROPIC_API_KEY` in the terminal that starts the program. Nothing is written anywhere except the file you name with `--save` or the debrief you download. The agent takes no action outside the conversation: it has no network access of its own, no filesystem tools, and nothing to authorize. Keep your key out of Git; this repository's `.gitignore` already covers `.env*`.

The web server holds the key and the interview state; the page only ever receives questions, events, and the debrief. Because the server can spend your credits, it listens on `127.0.0.1` only, so other machines on your network cannot reach it, and it rejects requests with a foreign Host header or a non-JSON body, so another website open in your browser cannot drive it.

Model defaults to `claude-opus-5` with adaptive thinking. A full interview is roughly 20-30 model turns.

## Limitations

**Offline scoring is crude and you should not trust it.** It checks whether an answer *looks* like it engages a dimension — length, a keyword, a number or a stated reason — not whether the thinking behind it is any good. It cannot tell a sharp segment choice from a confident wrong one, and it will reward padding. It exists so the flow runs and can be tested without a key. For anything resembling feedback, run the live agent.

**One interviewer, one conversation.** Scores are not calibrated against anything. Run the same answers twice and you may get different numbers. This is practice equipment, not assessment, and certainly not a hiring signal.

**The rubric is a teaching simplification.** Real product sense interviews vary by company and by interviewer, many are far less structured than five fixed stages, and some of the best answers ignore the expected arc entirely. The probe budget in particular is an artifact of keeping a practice session finite, not a thing real interviewers do.

**No follow-through.** The interview ends at the debrief. It does not remember previous sessions, track whether you improved, or adapt its questions to you.

**Live interviews are only partly proven.** The API accepts the tool definitions and settings, and a real `end_interview` call has completed. A full live interview, with Claude scoring answers and moving between stages, has not yet been run, and the web page has only been exercised in offline mode. The loop around those calls is tested with a fake client, but a fake cannot show whether Claude follows the probe budget well.

**One machine, one person.** The web server is for running on your own computer. It keeps interviews in memory, has no accounts, and is not built to be put on the internet: anyone who could reach it could spend your credits.

Return to the [agents folder](../README.md) or the [project collection](../../README.md).
