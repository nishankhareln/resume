# What Makes It Unique

> **One-line pitch:** It's not a resume scanner or a chatbot — it's a **career copilot** that reads
> your resume, scores you against real jobs *for free*, and tells you the truth about your fit,
> grounded in evidence.

Resume parsing, a chat box, and a jobs list each exist in many products. What's original here is
**the combination** and a handful of deliberate design choices. This doc is the honest version —
including what is *not* unique.

---

## The one big differentiator

**NK is a context-aware copilot, not a chatbot.**

It holds two things in context at the same time — your **parsed resume** *and* the **exact job you're
viewing** — and reasons about them together. Tap "Ask NK about this" on a posting and it tells you
*why* you're (say) a 78% match and *what one gap* is holding you back, grounded in both your CV and
that job's actual text.

| Typical tool | What it can't do |
|---|---|
| Generic AI chatbot (e.g. ChatGPT) | Doesn't know your resume or the live job. |
| Resume analyzer | Gives a static, one-time report — no live jobs, no conversation. |
| Job board | Lists jobs but can't reason about *you* vs. *this* role. |
| **This platform** | **All three at once, live: your resume × this job × a conversation.** |

That fusion — resume-aware **and** job-aware in one live conversation — is the core unique feature.

---

## The other things most tools don't have

1. **Grounded, not hallucinated.** The recruiter side answers with *verbatim evidence quotes* from
   the resume plus a confidence flag (`explicitly_stated` / `implied` / `not_found`) and refuses to
   invent a skill that isn't there. For hiring decisions, "the AI made it up" is a dealbreaker —
   so we engineered against it.

2. **Bias guardrail built in.** Every screening prompt explicitly instructs the model to judge only
   skills and experience and to ignore name, gender, age, and nationality. That's what makes a
   people-screening tool *defensible to actually deploy*, not just a demo.

3. **Free, private, local matching.** All semantic match scoring runs on a local model
   (sentence-transformers MiniLM) — no API cost per comparison, no quota, and the resume isn't sent
   to a third party for that step. Most competitors bill an API call for every match.

4. **Quota-conscious engineering.** It runs on a *free* Gemini tier on purpose: one LLM call on
   upload, then only when the user asks. Most demos fire many calls at once and die on rate limits.

5. **Handles scanned resumes.** An OCR fallback (Tesseract at 300 DPI) reads image/scanned PDFs that
   plain text parsers choke on.

6. **Both sides of the hiring table, one brain.** A candidate mode *and* a recruiter screening mode,
   sharing the same core. Most tools serve only job seekers or only recruiters.

7. **Two job markets.** US (JSearch) **and Nepal (merojob.com)** — a market most global tools ignore.

8. **A transparent score, not a black box.** The readiness score is an explainable weighted formula
   (35% skill overlap + 25% semantic + 20% experience + 10% keyword quality + 10% LinkedIn), so a
   user can see *why* they scored what they did.

9. **A full career pipeline in one place.** parse → skill gap → job match → interview prep →
   30/60/90-day roadmap → LinkedIn optimization → ATS audit. Most tools do a single slice.

10. **Production-shaped, not a toy.** A Python AI core behind a clean streaming API with a React +
    Tailwind frontend — the same architecture real products use, not a single notebook or script.

---

## Feature comparison

| Capability | Generic AI chatbot | Resume scanner / ATS checker | Job board | **This platform** |
|---|:--:|:--:|:--:|:--:|
| Knows your actual resume | ✗ | ✓ | ✗ | ✓ |
| Reasons about a *specific* job vs. you | ✗ | ✗ | ✗ | ✓ |
| Live, natural conversation | ✓ | ✗ | ✗ | ✓ |
| Match score per job | ✗ | partial | ✗ | ✓ |
| Evidence-grounded / anti-hallucination | ✗ | ✗ | — | ✓ |
| Bias / fairness guardrail | ✗ | rare | — | ✓ |
| Free local matching (no per-call cost) | ✗ | ✗ | — | ✓ |
| Reads scanned/image PDFs (OCR) | ✗ | some | — | ✓ |
| Candidate **and** recruiter modes | ✗ | ✗ | ✗ | ✓ |
| Localized (US + Nepal) | ✗ | ✗ | some | ✓ |

*(— = not applicable to that category.)*

---

## What is *not* unique (being honest)

- Parsing a resume into structured fields — common.
- A chat interface — common.
- Listing jobs — common.

The originality is in **how these are combined** and the specific choices: **context-aware fit
reasoning** (resume × job), **grounded and fair** screening, and **free local matching** that keeps
it cheap and private. Take any one feature alone and you'll find it elsewhere; the value is the whole.

---

*See [`DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md) for how each of these is implemented, and
[`docs/architecture.svg`](architecture.svg) for the system diagram.*
