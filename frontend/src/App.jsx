import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import Sidebar from './components/Sidebar'
import TopicForm from './components/TopicForm'
import ProgressPanel from './components/ProgressPanel'
import ReportView from './components/ReportView'
import ToolStatus from './components/ToolStatus'

export default function App() {
  // ─────────────────────────────────────────────────────────────
  // STATE + LOGIC — unchanged from the original. Do not edit.
  // ─────────────────────────────────────────────────────────────
  const [health, setHealth] = useState(null)
  const [history, setHistory] = useState([])
  const [active, setActive] = useState(null) // { id, topic, report }
  const [job, setJob] = useState(null) // { id, status, steps, error, topic }
  const [formError, setFormError] = useState('')
  const [loadingReport, setLoadingReport] = useState(false)
  const pollRef = useRef(null)

  const refreshHistory = useCallback(async () => {
    try {
      setHistory(await api.history())
    } catch {
      /* sidebar simply stays empty */
    }
  }, [])

  const stopPolling = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = null
  }

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ offline: true }))
    refreshHistory()
    return stopPolling
  }, [refreshHistory])

  const openReport = async (id) => {
    setLoadingReport(true)
    setFormError('')
    try {
      const record = await api.getResearch(id)
      setActive(record)
    } catch (err) {
      setFormError(err.message)
    } finally {
      setLoadingReport(false)
    }
  }

  const startResearch = async (topic) => {
    setFormError('')
    setActive(null)
    try {
      const { job_id } = await api.startResearch(topic)
      setJob({ id: job_id, status: 'running', steps: [], error: '', topic })

      stopPolling()
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.jobStatus(job_id)
          setJob({ id: job_id, ...status })
          if (status.status === 'done') {
            stopPolling()
            await openReport(status.result_id)
            setJob(null)
            refreshHistory()
          } else if (status.status === 'error') {
            stopPolling()
          }
        } catch (err) {
          stopPolling()
          setJob({ id: job_id, status: 'error', steps: [], error: err.message, topic })
        }
      }, 1500)
    } catch (err) {
      setFormError(err.message)
    }
  }

  const newResearch = () => {
    stopPolling()
    setJob(null)
    setActive(null)
    setFormError('')
  }

  const selectHistory = (id) => {
    stopPolling()
    setJob(null)
    openReport(id)
  }

  const removeHistory = async (id) => {
    try {
      await api.deleteResearch(id)
      if (active?.id === id) setActive(null)
      refreshHistory()
    } catch (err) {
      setFormError(err.message)
    }
  }

  const running = job?.status === 'running'
  const keysMissing = health && !health.offline && !health.llm_ready

  // ─────────────────────────────────────────────────────────────
  // UI-only state + derived values (never touch the logic above)
  // ─────────────────────────────────────────────────────────────
  const [historyOpen, setHistoryOpen] = useState(false) // mobile history drawer only

  const busy = Boolean(job) && job.status !== 'error'
  const hasReport = Boolean(active) && !job
  const stage = busy ? 'running' : hasReport ? 'done' : 'idle'
  const stageIndex = busy ? detectStage(job) : -1

  const hero = job?.status === 'error'
    ? { title: 'The investigation stopped.', body: 'Review the details below, then start again.' }
    : busy
      ? { title: 'Investigation under way.', body: 'Keep this tab open. The report opens automatically when it is ready.' }
      : hasReport
        ? { title: active.topic, body: null }
        : {
            title: 'Research that shows its sources.',
            body: 'Enter a topic. The agent plans the inquiry, searches the web, analyses what it finds and writes a report with references you can check.',
          }

  const handleSelect = (id) => {
    setHistoryOpen(false)
    selectHistory(id)
  }
  const handleNew = () => {
    setHistoryOpen(false)
    newResearch()
  }

  // ─────────────────────────────────────────────────────────────
  // UI
  // ─────────────────────────────────────────────────────────────
  return (
    <div className="ra-root flex min-h-screen flex-col bg-[#f3f5f8] text-slate-800 antialiased selection:bg-[#f2a93b]/40">
      <GlobalStyles />

      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:text-[#0a1628]"
      >
        Skip to content
      </a>

      {/* ── Top bar: brand, status, primary action ─────────── */}
      <header className="ra-dark sticky top-0 z-30 bg-[#0a1628] text-white">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            <Mark />
            <span className="ra-display truncate text-base font-medium sm:text-lg">AI Research Agent</span>
          </div>

          <div className="flex items-center gap-3 sm:gap-4">
            <StatusChip health={health} keysMissing={keysMissing} busy={busy} hasReport={hasReport} />
            {(active || job) && (
              <button
                type="button"
                onClick={newResearch}
                disabled={running}
                className="rounded-md border border-white/25 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:border-[#f2a93b] hover:text-[#f2a93b] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-white/25 disabled:hover:text-white"
              >
                New research
              </button>
            )}
          </div>
        </div>
        {running && (
          <div className="absolute inset-x-0 bottom-0 h-[2px] overflow-hidden bg-white/10" aria-hidden="true">
            <div className="ra-sweep h-full w-1/4 bg-[#f2a93b]" />
          </div>
        )}
      </header>

      {/* ── Body ────────────────────────────────────────────── */}
      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-5 px-4 py-6 sm:px-6 md:grid md:grid-cols-[15rem_minmax(0,1fr)] md:items-start md:gap-8 md:py-8">
        {/* History: drawer on mobile, fixed column on md+ */}
        <aside className="md:sticky md:top-20">
          <button
            type="button"
            onClick={() => setHistoryOpen((o) => !o)}
            aria-expanded={historyOpen}
            aria-controls="history-panel"
            className="flex w-full items-center justify-between rounded-lg bg-white px-4 py-2.5 text-sm font-medium text-slate-700 ring-1 ring-slate-900/10 md:hidden"
          >
            <span>
              Past research <span className="ml-1 tabular-nums text-slate-400">{history.length}</span>
            </span>
            <svg
              viewBox="0 0 20 20"
              className={`h-4 w-4 text-slate-400 transition-transform ${historyOpen ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M5 8l5 5 5-5" />
            </svg>
          </button>

          <div id="history-panel" className={`${historyOpen ? 'mt-3 block' : 'hidden'} md:mt-0 md:block`}>
            <Sheet className="max-h-[60vh] overflow-y-auto md:max-h-[calc(100vh-7rem)] [&>*:only-child]:!w-full">
              <Sidebar
                items={history}
                activeId={active?.id}
                onSelect={handleSelect}
                onDelete={removeHistory}
                onNew={handleNew}
                disabled={running}
              />
            </Sheet>
          </div>
        </aside>

        <main id="main" className="min-w-0 space-y-5" aria-busy={running || loadingReport}>
          {/* Heading */}
          <div>
            <h1
              key={hero.title}
              className={`ra-display ra-rise font-medium tracking-[-0.02em] text-[#0a1628] ${
                hasReport
                  ? 'line-clamp-2 text-2xl leading-tight sm:text-3xl'
                  : 'text-3xl leading-[1.1] sm:text-4xl'
              }`}
            >
              {hero.title}
            </h1>
            {hero.body && <p className="mt-3 max-w-xl text-[15px] leading-7 text-slate-600">{hero.body}</p>}
          </div>

          {/* Pipeline: only while it matters */}
          {!hasReport && <Pipeline stage={stage} current={stageIndex} />}

          {health?.offline && (
            <Notice tone="error" title="Backend unreachable">
              Start it with <code>uvicorn main:app --reload</code> in the <code>backend</code> folder, then
              refresh this page.
            </Notice>
          )}
          {keysMissing && (
            <Notice tone="error" title="No LLM API key found">
              Add <code>GOOGLE_API_KEY</code> or <code>GROQ_API_KEY</code> to <code>backend/.env</code> and
              restart the backend.
            </Notice>
          )}

          {formError && (
            <Notice tone="error" title="Request failed">
              {formError}
            </Notice>
          )}

          {job && (
            <Sheet>
              <ProgressPanel job={job} onRetry={newResearch} />
            </Sheet>
          )}

          {!active && (
            <Sheet>
              <TopicForm onSubmit={startResearch} disabled={running || health?.offline || keysMissing} />
            </Sheet>
          )}

          {!active && !job && <ToolStatus tools={health?.tools} />}

          {loadingReport && (
            <Sheet>
              <div role="status" aria-live="polite" className="space-y-3 p-5 sm:p-6">
                <span className="sr-only">Loading report…</span>
                <div className="h-5 w-2/5 animate-pulse rounded bg-slate-200" />
                <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
                <div className="h-3 w-11/12 animate-pulse rounded bg-slate-100" />
                <div className="h-3 w-4/5 animate-pulse rounded bg-slate-100" />
              </div>
            </Sheet>
          )}

          {active && !job && (
            <Sheet>
              <ReportView record={active} pdfUrl={api.pdfUrl(active.id)} />
            </Sheet>
          )}

          <p className="pt-2 text-xs leading-relaxed text-slate-500">
            Reports are generated from retrieved web sources. Verify important facts using the references.
          </p>
        </main>
      </div>
    </div>
  )
}

/* ───────────────────────── UI pieces ───────────────────────── */

const STAGES = [
  { label: 'Plan', hint: 'Scope the topic' },
  { label: 'Search', hint: 'Gather sources' },
  { label: 'Analyse', hint: 'Weigh the evidence' },
  { label: 'Report', hint: 'Write it up with references' },
]

// Best-effort guess of the current stage from the step text the backend sends.
// If nothing matches it returns -1 and the pipeline just shows a general "working" state.
const STAGE_PATTERNS = [
  /\bplan/,
  /\b(search|fetch|retriev|gather|crawl|scrap)/,
  /\b(analy|summar|synthes|evaluat|extract)/,
  /\b(report|writ|draft|compil|final)/,
]

function detectStage(job) {
  const steps = Array.isArray(job?.steps) ? job.steps : []
  let best = -1
  for (const step of steps) {
    let text = ''
    try {
      text = (typeof step === 'string' ? step : JSON.stringify(step)).toLowerCase()
    } catch {
      continue
    }
    let first = -1
    let firstPos = Infinity
    STAGE_PATTERNS.forEach((re, i) => {
      const pos = text.search(re)
      if (pos !== -1 && pos < firstPos) {
        firstPos = pos
        first = i
      }
    })
    if (first > best) best = first
  }
  return best
}

// Compact stepper on a light surface. Hints show only on sm+ and only while idle.
function Pipeline({ stage, current }) {
  return (
    <ol
      className="grid grid-cols-4 gap-2 rounded-lg bg-white px-4 py-3.5 ring-1 ring-slate-900/10 sm:gap-4 sm:px-5"
      aria-label="Research pipeline"
    >
      {STAGES.map((s, i) => {
        let state = 'todo'
        if (stage === 'done') state = 'done'
        else if (stage === 'running') {
          if (current < 0) state = 'working'
          else if (i < current) state = 'done'
          else if (i === current) state = 'current'
        }

        const node =
          state === 'done' || state === 'working'
            ? 'bg-[#f2a93b]'
            : state === 'current'
              ? 'bg-[#f2a93b] ra-pulse'
              : 'border border-slate-300'
        const lit = state !== 'todo'

        return (
          <li key={s.label} className="min-w-0">
            <div className="flex items-center">
              <span
                className={`h-2.5 w-2.5 shrink-0 rounded-full ${node}`}
                style={state === 'working' ? { animation: `ra-blink 1.4s ease-in-out ${i * 0.3}s infinite` } : undefined}
                aria-hidden="true"
              />
              {i < STAGES.length - 1 && (
                <span className={`ml-2 h-px flex-1 sm:ml-3 ${state === 'done' ? 'bg-[#f2a93b]' : 'bg-slate-200'}`} aria-hidden="true" />
              )}
            </div>
            <p className={`mt-2 truncate text-[13px] font-medium ${lit ? 'text-[#0a1628]' : 'text-slate-500'}`}>{s.label}</p>
            {stage === 'idle' && <p className="mt-0.5 hidden text-xs leading-4 text-slate-400 sm:block">{s.hint}</p>}
          </li>
        )
      })}
    </ol>
  )
}

function StatusChip({ health, keysMissing, busy, hasReport }) {
  let dot = 'bg-amber-400 animate-pulse'
  let label = 'Connecting'
  if (health?.offline) {
    dot = 'bg-red-500'
    label = 'Backend offline'
  } else if (health) {
    dot = keysMissing ? 'bg-red-500' : 'bg-emerald-400'
    label = keysMissing ? 'No API key' : busy ? 'Researching' : hasReport ? 'Report ready' : 'Ready'
  }
  const provider = health && !health.offline && health.llm_provider

  return (
    <div className="flex items-center gap-2 text-xs text-slate-300" role="status">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      <span className="hidden sm:inline">{label}</span>
      {provider && <span className="hidden text-slate-400 md:inline">· {provider}</span>}
      <span className="sr-only sm:hidden">{label}</span>
    </div>
  )
}

// A white working surface. Gives every child component a reliable paper background
// and, when a child is a single card, removes its own border/shadow so there is no card-in-card look.
function Sheet({ children, className = '' }) {
  return (
    <div
      className={`rounded-lg bg-white shadow-sm ring-1 ring-slate-900/10 [&>*:only-child]:!rounded-[inherit] [&>*:only-child]:!border-0 [&>*:only-child]:!shadow-none ${className}`}
    >
      {children}
    </div>
  )
}

function Mark() {
  return (
    <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="3" stroke="#f2a93b" strokeWidth="1.5" />
      <path d="M8 11h16" stroke="#f2a93b" strokeWidth="2" strokeLinecap="round" />
      <path d="M8 16h12" stroke="#fff" strokeWidth="2" strokeLinecap="round" opacity="0.85" />
      <path d="M8 21h8" stroke="#fff" strokeWidth="2" strokeLinecap="round" opacity="0.55" />
    </svg>
  )
}

function Notice({ tone, title, children }) {
  const isError = tone === 'error'
  const styles = isError
    ? 'border-red-200 border-l-red-600 bg-white text-red-900'
    : 'border-slate-200 border-l-slate-400 bg-white text-slate-700'
  return (
    <div
      role={isError ? 'alert' : 'status'}
      className={`flex gap-3 rounded-md border border-l-[3px] px-4 py-3 text-sm leading-6 shadow-sm [&_code]:break-all [&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.82em] [&_code]:text-slate-800 ${styles}`}
    >
      <svg
        viewBox="0 0 20 20"
        className={`mt-0.5 h-5 w-5 shrink-0 ${isError ? 'text-red-600' : 'text-slate-400'}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="10" cy="10" r="7.5" />
        <path d="M10 6v4.5" />
        <path d="M10 13.5h.01" />
      </svg>
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        <div className={title ? 'mt-0.5' : ''}>{children}</div>
      </div>
    </div>
  )
}

function GlobalStyles() {
  return (
    <style>{`
      @import url('https://fonts.googleapis.com/css2?family=Spectral:wght@400;500;600&display=swap');

      .ra-display { font-family: 'Spectral', Georgia, 'Times New Roman', serif; }

      .ra-root :focus-visible { outline: 2px solid #0a1628; outline-offset: 2px; }
      .ra-dark :focus-visible { outline-color: #f2a93b; }

      @keyframes ra-sweep { from { transform: translateX(-100%); } to { transform: translateX(400%); } }
      @keyframes ra-blink { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
      @keyframes ra-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(242,169,59,.5); } 60% { box-shadow: 0 0 0 6px rgba(242,169,59,0); } }
      @keyframes ra-rise  { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

      .ra-sweep { animation: ra-sweep 1.6s linear infinite; }
      .ra-pulse { animation: ra-pulse 1.8s ease-out infinite; }
      .ra-rise  { animation: ra-rise .4s cubic-bezier(.2,.7,.2,1) both; }

      @media (prefers-reduced-motion: reduce) {
        .ra-sweep, .ra-pulse, .ra-rise { animation: none !important; }
      }
    `}</style>
  )
}