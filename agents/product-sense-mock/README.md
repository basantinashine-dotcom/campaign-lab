# Product Sense Mock

Practice product sense interviews against an interviewer that has to decide, every turn, whether you have said enough.

Claude plays the interviewer. You start by asking the clarifying questions, then answer its questions through six stages: Clarify, Strategy, Users, Pain points, Solutions, and MVP. It scores each stage as it goes, judged against the bar for the level you choose, and files a debrief at the end saying what you showed and what would have scored higher.

## Run it in your browser

```sh
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # PowerShell: $env:ANTHROPIC_API_KEY = "..."
python web.py
```

A tab opens at http://127.0.0.1:8765. Pick a question, your level, and Claude or the offline script, then answer in the chat. `Ctrl+Enter` sends. The stage rail shows where you are; scores stay hidden until the debrief unless you turn on **Show interviewer's notes**. The debrief can be downloaded as Markdown.

Setting the key is only needed for Claude. The offline script needs neither the key nor `pip install`. Stop the server with `Ctrl+C`. Interviews live in the server's memory, so stopping it discards any that are unfinished.

Flags: `--port`, `--effort low|medium|high|xhigh|max`, `--model`, `--no-open`.

## Run it in the terminal

```sh
python product_sense_mock.py --offline     # scripted, no key
python product_sense_mock.py               # Claude, needs the key
```

Useful flags: `--prompt <key>` picks the question, `--level pm|senior` sets the bar, `--list-prompts` shows the questions, `--save debrief.md` writes the debrief to a file, `--no-trace` hides the tool traffic, `--effort` trades thinking depth against cost.

Answers can run over several lines. A blank line sends one. `/quit` ends early and still gives you a debrief for what you covered.

## The framework

One stage per step, one scored dimension per stage, each scored 1 missing, 2 partial, 3 solid, 4 strong, out of 24 in total.

| Stage | What gets scored |
| --- | --- |
| **Clarify** | Asks only questions whose answers would change what gets built, and states product context as assumptions instead of asking the interviewer to decide |
| **Strategy** | Ties the opportunity to the company's mission and strategy, and explains why this company would build it now |
| **Users** | Segments users by what the product enables, picks one group quickly, and gives a logical rationale with rough sizing |
| **Pain points** | Finds genuinely distinct pain points, prioritizes one, and names the root problem behind it |
| **Solutions** | Generates meaningfully different ideas anchored to the root problem, including a moonshot |
| **MVP** | Defines the smallest version that delivers real value, names what waits and why, and says how success would be measured, including a counter-metric |

**Clarify runs the other way round.** You ask; the interviewer answers from a hidden company brief written for each question, covering the company, its mission, competitors, and constraints. It answers questions about the question directly. If you ask it to decide product context for you, such as company size or timeline, it asks what you would assume instead. If you ask about something the brief doesn't cover, state an assumption, as you would in a real interview.

**Metrics are scored in MVP**, not as a stage of their own. A north star can still come up naturally in Strategy.

A stage the interviewer never got to is reported as **not assessed** rather than scored zero, and the total is out of the assessed stages only. Counting an unasked question as a failure would be a worse lie than admitting it was never asked.

## Levels

| Level | The bar |
| --- | --- |
| **PM** (default) | In Strategy, a clear mission and a sensible north star, covered briefly, is a solid answer. Clear structure and decisiveness count for more than depth of market knowledge. |
| **Senior PM+** | Strategy also needs why this company specifically, the competitive gap, and the longer arc; at this level it often decides the interview. Users needs sizing with stated reasoning, and MVP needs specific, justified cuts. |

The level changes the bar, not the stages or the questions.

## Reference context

Markdown files in [`context/`](context/) are added to the interviewer's instructions at the start of every live interview, as guidance on what strong answers look like. The interviewer uses them to judge and to decide what to probe, and is told never to quote them or coach from them.

Material that isn't yours to publish, such as course notes, blog excerpts, or an employer's interview guide, goes in `context/private/`. This public repository ignores that folder; keep it as a separate private repository. The setup page lists the files it found, and the web server rereads the folder for each interview, so edits apply without a restart. See [context/README.md](context/README.md).

## Progress

After each finished interview with Claude, the stage scores are saved as a small JSON file in `context/private/progress/`, and the private context folder is uploaded to GitHub in the background. The debrief says whether the upload worked. Offline runs are never saved, and neither is an interview that ended before anything was scored.

