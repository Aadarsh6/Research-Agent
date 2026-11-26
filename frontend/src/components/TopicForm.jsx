import { useState } from 'react'

const EXAMPLES = [
  'Impact of Artificial Intelligence on Education',
  'Renewable energy adoption in India',
  'Future of electric vehicles',
]

export default function TopicForm({ onSubmit, disabled }) {
  const [topic, setTopic] = useState('')
  const tooShort = topic.trim().length < 5

  const submit = (e) => {
    e.preventDefault()
    if (!tooShort && !disabled) onSubmit(topic.trim())
  }

  return (
    <section className="rounded border border-slate-200 bg-white p-6">
      <h2 className="font-serif text-2xl text-navy-800">New research</h2>
      <p className="mt-1 text-sm text-slate-600">
        Enter a topic. The agent will plan the research, search the web and Wikipedia, draw charts and
        diagrams, and produce a cited report you can download as a PDF.
      </p>

      <form onSubmit={submit} className="mt-5 flex flex-col gap-3 sm:flex-row">
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          maxLength={300}
          placeholder="e.g. Impact of Artificial Intelligence on Education"
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm outline-none focus:border-navy-600 focus:ring-1 focus:ring-navy-600"
        />
        <button
          type="submit"
          disabled={tooShort || disabled}
          className="rounded bg-navy-700 px-6 py-2 text-sm font-medium text-white transition hover:bg-navy-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Start research
        </button>
      </form>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-500">Try:</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => setTopic(ex)}
            className="rounded border border-slate-200 px-2 py-1 text-slate-600 hover:border-navy-600 hover:text-navy-700"
          >
            {ex}
          </button>
        ))}
      </div>
    </section>
  )
}
