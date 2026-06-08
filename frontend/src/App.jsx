import { useState } from "react";
import CandidateApp from "./CandidateApp.jsx";
import RecruiterApp from "./RecruiterApp.jsx";

export default function App() {
  const [mode, setMode] = useState("candidate"); // "candidate" | "recruiter"

  return (
    <div className="flex h-full flex-col bg-slate-100">
      {/* App chrome: brand + mode toggle */}
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-5 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 text-sm font-bold text-white">
            CH
          </div>
          <div>
            <h1 className="font-semibold leading-tight text-slate-800">CareerHub</h1>
            <p className="text-xs text-slate-400">AI resume matching — for job seekers &amp; recruiters</p>
          </div>
        </div>

        <div className="ml-auto inline-flex rounded-lg bg-slate-100 p-1 text-sm">
          <button
            onClick={() => setMode("candidate")}
            className={`rounded-md px-3 py-1.5 font-medium transition ${
              mode === "candidate" ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            For Job Seekers
          </button>
          <button
            onClick={() => setMode("recruiter")}
            className={`rounded-md px-3 py-1.5 font-medium transition ${
              mode === "recruiter" ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            For Recruiters
          </button>
        </div>
      </header>

      {/* Both stay mounted so switching modes doesn't lose state. */}
      <div className="flex-1 overflow-hidden">
        <div className={`h-full ${mode === "candidate" ? "" : "hidden"}`}>
          <CandidateApp />
        </div>
        <div className={`h-full ${mode === "recruiter" ? "" : "hidden"}`}>
          <RecruiterApp />
        </div>
      </div>
    </div>
  );
}
