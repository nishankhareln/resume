// Thin client for the FastAPI backend (chat_api.py). All calls go to /api/*,
// which Vite proxies to http://localhost:8000 in dev.

/**
 * Upload a resume PDF. Returns { ok, background, profile } or { ok:false, error }.
 * `background` is the briefing the coach uses to personalize replies.
 */
export async function uploadResume(file, targetRole = "") {
  const form = new FormData();
  form.append("file", file);
  if (targetRole) form.append("target_role", targetRole);

  const res = await fetch("/api/resume", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(`Upload failed (HTTP ${res.status})`);
  }
  return res.json();
}

/**
 * Stream the assistant's reply for a conversation.
 *
 * @param messages   full history incl. the latest user turn (no empty placeholder)
 * @param background resume briefing (may be "")
 * @param onChunk    called with the full text-so-far each time tokens arrive
 * @param signal     optional AbortSignal
 * @returns the complete reply text
 */
export async function streamChat(messages, background, onChunk, signal) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, background }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`Chat failed (HTTP ${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let acc = "";
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    // { stream: true } so multi-byte chars split across chunks decode correctly.
    acc += decoder.decode(value, { stream: true });
    onChunk(acc);
  }
  acc += decoder.decode(); // flush any trailing bytes
  onChunk(acc);
  return acc;
}
