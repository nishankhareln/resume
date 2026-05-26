"""Probe each candidate Gemini model with a 5-token call and report which
ones your API key actually has quota for *right now*. Free tier is usually
on flash-lite variants when the standard flash models hit limit:0.
"""

import os
import time
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("GEMINI_API_KEY")
if not KEY:
    print("GEMINI_API_KEY missing in .env")
    raise SystemExit(1)

import google.generativeai as genai
genai.configure(api_key=KEY)

# Ordered: try cheapest/most-likely-free-tier first
CANDIDATES = [
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
]

PROMPT = "Reply with the single word: OK"

results = []
for name in CANDIDATES:
    try:
        m = genai.GenerativeModel(name)
        r = m.generate_content(PROMPT)
        text = (r.text or "").strip()
        results.append((name, "OK", text[:30]))
        print(f"OK    {name}  ->  {text[:30]!r}")
    except Exception as e:
        msg = str(e)
        short = "quota/limit 0" if "limit: 0" in msg else (
                "quota exhausted (retry later)" if "ResourceExhausted" in msg or "429" in msg else
                "not found / permission" if "404" in msg or "NotFound" in msg or "PERMISSION" in msg else
                msg[:120])
        results.append((name, "FAIL", short))
        print(f"FAIL  {name}  ->  {short}")
    time.sleep(0.4)  # small pause to avoid burst-limiting

print()
working = [n for n, s, _ in results if s == "OK"]
if working:
    print(f"USE THIS in your .env -> GEMINI_MODEL={working[0]}")
else:
    print("None of the candidates worked. Your daily free quota is fully exhausted across all flash variants.")
    print("Options: (a) wait until ~midnight Pacific for daily reset, (b) generate a new API key from a fresh Google Cloud project, (c) enable billing.")
