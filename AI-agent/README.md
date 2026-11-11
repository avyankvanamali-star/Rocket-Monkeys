# Shadow Self AI agent (Groq, free tier)

| File | What it does |
|---|---|
| agent.py | The agent loop + command line + fallback when the AI is offline |
| agent_tools.py | 7 tools that read shadow_self.db (scores, alerts, checks, trends, plan, guidelines) |
| agent_prompts.py | The agent's job, rules (guardrails) and an example briefing |
| knowledge.md | The team's research per health risk — the agent's "textbook" (edit freely) |
| agent_settings.py | Model names, limits |
| .env | YOUR Groq key (you create this; never share it) |

Setup (once): see the steps in the chat / below.
    python3 -m pip install -r AI-agent/requirements.txt
    cp AI-agent/.env.example AI-agent/.env      # then paste your key into AI-agent/.env

Use (from the shadow_self folder):
    python3 AI-agent/agent.py --test            # check key + connection
    python3 AI-agent/agent.py --brief A2 3      # daily briefing
    python3 AI-agent/agent.py                   # chat
    add --fast for the small model (higher free limits); AGENT_DEBUG=1 shows tool calls
