import ReactMarkdown from "react-markdown";

function UserAvatar() {
  return (
    <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-300 text-slate-600">
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
        <path d="M12 12a5 5 0 100-10 5 5 0 000 10zm0 2c-4.42 0-8 2.69-8 6v1h16v-1c0-3.31-3.58-6-8-6z" />
      </svg>
    </div>
  );
}

function AssistantAvatar() {
  return (
    <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 text-xs font-bold text-white shadow">
      NK
    </div>
  );
}

// Shown before the first token arrives, so it feels like NK is "typing".
function TypingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400" />
    </div>
  );
}

// Tailwind's preflight strips default list/heading styles, so we restore the
// few markdown elements the coach actually uses, with classes that match the UI.
const markdownComponents = {
  p: (props) => <p className="mb-2 leading-relaxed last:mb-0" {...props} />,
  ul: (props) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0" {...props} />,
  ol: (props) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0" {...props} />,
  li: (props) => <li className="leading-relaxed" {...props} />,
  strong: (props) => <strong className="font-semibold" {...props} />,
  em: (props) => <em className="italic" {...props} />,
  a: (props) => (
    <a className="text-indigo-600 underline underline-offset-2" target="_blank" rel="noreferrer" {...props} />
  ),
  code: (props) => <code className="rounded bg-slate-200 px-1 py-0.5 text-[0.85em]" {...props} />,
  h1: (props) => <h1 className="mb-2 text-base font-semibold" {...props} />,
  h2: (props) => <h2 className="mb-2 text-base font-semibold" {...props} />,
  h3: (props) => <h3 className="mb-1 font-semibold" {...props} />,
};

export default function Message({ role, content }) {
  const isUser = role === "user";
  return (
    <div className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      {isUser ? <UserAvatar /> : <AssistantAvatar />}
      <div
        className={`max-w-[82%] rounded-2xl px-4 py-2.5 shadow-sm ${
          isUser
            ? "rounded-tr-sm bg-indigo-600 text-white"
            : "rounded-tl-sm bg-white text-slate-800 ring-1 ring-slate-200"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{content}</p>
        ) : content ? (
          <div className="text-[15px]">
            <ReactMarkdown components={markdownComponents}>{content}</ReactMarkdown>
          </div>
        ) : (
          <TypingDots />
        )}
      </div>
    </div>
  );
}
