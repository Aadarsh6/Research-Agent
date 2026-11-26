const DOT = {
  ready: 'bg-emerald-500',
  starting: 'bg-amber-400 animate-pulse',
  failed: 'bg-red-500',
  disabled: 'bg-slate-300',
  stopped: 'bg-slate-300',
}

// Small panel showing which tools (MCP servers etc.) are active. Optional tools may be off.
export default function ToolStatus({ tools }) {
  if (!tools?.length) return null
  return (
    <details className="rounded border border-slate-200 bg-white px-4 py-2 text-sm">
      <summary className="cursor-pointer text-slate-600">
        Tools: {tools.filter((t) => t.state === 'ready').length} of {tools.length} active
      </summary>
      <ul className="mt-2 space-y-1">
        {tools.map((t) => (
          <li key={t.name} className="flex items-start gap-2 text-xs">
            <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${DOT[t.state] || 'bg-slate-300'}`} />
            <span className="text-slate-800">{t.name}</span>
            <span className="text-slate-500">- {t.detail}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}
