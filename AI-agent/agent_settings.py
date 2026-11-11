"""
AI AGENT SETTINGS — change models here (Groq's model list changes over time).
Check current model names at console.groq.com -> Playground / Models.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the shadow_self folder
DB_PATH = os.path.join(ROOT, "shadow_self.db")
HERE = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE = os.path.join(HERE, "knowledge.md")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
AGENT_MODEL = "openai/gpt-oss-120b"        # demo model: strong tool use
TEST_MODEL = "llama-3.1-8b-instant"        # cheap + fast for everyday testing (higher free limits)
MAX_TOOL_ROUNDS = 4                        # agent may call tools at most this many rounds per question
MAX_ANSWER_TOKENS = 2500                   # thinking models need room to reason AND write the answer
REASONING_EFFORT = "low"                   # for thinking models (gpt-oss): less silent thinking, faster answers
BACKUP_MODEL = "llama-3.3-70b-versatile"   # used automatically if the main model returns an empty answer
TEMPERATURE = 0.3                          # low = steady, factual answers

# token savers
SKIP_AI_WHEN_OK = True                     # astronaut with every system OK -> one-line summary, no AI call
BRIEFING_GAP_SECONDS = 3                   # pause between crew briefings (stay under free-tier rate limits)
