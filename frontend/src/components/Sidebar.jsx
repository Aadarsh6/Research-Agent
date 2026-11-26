export default function Sidebar({ items, activeId, onSelect, onDelete, onNew, disabled }) {
  return (
    <aside className="w-full shrink-0 md:w-64">
      <button
        onClick={onNew}
        disabled={disabled}
        className="mb-4 w-full rounded bg-navy-700 px-4 py-2 text-sm font-medium text-white transition hover:bg-navy-800 disabled:cursor-not-allowed disabled:opacity-50"
      >
        + New research
      </button>

      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">History</h2>

      {items.length === 0 ? (
        <p className="text-sm text-slate-500">Past research will appear here.</p>
      ) : (
        <ul className="max-h-[60vh] space-y-1 overflow-y-auto">
          {items.map((item) => (
            <li
              key={item.id}
              className={`group flex items-start justify-between rounded border px-3 py-2 text-sm ${
                item.id === activeId
                  ? 'border-navy-600 bg-white'
                  : 'border-transparent hover:border-slate-200 hover:bg-white'
              }`}
            >
              <button
                onClick={() => onSelect(item.id)}
                disabled={disabled}
                className="min-w-0 flex-1 text-left disabled:cursor-not-allowed"
              >
                <span className="block truncate text-slate-800">{item.topic}</span>
                <span className="block text-xs text-slate-500">{item.created_at.slice(0, 10)}</span>
              </button>
              <button
                onClick={() => {
                  if (window.confirm('Delete this research from history?')) onDelete(item.id)
                }}
                className="ml-2 text-slate-400 opacity-0 transition hover:text-red-600 group-hover:opacity-100"
                aria-label="Delete"
                title="Delete"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
