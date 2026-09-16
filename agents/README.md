# Agents

## Available projects

| Project | How it works | What you learn |
| --- | --- | --- |
| [LinkedIn Post Coach](linkedin-post-coach/) | Reusable reviewer instructions pasted into ChatGPT; no separate API key. | Rubric design, structured feedback, factual grounding, and manual model evaluation. |
| [Product Sense Mock](product-sense-mock/) | A Python tool-use loop against the Anthropic API, with an offline mode that needs no key. | Agent loops, tool-call state machines, rubric scoring, and testing an agent without a model. |

The two take different approaches on purpose. LinkedIn Post Coach is an instruction-based reviewer: the rubric lives in prose you paste into a chat. Product Sense Mock runs a real agent loop, where the rubric is code and the model's judgements come back as tool calls the harness can constrain. Neither takes action outside the conversation.

Give each new agent its own folder with a README covering its purpose, setup, example inputs and outputs, required services, and limitations. Store secrets outside Git. Document how any external actions are authorized.

Return to the [project collection](../README.md).
