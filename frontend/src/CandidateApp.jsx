import { useEffect, useState } from "react";
import JobCard from "./components/JobCard.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import { fetchJobs, streamChat, uploadResume } from "./api.js";

// Job-seeker view: a jobs board scored against your resume + NK as a copilot.
export default function CandidateApp() {
  const [sessionId, setSessionId] = useState(null);
  const [profile, setProfile] = useState(null);
  const [targetRole, setTargetRole] = useState("");
  const [uploading, setUploading] = useState(false);

  const [jobs, setJobs] = useState([]);
  const [query, setQuery] = useState("");
  const [jobsLoading, setJobsLoading] = useState(false);

  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [activeJob, setActiveJob] = useState(null);

  const [error, setError] = useState("");

  const loadJobs = async (q = query, sid = sessionId) => {
    setJobsLoading(true);
    try {
      const data = await fetchJobs(sid || "", q || "");
      if (data.ok) setJobs(data.jobs);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setJobsLoading(false);
    }
  };

  useEffect(() => {
    loadJobs("", "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onPickFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const data = await uploadResume(file, targetRole);
      if (data.ok) {
        setSessionId(data.session_id);
        setProfile(data.profile);
        await loadJobs(query, data.session_id);
      } else {
        setError(data.error || "Couldn't read that resume.");
      }
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setUploading(false);
    }
  };

  const send = async (text, jobOverride) => {
    const t = (text ?? "").trim();
    if (!t || streaming) return;
    setError("");
    const job = jobOverride ?? activeJob;
    const base = [...messages, { role: "user", content: t }];
    setMessages([...base, { role: "assistant", content: "" }]);
    setStreaming(true);
    try {
      const jobContext = job
        ? { id: job.id, title: job.title, company: job.company, location: job.location, match_score: job.match_score, description: job.description }
        : null;
      await streamChat(base, { sessionId, jobContext }, (acc) => {
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = { role: "assistant", content: acc };
          return copy;
        });
      });
    } catch (e) {
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { role: "assistant", content: "Sorry — I couldn't reach the coach. Is the API running on port 8000?" };
        return copy;
      });
      setError(String(e.message || e));
    } finally {
      setStreaming(false);
    }
  };

  const onAsk = (job) => {
    setActiveJob(job);
    send("Am I a good fit for this role?", job);
  };

  const firstName = profile?.name && profile.name !== "Unknown" ? profile.name.split(" ")[0] : null;

  return (
    <div className="flex h-full flex-col">
      {/* Controls bar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-5 py-2.5">
        <span className="text-sm font-medium text-slate-600">Find roles that match your resume</span>
        <div className="ml-auto flex items-center gap-2">
          {profile ? (
            <span className="hidden rounded-full bg-emerald-100 px-3 py-1.5 text-sm text-emerald-700 sm:inline">
              ✓ {firstName || "Resume loaded"}
              {Array.isArray(profile.skills) && profile.skills.length > 0 && ` · ${profile.skills.length} skills`}
            </span>
          ) : (
            <input
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              placeholder="Target role (optional)"
              className="hidden w-44 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-400 sm:block"
            />
          )}
          <label className="cursor-pointer rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-indigo-700">
            {uploading ? "Reading…" : profile ? "Change resume" : "Upload resume"}
            <input type="file" accept="application/pdf" className="hidden" onChange={onPickFile} disabled={uploading} />
          </label>
        </div>
      </div>

      {error && <div className="bg-rose-50 px-5 py-2 text-xs text-rose-600">{error}</div>}

      <div className="flex flex-1 flex-col overflow-hidden lg:flex-row">
        <section className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          <div className="mx-auto max-w-3xl">
            <div className="flex gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && loadJobs(query)}
                placeholder="Search roles, skills, keywords…"
                className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
              />
              <button onClick={() => loadJobs(query)} className="rounded-xl bg-slate-800 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-900">
                Search
              </button>
            </div>

            <p className="mt-3 mb-3 text-sm text-slate-500">
              {jobsLoading ? "Loading roles…" : sessionId ? `${jobs.length} roles · sorted by your match` : `${jobs.length} roles · upload your resume to see match scores`}
            </p>

            <div className="space-y-3 pb-6">
              {jobs.map((job) => (
                <JobCard key={job.id} job={job} active={activeJob?.id === job.id} onAsk={onAsk} />
              ))}
              {!jobsLoading && jobs.length === 0 && (
                <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400">
                  No roles found. Try a different search.
                </p>
              )}
            </div>
          </div>
        </section>

        <aside className="flex h-[60vh] flex-col border-t border-slate-200 lg:h-auto lg:w-[400px] lg:border-l lg:border-t-0">
          <ChatPanel
            messages={messages}
            streaming={streaming}
            onSend={(t) => send(t)}
            activeJob={activeJob}
            onClearContext={() => setActiveJob(null)}
            hasResume={!!sessionId}
          />
        </aside>
      </div>
    </div>
  );
}
