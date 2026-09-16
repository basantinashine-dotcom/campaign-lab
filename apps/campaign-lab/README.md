# Campaign Lab

Understand how to run effective ad campaigns by practicing before you spend.

A guided, browser-based exercise for a small online store owner learning paid advertising. Create a fictional Ember & Earth candle campaign, simulate seven days, interpret its results, and test one change against a preserved baseline.

## Run locally

From the collection root, first run `cd apps/campaign-lab`. Serve this app's `dist` directory with a static HTTP server, for example `python -m http.server 4317 --directory dist`, then open http://localhost:4317. ES modules require an HTTP server; do not open index.html directly from the filesystem.

Run `npm test` (Node 18+) for the simulation tests and `npm run check` for JavaScript syntax checks. There are no npm dependencies or build step. Google Fonts is optional; system fallbacks keep the interface usable offline once files are served locally.

## How this app is built

- `dist/index.html` is the document shell and dialog markup.
- `dist/style.css` controls appearance and responsive layouts.
- `dist/app.js` handles the five-screen journey, visit-only state, validation, results, experiments, and learning-summary download.
- `dist/engine.mjs` is a pure simulation module. Inputs produce results without touching the interface.
- `tests/engine.test.mjs` verifies financial reconciliation, deterministic replay, one-variable changes, and input validation.
- `dist/candle.png` is an original AI-generated image for the fictional shop.

The app runs in the browser. It has no advertising connection, paid API, database, account system, or server business logic. Reloading clears the exercise. The optional browser WebMCP interface exposes read, stage, and simulate actions with the same validation as the UI.

## Model and limits

All coefficients are invented teaching assumptions, not empirical benchmarks or forecasts. Impressions follow spend/CPM, clicks and orders are Bernoulli draws from seeded random streams. Costs vary by day within a fixed fictional market. Replaying the same choices yields the same result. The same per-impression click and purchase draws are used for comparisons. The full lifetime budget is spent evenly across seven days.

Audience, placement, message, discount, and budget saturation adjust explicit coefficients exposed in the app's assumptions dialog. The model does not judge free-form text, simulate Meta's auction algorithm, reproduce Advantage+, infer real audience size, or establish statistical significance. It omits attribution, tracking gaps, repeated exposure, inventory, organic purchases, returns, overhead, and repeat buyers. Contribution after fulfillment and ads is not net profit. Reels uses a still storyboard preview, not video generation.

This first lesson intentionally uses one sales objective, one ad set, prepared ad concepts, and one-variable comparisons. Future scope should follow user research, especially whether beginners can transfer what they learn to real decisions.

## Product learning

Customer hypothesis: an online store owner unsure how to make and evaluate their first Instagram advertising decisions.

Success criterion: after the exercise, the learner can name one decision they changed, explain why, and interpret its effect on contribution rather than just clicks or revenue.

The existing Sites deployment is configured in this app's `.openai/hosting.json`. Its paths are relative to this folder. See the collection's [deployment instructions](../../README.md#deployment) for synchronizing the standalone Sites checkout before publishing. Static files can also be hosted by any provider that supports ES modules. Meta and Instagram do not sponsor or endorse this tool.

Return to the [project collection](../../README.md).

## Explainable experiments

Every change has a causal explanation derived from the engine: the changed assumption, impression cost, click probability, purchase probability, expected orders versus the realized seeded outcome, and a reconciled decomposition of contribution change into order volume, price, and advertising spend. Placement guidance compares all three surfaces using the same campaign settings. Editing an experiment marks its previous comparison as pending until rerun.
