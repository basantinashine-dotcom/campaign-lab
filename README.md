# Learn by Building

Learn data science, ad tech, and product thinking by building.

A growing collection of hands-on projects to explore concepts, experiment with ideas, and learn through code.

- **Data science:** Explore data, uncover patterns, and interpret results.
- **Ad tech:** Understand advertising systems, campaign performance, and measurement.
- **Product management:** Turn problems into products, test hypotheses, and evaluate trade-offs.

## Explore the projects

| Project | What you can learn | Open it |
| --- | --- | --- |
| **Campaign Lab** | Practice Instagram campaign decisions, compare one-variable experiments, and trace why simulated results changed. | [Source and instructions](apps/campaign-lab/) · [Web app](https://campaign-lab-instagram.basanti-nashine.chatgpt.site) |
| **LinkedIn Post Coach** | Design an AI review rubric, preserve an author's voice, and evaluate whether feedback is useful and grounded in the draft. | [Instructions and examples](agents/linkedin-post-coach/) |

Campaign Lab currently runs in the browser using a fictional simulation. A backend, saved event dataset, and database are future learning milestones, not implemented features.

## Repository structure

```text
learn-by-building/
├── apps/
│   └── campaign-lab/
│       ├── .openai/hosting.json
│       ├── dist/
│       ├── tests/
│       ├── package.json
│       └── README.md
├── agents/
│   ├── linkedin-post-coach/
│   │   ├── AGENT.md
│   │   ├── examples/
│   │   ├── tests/
│   │   └── README.md
│   └── README.md
├── package.json
└── README.md
```

Each app or agent belongs in its own folder and documents its setup, assumptions, and limitations. Projects may use different languages and deploy independently.

## Try LinkedIn Post Coach

Copy [the reviewer instructions](agents/linkedin-post-coach/AGENT.md) into a new ChatGPT conversation, then send your post draft. Add the intended reader and purpose if you know them. It returns strengths, up to three prioritized improvements, and claims to check. Ask for `feedback-and-rewrite` when you also want a revision.

This is a reusable instruction-based reviewer, not a hosted app or autonomous publishing agent. It needs access to ChatGPT, but no separate API key or LinkedIn connection. See the [setup guide](agents/linkedin-post-coach/) for an optional offline prompt builder and a worked example.

## Try Campaign Lab locally

From the repository root, with Python installed:

```sh
python -m http.server 4317 --directory apps/campaign-lab/dist
```

Open http://localhost:4317. Use a web server rather than opening the HTML file directly, because the app uses JavaScript modules.

With Node.js 18 or later installed, run the existing checks from the root:

```sh
npm test
npm run check
```

There are no npm dependencies to install for either project. Root commands run both projects' checks. These check code behavior; they do not evaluate a live model's editorial judgment.

## Deployment

Each project owns its deployment settings. Campaign Lab's Sites manifest is at `apps/campaign-lab/.openai/hosting.json`; its `dist` directory is relative to that app folder. The existing Site ID and web address are preserved.

GitHub holds the collection. Sites uses a separate source repository for Campaign Lab, and a GitHub push does not automatically publish a new website version. For a Campaign Lab release, synchronize **the contents of `apps/campaign-lab/`** into the existing Campaign Lab Sites checkout, preserving its `.git` directory, then follow the Sites publishing workflow. Build or package from that standalone app checkout, not the collection root. Reuse the manifest's existing Site ID.

This reorganization changes source paths only; it does not require replacing or redeploying the currently published app. New projects should use separate hosting configurations and Site IDs.

## Add the next project

1. Create `apps/<app-name>/` or `agents/<agent-name>/`.
2. Include the code and a README explaining the problem, local setup, examples, and limitations.
3. Keep credentials out of Git and document any required environment variables.
4. Add the project to the table above. Add project-specific checks and deployment instructions as needed.

This repository is public: every tracked project shares that visibility. Keep private projects in separate private repositories.

**Explore the projects. Build something. Learn along the way.**