- **Progress** in the top bar shows your average per stage, your recent scores oldest to newest, your weakest stage, and every past interview.
- **The interviewer sees a short summary** of your history at the start of each interview. It is allowed to press a little harder where you have been weak and to aim its suggested next question there, and it is told that history must never change a score.
- **Private context** on the start page shows whether you have unsaved changes, such as a reference file you edited, and has a **Save to GitHub** button for them.

Uploading runs `git add`, `git commit`, and `git push` inside `context/private`, using the GitHub login already on your computer. It only does so if that folder is its own Git repository. Otherwise, because the folder sits inside this public repository, Git would find the public one instead. Without a private repository, results are still saved on your computer, and the page says so.

## Why this is an agent and not a prompt

The interviewer faces a real decision on every turn: *has this stage been covered well enough to move on, or does it need another probe?* That decision is a tool call against live state, and the result changes what it does next.

| Tool | What it does | What it returns |
| --- | --- | --- |
| `record_signal` | Scores one stage 1-4 with evidence and the gap to a higher score | Whether this stage is still uncovered, and how many probes remain |
| `advance_stage` | Moves to the next stage | The next stage's focus, brief, and probe budget |
| `end_interview` | Files the debrief | The final scorecard |

Each stage carries a **probe budget**: the number of your messages the interviewer may spend there, 3 in Clarify and 2 elsewhere. When it runs out, the tool result says so and the interviewer has to move on. That limit is enforced by the harness in `interview.py`, not requested of the model in the system prompt, which is the difference between a constraint and a suggestion. It is also what stops an interview running forever.

The loop in `session.py` is written by hand rather than handed to the SDK's tool runner, for one specific reason: an interview has to stop and wait for a human between turns, and the tool runner drives a conversation to completion without yielding.

## How the code is organized

| File | Job | Knows about |
| --- | --- | --- |
| `interview.py` | Stages, rubric, levels, prompts and company briefs, probe budget, tool schemas, scorecard, Markdown debrief | Nothing else |
| `session.py` | The live agent loop: build the instructions, load reference context, call Claude, run its tool calls, stop when it needs you | `interview.py`, and a client passed in |
| `offline.py` | The scripted interviewer, with the same shape and events as a live session | `interview.py` |
| `progress.py` | Saving finished interviews, reading history, and summarizing it for you and the interviewer | `interview.py` |
| `sync.py` | Backing up `context/private` to its own GitHub repository, refusing if it isn't one | Git |
| `product_sense_mock.py` | Terminal front end | Sessions |
| `web.py` + `web/` | Browser front end: a standard-library server and a plain HTML/JS/CSS page | Sessions |

Neither front end talks to Claude directly. Both drive a session and render the events it returns, which is why the terminal and the browser cannot drift apart, and why the loop can be tested with a fake client.

## The prompts

| Key | Question |
| --- | --- |
| `grocery-reorder` (default) | Design a feature that helps first-time grocery delivery customers place a second order. |
| `small-creators` | How would you improve Instagram for creators with fewer than 1,000 followers? |
| `notes-decline` | Weekly active users of a note-taking app fell 8% month over month. Work out why, then decide what to do about it. |
| `commute-podcasts` | Design something for people who listen to podcasts during a commute. |

Each prompt carries two things the candidate never sees: a company brief for answering clarifying questions, and notes on what strong answers tend to cover. Three of the companies are fictional. The Instagram brief uses Instagram's public mission and competitors, but its figures are labelled as practice assumptions, not published data.

## What the tool traffic looks like

With `--trace` on (the default), each call and its result is printed as it happens. The result is what drives the next question:

```
  - record_signal({"dimension": "strategy", "score": 2, "evidence": "...", "gap": "..."})
    {"recorded": {"dimension": "strategy", "score": 2, "label": "partial"},
     "stage": "strategy", "stage_uncovered": [], "probes_remaining": 1,
     "guidance": "Every dimension in this stage is recorded. Call advance_stage."}
```

## Example debrief

Abridged from a real `--offline` run:

