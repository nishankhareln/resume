import { useEffect, useRef, useState } from "react";
import Message from "./components/Message.jsx";
import { streamChat, uploadResume } from "./api.js";

const STARTERS = [
  "How does my resume look for the role I want?",
  "What skills should I focus on learning next?",
  "Can you help me prep for an interview?",
  "How do I make my resume stand out more?",
];

export default function App() {
  const [messages, setMessages] = useState([]); // [{ role, content }]
  const [background, setBackground] = useState(""); // resume briefing for the coach
  const [profile, setProfile] = useState(null); // { name, job_title, skills, ... }
  const [targetRole, setTargetRole] = useState("");
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const bottomRef = useRef(null);
  const taRef = useRef(null);

  // Keep the latest message in view as it streams in.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async (raw) => {
    const text = (raw ?? input).trim();
    if (!text || streaming) return;

    setError("");
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";

    // Append the user turn + an empty assistant bubble (which shows typing dots).
    const base = [...messages, { role: "user", content: text }];
    setMessages([...base, { role: "assistant", content: "" }]);
    setStreaming(true);

    try {
      await streamChat(base, background, (acc) => {
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = { role: "assistant", content: acc };
          return copy;
        });
      });
    } catch (e) {
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = {
          role: "assistant",
          content:
            "Sorry — I couldn't reach the coach. Make sure the API is running:\n\n`uvicorn chat_api:app --port 8000`",
        };
        return copy;
      });
      setError(String(e.message || e));
    } finally {
      setStreaming(false);
    }
  };

  const onPickFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // let the user re-pick the same file later
    if (!file) return;

    setUploading(true);
    setError("");
    try {
      const data = await uploadResume(file, targetRole);
      if (data.ok) {
        setBackground(data.background);
        setProfile(data.profile);
      } else {
        setError(data.error || "Couldn't read that resume.");
      }
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setUploading(false);
    }
  };

  const onInput = (e) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const empty = messages.length === 0;

  return (
    <div className="flex h-full w-full justify-center bg-gradient-to-b from-slate-100 to-slate-200 sm:p-4">
      <div className="flex h-full w-full max-w-3xl flex-col overflow-hidden bg-slate-50 ring-1 ring-slate-200 shadow-xl sm:rounded-2xl">
        {/* Header */}
        <header className="flex items-center gap-3 bg-gradient-to-r from-indigo-600 to-violet-600 px-5 py-4 text-white">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-white/20 text-lg font-bold ring-2 ring-white/40">
            M
          </div>
          <div className="flex-1">
            <h1 className="text-lg font-semibold leading-tight">Maya</h1>
            <p className="text-xs text-indigo-100">AI Career Coach · here to help with your job search</p>
          </div>
          <label className="cursor-pointer rounded-lg bg-white/15 px-3 py-2 text-sm font-medium transition hover:bg-white/25">
            {uploading ? "Reading…" : profile ? "Change resume" : "Attach resume"}
            <input
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={onPickFile}
              disabled={uploading}
            />
          </label>
        </header>

        {/* Resume context bar */}
        <div className="border-b border-slate-200 bg-white px-5 py-2.5">
          {profile ? (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-emerald-700">✓ Resume loaded</span>
              {profile.name && profile.name !== "Unknown" && (
                <span className="font-medium text-slate-700">{profile.name}</span>
              )}
              {profile.job_title && profile.job_title !== "Unknown" && (
                <span className="text-slate-500">· {profile.job_title}</span>
              )}
              {Array.isArray(profile.skills) && profile.skills.length > 0 && (
                <span className="text-slate-400">· {profile.skills.length} skills detected</span>
              )}
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
              <span>💡 Optional: attach your resume (PDF) so I can tailor advice to you.</span>
              <input
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                placeholder="Target role (optional)"
                className="ml-auto w-44 rounded-md border border-slate-200 px-2 py-1 text-sm outline-none focus:border-indigo-400"
              />
            </div>
          )}
        </div>

        {/* Messages */}
        <main className="flex-1 space-y-5 overflow-y-auto px-4 py-5 sm:px-6">
          {empty && (
            <div className="mx-auto max-w-md text-center">
              <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 text-2xl shadow-lg">
                👋
              </div>
              <h2 className="text-lg font-semibold text-slate-800">Hi, I'm Maya</h2>
              <p className="mt-1 text-sm text-slate-500">
                Ask me anything about your resume, skills, job hunt, or interviews. Attach your resume above and
                I'll tailor my advice to you.
              </p>
              <div className="mt-5 grid gap-2 sm:grid-cols-2">
                {STARTERS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left text-sm text-slate-600 shadow-sm transition hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <Message key={i} role={m.role} content={m.content} />
          ))}
          <div ref={bottomRef} />
        </main>

        {/* Error strip */}
        {error && (
          <div className="border-t border-rose-100 bg-rose-50 px-5 py-2 text-xs text-rose-600">{error}</div>
        )}

        {/* Composer */}
        <footer className="border-t border-slate-200 bg-white px-3 py-3 sm:px-4">
          <div className="flex items-end gap-2">
            <textarea
              ref={taRef}
              rows={1}
              value={input}
              onChange={onInput}
              onKeyDown={onKeyDown}
              placeholder="Message Maya…"
              className="max-h-40 flex-1 resize-none rounded-xl border border-slate-200 px-4 py-3 text-[15px] outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
            />
            <button
              onClick={() => send()}
              disabled={streaming || !input.trim()}
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="Send message"
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                <path d="M3.4 20.4l17.45-7.48a1 1 0 000-1.84L3.4 3.6a.993.993 0 00-1.39.91L2 9.12c0 .5.37.93.87.99L17 12 2.87 13.88c-.5.07-.87.5-.87 1l.01 4.61c0 .71.73 1.2 1.39.91z" />
              </svg>
            </button>
          </div>
          <p className="mt-1.5 px-1 text-[11px] text-slate-400">Enter to send · Shift+Enter for a new line</p>
        </footer>
      </div>
    </div>
  );
}
