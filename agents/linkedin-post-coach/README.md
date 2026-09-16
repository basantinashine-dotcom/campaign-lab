# LinkedIn Post Coach

Get practical feedback on a LinkedIn draft while keeping your meaning and voice. The coach identifies what works, explains up to three useful changes, and flags claims that need evidence. A rewrite is optional.

This project is a reusable ChatGPT instruction pack: an agent starter, not an autonomous agent or hosted web app. ChatGPT supplies the model. No separate API key or LinkedIn connection is needed.

## Start in two minutes

1. Open [AGENT.md](AGENT.md) and copy its full contents into a new ChatGPT conversation.
2. Send your draft in the next message. You can use the template below.
3. Read the feedback and supply any missing facts. Ask for a revision only when you want one.

```text
Intended reader: Product managers learning to build small apps
Purpose: Share something I learned from building
Tone: Conversational and practical
Preserve: My original story and the project link
Mode: feedback

Draft:
[Paste your post here]
```

Only the draft is required. Choose `feedback-and-rewrite` for feedback plus a suggested revision. You can also provide a past post as a voice sample. Avoid including confidential details you do not want to send to ChatGPT.

## What the coach returns

- An overall editorial assessment and up to two strengths, quoting your draft.
- Up to three improvements, each with an excerpt, explanation, and specific suggested change.
- Claims to verify, with the evidence needed.
- A revision and change log only when requested.
- One next step.

See the [fictional sample input](examples/product-learning.json) and [illustrative review](examples/worked-review.md). The sample review is a written reference, not a recorded model test. The coach should ask for real details where useful; it must not invent achievements, metrics, or personal experiences.

## What you learn by building this

An AI feature has more than a prompt. This project separates four pieces:

| Piece | File or component | Purpose |
| --- | --- | --- |
| Instructions | [AGENT.md](AGENT.md) | Define the job, constraints, and output format. |
| Input | A draft and optional context | Tell the reviewer what to assess and who it is for. |
| Model | Your ChatGPT conversation | Interpret the draft and generate feedback. |
| Evaluation | [EVALUATIONS.md](EVALUATIONS.md) | Check whether feedback follows the rules and helps the writer. |

The [rubric](RUBRIC.md) makes the product's idea of good feedback explicit. The product loop is: submit a draft, read the reasons, revise, and compare. A useful success measure is whether writers can make a concrete improvement without having to correct invented information. Engagement or virality is not promised.

## Optional: build a complete prompt locally

This step is for learning the code. You do not need it to use the coach.

With Node.js 18 or later, from the repository root:

```sh
node agents/linkedin-post-coach/build-prompt.mjs agents/linkedin-post-coach/examples/product-learning.json
```

The command prints the instructions plus example input. Paste that output into ChatGPT. The CLI **does not generate a review**, invoke a model, or send any data over the network.

For your own draft, copy [input-template.json](input-template.json) outside the repository, fill it in, and pass its file path to the same command. Keep JSON quotes and line breaks escaped correctly. Directly pasting into ChatGPT is easier for most writers. If you save inputs or generated prompts in the repository, they can accidentally be committed to this public project.

The builder accepts `draft`, `audience`, `goal`, `tone`, `preserve`, `voiceSample`, and `mode`. It rejects unknown fields, blank drafts, invalid modes, and oversized inputs. Limits are implementation choices, not LinkedIn or ChatGPT limits.

```sh
npm --prefix agents/linkedin-post-coach test
npm --prefix agents/linkedin-post-coach run check
```

Automated tests cover input validation, prompt serialization, and CLI behavior. They do not prove that a model follows instructions. Use the manual evaluation cases before changing the rubric or model.

## Limitations

Feedback is subjective and can vary between model runs. Exact quotes and proposed revisions still need a human check. A writing review is not an independent fact-check. The coach cannot predict reach, identify AI authorship, or guarantee resistance to malicious instructions inside a draft.

This project does not scrape LinkedIn, log in, publish, schedule, or message anyone. Future model integrations would need their own setup, privacy choices, and evaluations.

Return to [Learn by Building](../../README.md).
