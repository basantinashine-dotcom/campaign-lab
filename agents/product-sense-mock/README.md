# Product Sense Mock

Practice product sense interviews against an interviewer that has to decide, every turn, whether you have said enough.

Claude plays the interviewer. You answer. It works through five stages, scores six rubric dimensions as it goes, and files a debrief at the end saying what you showed and what would have scored higher.

## Run it

Offline, with no API key and no model involved:

```sh
python product_sense_mock.py --offline
```

Live, against Claude:

```sh
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # PowerShell: $env:ANTHROPIC_API_KEY = "..."
python product_sense_mock.py
```

Useful flags: `--prompt <key>` picks the question, `--list-prompts` shows them all, `--save debrief.md` writes the debrief to a file, `--no-trace` hides the tool traffic, `--effort low|medium|high|xhigh|max` trades thinking depth against cost.

Answers can run over several lines. A blank line sends one. `/quit` ends early and still gives you a debrief for what you covered.

## Why this is an agent and not a prompt

The interviewer faces a real decision on every turn: *has this dimension been covered well enough to move on, or does it need another probe?* That decision is a tool call against live state, and the result changes what it does next.

| Tool | What it does | What it returns |
| --- | --- | --- |
| `record_signal` | Scores one rubric dimension 1-4 with evidence and the gap to a higher score | Which dimensions in this stage are still uncovered, and how many probes remain |
| `advance_stage` | Moves to the next stage | The next stage's focus, brief, and probe budget |
| `end_interview` | Files the debrief | The final scorecard |

Each stage carries a **probe budget** — the number of your answers the interviewer may spend there. When it runs out, the tool result says so and the interviewer has to move on. That limit is enforced by the harness in `interview.py`, not requested of the model in the system prompt, which is the difference between a constraint and a suggestion. It is also what stops an interview running forever.

The loop in `product_sense_mock.py` is written by hand rather than handed to the SDK's tool runner, for one specific reason: an interview has to stop and wait for a human between turns, and the tool runner drives a conversation to completion without yielding.

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
| `campaign-lab-next` | Campaign Lab teaches an online store owner to run their first Instagram ad campaign. What would you build next, and who is it for? |
| `grocery-reorder` | Design a feature that helps first-time grocery delivery customers place a second order. |
| `small-creators` | How would you improve Instagram for creators with fewer than 1,000 followers? |
| `notes-decline` | Weekly active users of a note-taking app fell 8% month over month. Work out why, then decide what to do about it. |
| `commute-podcasts` | Design something for people who listen to podcasts during a commute. |

`campaign-lab-next` points at [Campaign Lab](../../apps/campaign-lab/), the other project in this collection. Its stated success criterion is that a learner can name a decision they changed and explain its effect on contribution, which is a reasonable thing to be interviewed about.

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

**Prompt:** Campaign Lab teaches an online store owner to run their first Instagram ad campaign...

**Score: 17 / 24** across 6 assessed dimensions.

| Dimension | Score | What you showed | What would raise it |
| --- | --- | --- | --- |
| problem framing | 4 strong | My goal is to get a store owner to make a second ad decision... | -- |
| pain points | 2 partial | First-time advertisers who just spent 50 dollars... | ...looked for language that engages pain points directly |
| metrics | 1 missing | (no answer given) | Any answer at all would score higher than silence. |
```

## Tests

```sh
python -m unittest discover -s tests -t .
```

35 tests, no API key and no network needed. `interview.py` and `offline.py` never import the Anthropic SDK, so the rubric, the probe budget, the stage transitions, the scorecard arithmetic, and a full scripted interview are all testable on their own.

## Required services

The live mode calls the Anthropic Messages API and needs `ANTHROPIC_API_KEY` in your environment. Nothing is written anywhere except the file you name with `--save`. The agent takes no action outside the conversation: it has no network access of its own, no filesystem tools, and nothing to authorize. Keep your key out of Git; this repository's `.gitignore` already covers `.env*`.

Model defaults to `claude-opus-5` with adaptive thinking. A full interview is roughly 20-30 model turns.

## Limitations

**Offline scoring is crude and you should not trust it.** It checks whether an answer *looks* like it engages a dimension — length, a keyword, a number or a stated reason — not whether the thinking behind it is any good. It cannot tell a sharp segment choice from a confident wrong one, and it will reward padding. It exists so the flow runs and can be tested without a key. For anything resembling feedback, run the live agent.

**One interviewer, one conversation.** Scores are not calibrated against anything. Run the same answers twice and you may get different numbers. This is practice equipment, not assessment, and certainly not a hiring signal.

**The rubric is a teaching simplification.** Real product sense interviews vary by company and by interviewer, many are far less structured than five fixed stages, and some of the best answers ignore the expected arc entirely. The probe budget in particular is an artifact of keeping a practice session finite, not a thing real interviewers do.

**No follow-through.** The interview ends at the debrief. It does not remember previous sessions, track whether you improved, or adapt its questions to you.

**The live path has not been executed end to end.** The tool schemas, state machine, offline interviewer, and CLI are covered by tests and were run locally; the code that calls the Messages API was written against the current API but has not been run against it. If you hit a problem there, that is the first place to look.

Return to the [agents folder](../README.md) or the [project collection](../../README.md).
