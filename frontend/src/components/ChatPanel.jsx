import { useEffect, useRef, useState } from "react";
import Message from "./Message.jsx";

const GENERAL_STARTERS = [
  "What are my strongest skills?",
  "What should I learn next?",
  "How can I improve my resume?",
];

const JOB_STARTERS = [
  "Am I a good fit for this role?",
  "Tailor my resume for this job",
  "Draft a cover letter for this",
];

export default function ChatPanel({ messages, streaming, onSend, activeJob, onClearContext, hasResume }) {
  const [input, setInput] = useState("");
  const bottomRef = useRef(null);
  const taRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const submit = (text) => {
    const t = (text ?? input).trim();
    if (!t || streaming) return;
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";
    onSend(t);
  };

  const onInput = (e) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 140) + "px";
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const empty = messages.length === 0;
  const starters = activeJob ? JOB_STARTERS : GENERAL_STARTERS;

  return (
    <div className="flex h-full flex-col bg-slate-50">
      {/* Header */}
      <div className="flex items-center gap-3 bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-3 text-white">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 text-sm font-bold ring-2 ring-white/40">
          NK
        </div>
        <div>
          <p className="font-semibold leading-tight">NK</p>
          <p className="text-xs text-indigo-100">AI Career Coach</p>
        </div>
      </div>

      {/* Job-context banner */}
      {activeJob && (
        <div className="flex items-center gap-2 border-b border-indigo-100 bg-indigo-50 px-4 py-2 text-sm">
          <span className="text-indigo-400">💬</span>
          <span className="min-w-0 flex-1 truncate text-indigo-700">
            Discussing: <span className="font-medium">{activeJob.title}</span>
          </span>
          <button onClick={onClearContext} className="text-indigo-400 hover:text-indigo-700" title="Stop discussing this job">
            ✕
          </button>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 space-y-4 overflow-y-auto px-3 py-4">
        {empty && (
          <div className="px-1 text-center text-sm text-slate-500">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 text-xl shadow">
              👋
            </div>
            <p className="font-medium text-slate-700">Hi, I'm NK</p>
            <p className="mt-1">
              {hasResume
                ? "Ask me anything, or pick a job and tap “Ask NK about this”."
                : "Upload your resume above and I'll tailor everything to you."}
            </p>
          </div>
        )}

        {messages.map((m, i) => (
          <Message key={i} role={m.role} content={m.content} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Starters */}
      {(empty || activeJob) && (
        <div className="flex flex-wrap gap-2 px-3 pb-2">
          {starters.map((s) => (
            <button
              key={s}
              onClick={() => submit(s)}
              disabled={streaming}
              className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 transition hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Composer */}
      <div className="border-t border-slate-200 bg-white px-3 py-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={taRef}
            rows={1}
            value={input}
            onChange={onInput}
            onKeyDown={onKeyDown}
            placeholder="Message NK…"
            className="max-h-36 flex-1 resize-none rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
          />
          <button
            onClick={() => submit()}
            disabled={streaming || !input.trim()}
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Send message"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
              <path d="M3.4 20.4l17.45-7.48a1 1 0 000-1.84L3.4 3.6a.993.993 0 00-1.39.91L2 9.12c0 .5.37.93.87.99L17 12 2.87 13.88c-.5.07-.87.5-.87 1l.01 4.61c0 .71.73 1.2 1.39.91z" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
