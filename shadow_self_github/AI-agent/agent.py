"""
SHADOW SELF AI AGENT — Groq API (free tier)

How it works (the agent loop):
    1. OBSERVE  the model asks for tools (get_scores, get_alerts, ...) -> we run them on shadow_self.db
    2. THINK    the model reads the results
    3. ACT      it answers: briefing, explanation, ranked suggestions
    repeat 1-2 at most MAX_TOOL_ROUNDS times

Fallbacks: no key / no internet / rate limit / model error -> a plain briefing built
from the rules engine, so the system always gives an answer.

Run from the shadow_self folder:
    python3 AI-agent/agent.py --test           check your key + connection
    python3 AI-agent/agent.py --brief A2 3     daily briefing for A2, day 3
    python3 AI-agent/agent.py                  chat (type 'quit' to stop)
    add --fast to use the small test model (higher free limits)
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_prompts as prompts  # noqa: E402
import agent_tools as tools  # noqa: E402
from agent_settings import (AGENT_MODEL, BACKUP_MODEL, REASONING_EFFORT, GROQ_BASE_URL, HERE, MAX_ANSWER_TOKENS, MAX_TOOL_ROUNDS,  # noqa: E402
                      TEMPERATURE, TEST_MODEL)


# ---------------- setup ----------------
def load_key():
    """Key from the environment, or from AI-agent/.env (KEY=value lines)."""
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"]
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        for line in open(path):
            if line.strip().startswith("GROQ_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key and key != "paste-your-key-here":
                    return key
    return None


def make_client():
    key = load_key()
    if not key:
        return None, "No Groq key found. Put it in AI-agent/.env (see .env.example)."
    try:
        from openai import OpenAI
    except ImportError:
        return None, "The 'openai' package is missing. Run: python3 -m pip install -r AI-agent/requirements.txt"
    # Ask for gzip, not brotli: an older "brotli" package on some Macs crashes the newer HTTP library
    # ("process() takes no keyword arguments"). gzip is built into Python, so this always works.
    return OpenAI(base_url=GROQ_BASE_URL, api_key=key,
                  default_headers={"Accept-Encoding": "gzip, deflate"}), None


# ---------------- one request to Groq ----------------
def groq_request(client, model, messages, tool_choice="auto"):
    kw = dict(model=model, messages=messages, tools=tools.TOOL_SPECS, tool_choice=tool_choice,
              temperature=TEMPERATURE, max_tokens=MAX_ANSWER_TOKENS)
    if "gpt-oss" in model:                                   # thinking model: keep its silent thinking short
        kw["extra_body"] = {"reasoning_effort": REASONING_EFFORT}
    reply = client.chat.completions.create(**kw)
    if os.environ.get("AGENT_DEBUG"):
        ch, u = reply.choices[0], getattr(reply, "usage", None)
        print(f"   [groq] {model} finish={getattr(ch, 'finish_reason', '?')} "
              f"tokens={getattr(u, 'total_tokens', '?')}")
    return reply.choices[0].message


# ---------------- the agent loop ----------------
def ask(question, history=None, model=AGENT_MODEL, client=None):
    """Answer one question. Returns (answer, used_ai). Never raises."""
    if client is None:
        client, problem = make_client()
        if client is None:
            return fallback_answer(question, problem), False
    messages = [{"role": "system", "content": prompts.SYSTEM + "\n\n" + prompts.EXAMPLE_BRIEFING}]
    messages += (history or []) + [{"role": "user", "content": question}]
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            msg = groq_request(client, model, messages)
            if not msg.tool_calls:                                   # no more tools needed -> final answer
                return finish(client, model, messages, msg)
            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [{"id": c.id, "type": "function",
                                             "function": {"name": c.function.name,
                                                          "arguments": c.function.arguments}}
                                            for c in msg.tool_calls]})
            for call in msg.tool_calls:                              # OBSERVE: run each tool on our database
                if os.environ.get("AGENT_DEBUG"):
                    print(f"   [tool] {call.function.name}({call.function.arguments})")
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": tools.run_tool(call.function.name, call.function.arguments)})
        # out of tool rounds: make it answer with what it already found (no more tools)
        messages.append({"role": "user", "content": "Answer now using only the information above."})
        return finish(client, model, messages, groq_request(client, model, messages, "none"))
    except Exception as e:  # noqa: BLE001  rate limit, no internet, bad key, model renamed...
        return fallback_answer(question, explain_error(e)), False


def finish(client, model, messages, msg):
    """Return the answer. Empty? -> ask the backup model once, then the rules-engine fallback."""
    text = (msg.content or "").strip()
    if text:
        return text, True
    if model != BACKUP_MODEL:
        if os.environ.get("AGENT_DEBUG"):
            print(f"   [groq] empty answer from {model} -> trying {BACKUP_MODEL}")
        text = (groq_request(client, BACKUP_MODEL, messages, "none").content or "").strip()
        if text:
            return text, True
    return fallback_answer(messages[-1]["content"][:200], "The AI returned an empty answer."), False


def explain_error(e):
    text = f"{type(e).__name__}: {e}"
    if "401" in text or "invalid_api_key" in text.lower() or "Authentication" in text:
        return "Groq rejected the key (check AI-agent/.env)."
    if "429" in text or "RateLimit" in text:
        return "Groq free-tier rate limit reached — wait a minute, or use --fast."
    if "model" in text.lower() and ("not found" in text.lower() or "decommission" in text.lower()):
        return "That model name is no longer on Groq — update AGENT_MODEL in AI-agent/settings.py."
    if "process() takes no keyword" in text:
        return "Old 'brotli' package on this computer. Run: python3 -m pip install --upgrade brotli"
    if "Connection" in text or "timed out" in text.lower():
        return "Can't reach Groq (no internet?)."
    return text[:200]


# ---------------- fallback: rules-only briefing ----------------
def fallback_answer(question, why):
    """No AI available: still give a useful, honest answer from the rules engine."""
    try:
        import re
        ids = list(dict.fromkeys(re.findall(r"\bA\d+\b", question)))    # unique, in order
        day = re.search(r"\bday\s*(\d+)", question, re.I)
        overview = tools.get_overview()
        astronauts = ids or re.findall(r"^(A\d+):", overview, re.M)
        parts = [f"[AI offline — {why} Showing the rules-engine summary instead.]"]
        for a in astronauts[:2]:
            d = int(day.group(1)) if day else None
            parts += [tools.get_scores(a, d), "Alerts:", tools.get_alerts(a, d), "Plan:", tools.get_plan(a, d)]
        return "\n".join(parts)
    except Exception as e:  # noqa: BLE001
        return f"[AI offline — {why}] Could not read the database either: {e}"


def briefing(astronaut, day=None, model=AGENT_MODEL):
    """Hand the AI today's data + the matching guidelines up front -> usually ONE request, no tool rounds."""
    day = day or tools._latest_day(astronaut)
    summary = tools.get_day_summary(astronaut, day)
    systems = [s for s in ("radiation", "muscle", "bone", "sans", "cardio")
               if re.search(rf"- {s}: \S+ (WATCH|ACT|URGENT)", summary)]
    guide = tools.look_up_guideline(", ".join(systems)) if systems else "All systems OK."
    question = (prompts.BRIEFING_REQUEST.format(astronaut=astronaut, day=day)
                + "\n\nTODAY'S DATA (from the monitoring system):\n" + summary
                + "\n\nGUIDELINES FOR THE SYSTEMS THAT NEED ATTENTION:\n" + guide)
    return ask(question, model=model)


