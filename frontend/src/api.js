// Thin client for the FastAPI backend (chat_api.py). All calls go to /api/*,
// which Vite proxies to http://localhost:8000 in dev (and is same-origin in prod).

/**
 * Upload a resume PDF. Returns { ok, session_id, background, profile } or { ok:false, error }.
 * The session_id is reused for job matching and chat so we don't resend the resume.
 */
export async function uploadResume(file, targetRole = "") {
  const form = new FormData();
  form.append("file", file);
  if (targetRole) form.append("target_role", targetRole);

  const res = await fetch("/api/resume", { method: "POST", body: form });
  if (!res.ok) throw new Error(`Upload failed (HTTP ${res.status})`);
  return res.json();
}

/**
 * List/search jobs. With a session_id, each job carries a 0-1 match_score and
 * the list is sorted best-first. Returns { ok, count, has_resume, jobs }.
 */
export async function fetchJobs(sessionId = "", q = "") {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  if (q) params.set("q", q);
  const res = await fetch(`/api/jobs?${params.toString()}`);
  if (!res.ok) throw new Error(`Jobs request failed (HTTP ${res.status})`);
  return res.json();
}

/**
 * Stream NK's reply for a conversation.
 *
 * @param messages full history incl. the latest user turn
 * @param opts     { sessionId, jobContext } — sessionId pulls the resume background
 *                 server-side; jobContext is the job currently in focus (copilot mode)
 * @param onChunk  called with the full text-so-far as tokens arrive
 */
export async function streamChat(messages, opts, onChunk, signal) {
  const { sessionId = null, jobContext = null } = opts || {};
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, session_id: sessionId, job_context: jobContext }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`Chat failed (HTTP ${res.status})`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let acc = "";
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    acc += decoder.decode(value, { stream: true });
    onChunk(acc);
  }
  acc += decoder.decode();
  onChunk(acc);
  return acc;
}

// --- HR / Recruiter mode ----------------------------------------------------

/** Upload + index a batch of resume PDFs. Returns { ok, hr_session_id, candidates }. */
export async function hrIndex(files) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await fetch("/api/hr/index", { method: "POST", body: form });
  if (!res.ok) throw new Error(`Index failed (HTTP ${res.status})`);
  return res.json();
}

/** Rank the indexed pool against a query / job description. Returns { ok, results }. */
export async function hrSearch(hrSessionId, query, topK = 10) {
  const res = await fetch("/api/hr/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hr_session_id: hrSessionId, query, top_k: topK }),
  });
  if (!res.ok) throw new Error(`Search failed (HTTP ${res.status})`);
  return res.json();
}

/** Grounded AI fit-screen of one candidate against criteria. Returns { ok, screen }. */
export async function hrScreen(hrSessionId, candidateId, criteria) {
  const res = await fetch("/api/hr/screen", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hr_session_id: hrSessionId, candidate_id: candidateId, criteria }),
  });
  if (!res.ok) throw new Error(`Screen failed (HTTP ${res.status})`);
  return res.json();
}

/** Grounded Q&A about one candidate. Returns { ok, answer:{answer,confidence,evidence,follow_up_suggestions} }. */
export async function hrChat(hrSessionId, candidateId, question, history = []) {
  const res = await fetch("/api/hr/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hr_session_id: hrSessionId, candidate_id: candidateId, question, history }),
  });
  if (!res.ok) throw new Error(`Chat failed (HTTP ${res.status})`);
  return res.json();
}