```markdown
# Product sense debrief

**Prompt:** Design a feature that helps first-time grocery delivery customers place a second order.

**Level:** PM

**Score: 23 / 24** across 6 assessed stages.

| Stage | Score | What you showed | What would raise it |
| --- | --- | --- | --- |
| Clarify | 3 solid | I am assuming the goal is repeat orders within 30 days, because first-order discounts are being cut this year. | This heuristic looked for more than a sentence of detail and did not find it. |
| Strategy | 4 strong | It fits the mission of giving people their evenings back, because a second order is what turns a discounted trial into a habit, and why n... | -- |
| MVP | 4 strong | The MVP is one-tap reorder for customers with one past order; standing orders wait for slot reservation. Success is the 30 day repeat rat... | -- |
```

## Tests

```sh
python -m unittest discover -s tests -t .
```

120 tests, no API key and no network needed. From the repository root, `npm run test:product-sense` runs the same thing.

- `test_interview.py` covers the framework's stages and dimensions, levels, company briefs, the probe budget, stage transitions, scorecard arithmetic, and the offline heuristic.
- `test_session.py` drives the live loop with a fake client: tool results matched back by id, rejected tool input returned as an error, several tool calls in one turn, quitting, refusals, the turn ceiling, and recovering from an API error without resending your answer. It also checks what goes into the instructions (brief, level bar, reference files, cache marker) and how reference files are loaded.
- `test_web.py` runs the server on a random port and completes interviews over real HTTP, including levels, reference context reaching a live session, results being saved and uploaded exactly once, offline runs not being saved, history reaching the next interview, and the Host and JSON checks below.
- `test_progress.py` covers what gets saved, reading history back, averages and the weakest stage, and the instruction that history never changes a score.
- `test_sync.py` runs real `git` against throwaway repositories, with a local bare repository standing in for GitHub: saving and pushing, nothing to save, pushing earlier unpushed commits, a failed push, and refusing to commit when the folder is only a subfolder of another repository. It is skipped if Git isn't installed.

## Required services

Live interviews call the Anthropic Messages API and need `ANTHROPIC_API_KEY` in the terminal that starts the program. Uploading progress needs Git and a GitHub login on your computer, plus `context/private` set up as a private repository. The program writes only the files you name with `--save`, the debriefs you download, and the progress files in `context/private/progress/`, and it pushes only to the private repository in `context/private`. The interviewer itself takes no action outside the conversation: it has no network access of its own, no filesystem tools, and nothing to authorize. Keep your key out of Git; this repository's `.gitignore` already covers `.env*`.

The web server holds the key, the interview state, and the reference context; the page only ever receives questions, events, the debrief, and the names of the reference files. Because the server can spend your credits, it listens on `127.0.0.1` only, so other machines on your network cannot reach it, and it rejects requests with a foreign Host header or a non-JSON body, so another website open in your browser cannot drive it.

Model defaults to `claude-opus-5` with adaptive thinking. A full interview is roughly 20-30 model turns. The instructions, including reference files, are resent every turn but marked for prompt caching, so after the first turn they are read from the cache at a fraction of the price.

## Limitations

**Offline scoring is crude and you should not trust it.** It checks whether an answer *looks* like it engages a stage (length, a keyword, a number or a stated reason), not whether the thinking behind it is any good. It cannot tell a sharp segment choice from a confident wrong one, and it will reward padding. In Clarify it cannot answer your questions at all; it hands you the company brief instead. It exists so the flow runs and can be tested without a key.

**One interviewer, one conversation.** Scores are not calibrated against anything. Run the same answers twice and you may get different numbers. This is practice equipment, not assessment, and certainly not a hiring signal.

**Levels are two broad bars.** Real expectations vary by company, team, and interviewer far more than PM versus Senior PM+.

**The framework is a teaching structure.** Real interviews rarely hand you the stages one at a time. Here the interviewer leads you through each stage, which is good for learning the structure but easier than having to drive it yourself.

**Progress is a trend, not a measurement.** Averages across different questions, levels, and interviewer moods are rough. A rise from 2.3 to 2.7 over three interviews is encouraging, not proof. Upload failures are reported but not retried automatically; the Save to GitHub button retries.

**Live interviews are only partly proven.** The API accepts the tool definitions and settings, and a real `end_interview` call has completed. A full live interview, with Claude answering clarifying questions, scoring stages, and moving through them, has not yet been run, and the web page has only been exercised in offline mode. The loop is tested with a fake client, but a fake cannot show whether Claude follows the probe budget or uses the brief and reference files well.

**One machine, one person.** The web server is for running on your own computer. It keeps interviews in memory, has no accounts, and is not built to be put on the internet: anyone who could reach it could spend your credits.

Return to the [agents folder](../README.md) or the [project collection](../../README.md).
