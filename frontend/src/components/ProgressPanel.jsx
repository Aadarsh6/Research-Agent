import { useEffect, useState } from 'react'

export default function ProgressPanel({ job, onRetry }) {
  const running = job.status === 'running'
  const failed = job.status === 'error'

  // Simple elapsed-time counter while the agent works.
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [running])

  return (
    <section className="rounded border border-slate-200 bg-white p-6">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-xl text-navy-800">
          {failed ? 'Research failed' : 'Agent is working…'}
        </h2>
        {running && <span className="text-xs text-slate-500">{seconds}s elapsed</span>}
      </div>
      <p className="mt-1 truncate text-sm text-slate-600">Topic: {job.topic}</p>

      <ol className="mt-5 space-y-3">
        {job.steps.map((step, i) => (
          <li key={i} className="flex items-start gap-3 text-sm">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-navy-700 text-xs text-white">
              ✓
            </span>
            <div>
              <p className="text-slate-800">{step.label}</p>
              {step.detail && <p className="text-xs text-slate-500">{step.detail}</p>}
            </div>
          </li>
        ))}

        {running && (
          <li className="flex items-center gap-3 text-sm text-slate-500">
            <span className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-slate-300 border-t-navy-700" />
            Working on the next step…
          </li>
        )}
      </ol>

      {failed && (
        <div className="mt-5 rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <p>{job.error || 'Something went wrong.'}</p>
          <p className="mt-1 text-xs">Check your API keys and internet connection, then try again.</p>
          <button
            onClick={onRetry}
            className="mt-3 rounded bg-navy-700 px-4 py-1.5 text-xs font-medium text-white hover:bg-navy-800"
          >
            Try again
          </button>
        </div>
      )}
    </section>
  )
}