# ---------------- command line ----------------
def main():
    args = sys.argv[1:]
    model = TEST_MODEL if "--fast" in args else AGENT_MODEL
    args = [a for a in args if a != "--fast"]

    if args[:1] == ["--test"]:
        client, problem = make_client()
        if client is None:
            return print("❌", problem)
        try:
            r = client.chat.completions.create(model=model, max_tokens=10,
                                               messages=[{"role": "user", "content": "Reply with: ready"}])
            print(f"✅ Groq works with {model}: {r.choices[0].message.content.strip()}")
        except Exception as e:  # noqa: BLE001
            import platform
            import traceback
            print("❌", explain_error(e))
            print("\n--- details (safe to share: no key inside) ---")
            try:
                import httpx
                import openai
                print(f"python {platform.python_version()} | openai {openai.__version__} | httpx {httpx.__version__}")
            except Exception:  # noqa: BLE001
                pass
            print("".join(traceback.format_exc().splitlines(keepends=True)[-14:]))
        return

    if args[:1] == ["--brief"]:
        astronaut = args[1] if len(args) > 1 else "A2"
        day = int(args[2]) if len(args) > 2 else None
        answer, used_ai = briefing(astronaut, day, model)
        return print(("🛰️  " if used_ai else "") + answer)

    print(f"Shadow Self AI ({model}). Ask about any astronaut, e.g. 'Why is A2's bone score low?'. 'quit' to stop.")
    history = []
    while True:
        try:
            q = input("\nyou > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in ("quit", "exit", "q"):
            break
        if not q:
            continue
        answer, used_ai = ask(q, history, model)
        print("\nshadow self > " + answer)
        if used_ai:                                   # remember the conversation (short, to save tokens)
            history = (history + [{"role": "user", "content": q}, {"role": "assistant", "content": answer}])[-6:]


if __name__ == "__main__":
    main()
