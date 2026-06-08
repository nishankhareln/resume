import { useState } from "react";
import { hrChat, hrIndex, hrScreen, hrSearch } from "./api.js";

const VERDICT = {
  strong_match: ["Strong match", "bg-emerald-100 text-emerald-700"],
  possible_match: ["Possible match", "bg-sky-100 text-sky-700"],
  weak_match: ["Weak match", "bg-amber-100 text-amber-700"],
  not_a_match: ["Not a match", "bg-rose-100 text-rose-700"],
};

const CONFIDENCE = {
  explicitly_stated: ["✓ Stated in resume", "bg-emerald-100 text-emerald-700"],
  implied: ["≈ Implied", "bg-amber-100 text-amber-700"],
  not_found: ["⚠ Not in this resume", "bg-rose-100 text-rose-700"],
};

const SUGGESTED = [
  "What are their strongest skills?",
  "How many years of relevant experience?",
  "Have they led a team or project?",
  "What's missing or unclear in this resume?",
];

function Badge({ map, k, fallback }) {
  const [label, cls] = map[k] || [fallback || k, "bg-slate-100 text-slate-600"];
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${cls}`}>{label}</span>;
}

export default function RecruiterApp() {
  const [hrSessionId, setHrSessionId] = useState(null);
  const [candidates, setCandidates] = useState([]); // indexed pool
  const [results, setResults] = useState([]); // ranked search results
  const [criteria, setCriteria] = useState("");
  const [indexing, setIndexing] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");

  const [selectedId, setSelectedId] = useState(null);
  const [screens, setScreens] = useState({}); // id -> screen
  const [screening, setScreening] = useState(false);
  const [chats, setChats] = useState({}); // id -> [{role, ...}]
  const [asking, setAsking] = useState(false);
  const [question, setQuestion] = useState("");

  const byId = (id) => candidates.find((c) => c.id === id);
  const list = results.length ? results : candidates;

  const onIndex = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    setIndexing(true);
    setError("");
    try {
      const data = await hrIndex(files);
      if (data.ok) {
        setHrSessionId(data.hr_session_id);
        setCandidates(data.candidates);
        setResults([]);
        setScreens({});
        setChats({});
        setSelectedId(null);
      } else {
        setError(data.error || "Couldn't index those resumes.");
      }
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setIndexing(false);
    }
  };

  const onRank = async () => {
    if (!hrSessionId || !criteria.trim()) return;
    setSearching(true);
    setError("");
    try {
      const data = await hrSearch(hrSessionId, criteria.trim());
      if (data.ok) setResults(data.results);
      else setError(data.error || "Search failed.");
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setSearching(false);
    }
  };

  const onScreen = async (id) => {
    if (!criteria.trim()) {
      setError("Add the role / criteria above first, then screen.");
      return;
    }
    setSelectedId(id);
    setScreening(true);
    setError("");
    try {
      const data = await hrScreen(hrSessionId, id, criteria.trim());
      if (data.ok) setScreens((s) => ({ ...s, [id]: data.screen }));
      else setError(data.error || "Screening failed.");
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setScreening(false);
    }
  };

  const ask = async (id, q) => {
    const text = (q ?? question).trim();
    if (!text || asking) return;
    setQuestion("");
    const prior = chats[id] || [];
    const history = prior.map((m) => ({ role: m.role, content: m.role === "user" ? m.content : m.answer }));
    setChats((c) => ({ ...c, [id]: [...prior, { role: "user", content: text }] }));
    setAsking(true);
    try {
      const data = await hrChat(hrSessionId, id, text, history);
      const a = data.ok ? data.answer : { answer: data.error || "Couldn't answer.", confidence: "not_found", evidence: [] };
      setChats((c) => ({ ...c, [id]: [...(c[id] || []), { role: "assistant", ...a }] }));
    } catch (err) {
      setChats((c) => ({ ...c, [id]: [...(c[id] || []), { role: "assistant", answer: String(err.message || err), confidence: "not_found", evidence: [] }] }));
    } finally {
      setAsking(false);
    }
  };

  const selected = selectedId ? byId(selectedId) : null;
  const screen = selectedId ? screens[selectedId] : null;
  const convo = selectedId ? chats[selectedId] || [] : [];

  return (
    <div className="flex h-full flex-col">
      {/* Controls bar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-5 py-2.5">
        <span className="text-sm font-medium text-slate-600">
          Screen a pool of resumes {candidates.length > 0 && `· ${candidates.length} indexed`}
        </span>
        <label className="ml-auto cursor-pointer rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-indigo-700">
          {indexing ? "Indexing…" : candidates.length ? "Add / replace resumes" : "Upload resumes (PDF)"}
          <input type="file" accept="application/pdf" multiple className="hidden" onChange={onIndex} disabled={indexing} />
        </label>
      </div>

      {error && <div className="bg-rose-50 px-5 py-2 text-xs text-rose-600">{error}</div>}

      {candidates.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-8 text-center">
          <div className="max-w-sm text-slate-500">
            <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 text-2xl shadow">📁</div>
            <p className="font-medium text-slate-700">Upload your resume pool</p>
            <p className="mt-1 text-sm">Select several candidate PDFs. They're indexed locally (free, private) so you can rank, screen, and ask about anyone — every answer grounded in their resume.</p>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden lg:flex-row">
          {/* Left: search + candidate list */}
          <section className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
            <div className="mx-auto max-w-2xl">
              <textarea
                value={criteria}
                onChange={(e) => setCriteria(e.target.value)}
                placeholder="Describe who you want, or paste a job description…&#10;e.g. Backend engineer with 3+ yrs Python + AWS who has led a small team"
                rows={3}
                className="w-full resize-none rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
              />
              <div className="mt-2 flex items-center gap-2">
                <button onClick={onRank} disabled={searching || !criteria.trim()} className="rounded-xl bg-slate-800 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-900 disabled:opacity-40">
                  {searching ? "Ranking…" : "🔎 Rank candidates"}
                </button>
                <span className="text-xs text-slate-400">{results.length ? "Ranked by semantic match" : `${candidates.length} candidates`}</span>
              </div>

              <div className="mt-4 space-y-3 pb-6">
                {list.map((c, i) => {
                  const score = c.score != null ? Math.round(c.score * 100) : null;
                  const tone = score == null ? "" : score >= 70 ? "bg-emerald-100 text-emerald-700" : score >= 55 ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500";
                  return (
                    <div key={c.id} className={`rounded-2xl border bg-white p-4 shadow-sm transition ${selectedId === c.id ? "border-indigo-400 ring-2 ring-indigo-100" : "border-slate-200 hover:border-indigo-200"}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h3 className="font-semibold text-slate-800">
                            {results.length ? `${i + 1}. ` : ""}{c.name}
                          </h3>
                          <p className="truncate text-xs text-slate-400">{c.file}</p>
                        </div>
                        {score != null && <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>{score}% match</span>}
                      </div>
                      {c.snippet && <p className="mt-2 line-clamp-2 text-sm text-slate-600">{c.snippet}…</p>}
                      <div className="mt-3 flex gap-2">
                        <button onClick={() => setSelectedId(c.id)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50">Open</button>
                        <button onClick={() => onScreen(c.id)} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-indigo-700">AI screen</button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          {/* Right: selected candidate detail */}
          <aside className="flex h-[60vh] flex-col overflow-y-auto border-t border-slate-200 bg-slate-50 lg:h-auto lg:w-[420px] lg:border-l lg:border-t-0">
            {!selected ? (
              <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-slate-400">
                Select a candidate to screen them or ask grounded questions.
              </div>
            ) : (
              <div className="flex flex-col gap-4 p-4">
                <div>
                  <h2 className="text-lg font-semibold text-slate-800">{selected.name}</h2>
                  <p className="text-xs text-slate-400">{selected.file}</p>
                </div>

                {/* Screen result */}
                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-slate-700">Fit screen</span>
                    <button onClick={() => onScreen(selected.id)} disabled={screening} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-indigo-700 disabled:opacity-40">
                      {screening ? "Screening…" : screen ? "Re-screen" : "Screen vs. criteria"}
                    </button>
                  </div>
                  {screen ? (
                    <div className="mt-3 space-y-2 text-sm">
                      <div className="flex items-center gap-2">
                        <Badge map={VERDICT} k={screen.verdict} />
                        <span className="text-slate-500">fit {screen.fit_score}/100</span>
                      </div>
                      {screen.rationale && <p className="text-slate-600">{screen.rationale}</p>}
                      {screen.matched_requirements?.length > 0 && (
                        <div><p className="font-medium text-slate-700">Meets</p>
                          <ul className="ml-4 list-disc text-slate-600">{screen.matched_requirements.map((r, i) => <li key={i}>✅ {r}</li>)}</ul></div>
                      )}
                      {screen.missing_requirements?.length > 0 && (
                        <div><p className="font-medium text-slate-700">Gaps</p>
                          <ul className="ml-4 list-disc text-slate-600">{screen.missing_requirements.map((r, i) => <li key={i}>❌ {r}</li>)}</ul></div>
                      )}
                      {screen.evidence?.length > 0 && (
                        <details className="text-slate-600"><summary className="cursor-pointer text-indigo-600">Evidence from resume</summary>
                          {screen.evidence.map((q, i) => <p key={i} className="mt-1 border-l-2 border-slate-200 pl-2 italic">{q}</p>)}</details>
                      )}
                    </div>
                  ) : (
                    <p className="mt-2 text-xs text-slate-400">Add criteria above, then screen this candidate against it.</p>
                  )}
                </div>

                {/* Grounded Q&A */}
                <div className="rounded-2xl border border-slate-200 bg-white p-4">
                  <p className="mb-2 text-sm font-semibold text-slate-700">Ask about this candidate</p>
                  <div className="space-y-3">
                    {convo.length === 0 && (
                      <div className="flex flex-wrap gap-2">
                        {SUGGESTED.map((q) => (
                          <button key={q} onClick={() => ask(selected.id, q)} disabled={asking} className="rounded-full border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition hover:border-indigo-300 hover:bg-indigo-50 disabled:opacity-50">{q}</button>
                        ))}
                      </div>
                    )}
                    {convo.map((m, i) =>
                      m.role === "user" ? (
                        <p key={i} className="ml-auto w-fit max-w-[90%] rounded-xl bg-indigo-600 px-3 py-2 text-sm text-white">{m.content}</p>
                      ) : (
                        <div key={i} className="rounded-xl bg-slate-100 px-3 py-2 text-sm text-slate-800">
                          <p>{m.answer}</p>
                          <div className="mt-1.5"><Badge map={CONFIDENCE} k={m.confidence} fallback="—" /></div>
                          {m.evidence?.length > 0 && (
                            <details className="mt-1 text-xs text-slate-600"><summary className="cursor-pointer text-indigo-600">Evidence</summary>
                              {m.evidence.map((q, j) => <p key={j} className="mt-1 border-l-2 border-slate-300 pl-2 italic">{q}</p>)}</details>
                          )}
                        </div>
                      )
                    )}
                    {asking && <p className="text-xs text-slate-400">Reading the resume…</p>}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <input
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && ask(selected.id)}
                      placeholder="e.g. Does he know Docker or Kubernetes?"
                      className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
                    />
                    <button onClick={() => ask(selected.id)} disabled={asking || !question.trim()} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:opacity-40">Ask</button>
                  </div>
                </div>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
