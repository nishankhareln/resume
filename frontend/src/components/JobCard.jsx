import { useState } from "react";

// Colour-code the match score so the eye finds the best fits instantly.
function MatchBadge({ score }) {
  if (score == null) {
    return (
      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-400">
        Upload resume for match
      </span>
    );
  }
  const pct = Math.round(score * 100);
  const tone =
    pct >= 70 ? "bg-emerald-100 text-emerald-700" : pct >= 55 ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500";
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>{pct}% match</span>;
}

export default function JobCard({ job, active, onAsk }) {
  const [open, setOpen] = useState(false);
  const meta = [job.company, job.location].filter(Boolean).join(" · ");

  return (
    <div
      className={`rounded-2xl border bg-white p-4 shadow-sm transition ${
        active ? "border-indigo-400 ring-2 ring-indigo-100" : "border-slate-200 hover:border-indigo-200"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold text-slate-800">{job.title}</h3>
          <p className="mt-0.5 text-sm text-slate-500">
            {meta || "Company not listed"}
            {job.is_remote && (
              <span className="ml-2 rounded bg-sky-50 px-1.5 py-0.5 text-xs font-medium text-sky-600">Remote</span>
            )}
          </p>
        </div>
        <MatchBadge score={job.match_score} />
      </div>

      {job.description && (
        <p className={`mt-2 text-sm leading-relaxed text-slate-600 ${open ? "" : "line-clamp-3"}`}>
          {job.description}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          onClick={() => onAsk(job)}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-indigo-700"
        >
          Ask NK about this
        </button>
        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
          >
            Apply ↗
          </a>
        )}
        {job.description && job.description.length > 180 && (
          <button onClick={() => setOpen((o) => !o)} className="ml-auto text-sm text-indigo-600 hover:underline">
            {open ? "Show less" : "Show more"}
          </button>
        )}
      </div>
    </div>
  );
}
