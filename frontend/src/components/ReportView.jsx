// Turns "[1]" / "[2, 5]" markers into links that jump to the reference list.
function Cited({ text }) {
  const parts = String(text ?? '').split(/(\[\d+(?:\s*,\s*\d+)*\])/g)
  return parts.map((part, i) => {
    const m = part.match(/^\[(\d+(?:\s*,\s*\d+)*)\]$/)
    if (!m) return part
    return (
      <sup key={i} className="mx-0.5 text-xs">
        {m[1].split(/\s*,\s*/).map((n, j) => (
          <a key={j} href={`#ref-${n}`} className="text-blue-700 hover:underline">
            [{n}]
          </a>
        ))}
      </sup>
    )
  })
}

function Section({ number, title, children }) {
  return (
    <section className="mt-8">
      <h3 className="border-b border-slate-200 pb-1 font-serif text-lg text-navy-800">
        {number}. {title}
      </h3>
      <div className="mt-3 space-y-3 text-[15px] leading-7 text-slate-700">{children}</div>
    </section>
  )
}

function Paragraphs({ text }) {
  const parts = String(text || '')
    .split(/\n\s*\n/)
    .filter((p) => p.trim())
  if (parts.length === 0) return <p>—</p>
  return parts.map((p, i) => <p key={i}><Cited text={p} /></p>)
}

function Bullets({ items }) {
  if (!items || items.length === 0) return <p className="text-slate-500">No items available.</p>
  return (
    <ul className="list-disc space-y-1 pl-5">
      {items.map((item, i) => (
        <li key={i}><Cited text={item} /></li>
      ))}
    </ul>
  )
}

export default function ReportView({ record, pdfUrl }) {
  const report = record.report
  const meta = report.meta || {}
  const visuals = report.visuals || []
  const references = report.references || []

  // Number the sections dynamically so numbering always matches the PDF.
  let n = 0
  const next = () => ++n

  return (
    <article className="rounded border border-slate-200 bg-white p-8">
      <div className="flex flex-col gap-4 border-b border-slate-200 pb-5 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-serif text-3xl leading-tight text-navy-800">{report.title}</h2>
          <p className="mt-2 text-xs text-slate-500">
            Generated {meta.generated_at || record.created_at} · {meta.num_findings ?? '–'} facts from{' '}
            {meta.num_sources ?? references.length} sources
            {meta.citation_stats?.statements_cited != null &&
              ` · ${meta.citation_stats.statements_cited} cited statements` +
                (meta.citation_stats.statements_removed
                  ? ` (${meta.citation_stats.statements_removed} unsupported removed)`
                  : '')}
          </p>
        </div>
        <a
          href={pdfUrl}
          className="shrink-0 rounded bg-navy-700 px-4 py-2 text-center text-sm font-medium text-white transition hover:bg-navy-800"
        >
          Download PDF
        </a>
      </div>

      {meta.research_question && (
        <p className="mt-5 rounded bg-slate-50 px-4 py-3 text-sm text-slate-700">
          <span className="font-semibold text-navy-700">Research question: </span>
          {meta.research_question}
        </p>
      )}

      {report.executive_summary && (
        <Section number={next()} title="Executive Summary">
          <Paragraphs text={report.executive_summary} />
        </Section>
      )}

      <Section number={next()} title="Introduction">
        <Paragraphs text={report.introduction} />
      </Section>

      <Section number={next()} title="Research Questions">
        <Bullets items={report.research_questions} />
      </Section>

      <Section number={next()} title="Key Findings">
        <Bullets items={report.key_findings} />
      </Section>

      {visuals.length > 0 && (
        <Section number={next()} title="Data & Diagrams">
          <div className="space-y-6">
            {visuals.map((v, i) => (
              <figure key={i} className="rounded border border-slate-200 p-3">
                <img src={v.image} alt={v.title} className="mx-auto max-h-[420px] w-auto" />
                <figcaption className="mt-2 text-center text-xs italic text-slate-500">
                  Figure {i + 1}: {v.title}. {v.caption}
                </figcaption>
              </figure>
            ))}
          </div>
        </Section>
      )}

      <Section number={next()} title="Detailed Analysis">
        <Paragraphs text={report.detailed_analysis} />
      </Section>

      <Section number={next()} title="Advantages & Opportunities">
        <Bullets items={report.advantages} />
      </Section>

      <Section number={next()} title="Challenges & Limitations">
        <Bullets items={report.challenges} />
      </Section>

      <Section number={next()} title="Conclusion">
        <Paragraphs text={report.conclusion} />
      </Section>

      <Section number={next()} title="References">
        {references.length === 0 ? (
          <p className="text-slate-500">No sources were available for this report.</p>
        ) : (
          <ol className="space-y-3 text-sm">
            {references.map((ref, i) => {
              const authors = (ref.authors || []).length > 3
                ? `${ref.authors.slice(0, 3).join(', ')} et al.`
                : (ref.authors || []).join(', ')
              const link = ref.doi ? `https://doi.org/${ref.doi}` : ref.url
              return (
                <li key={i} id={`ref-${i + 1}`} className="scroll-mt-4 break-words">
                  [{i + 1}] {authors && `${authors} `}({ref.published || 'n.d.'}).{' '}
                  <span className="font-medium">{ref.title || ref.url}.</span>
                  {ref.venue && ` ${ref.venue}.`}
                  {ref.doi && ` DOI: ${ref.doi}.`}
                  {ref.accessed && ` Accessed ${ref.accessed}.`}{' '}
                  <a href={link} target="_blank" rel="noreferrer"
                     className="text-blue-700 underline underline-offset-2 hover:text-blue-900">
                    {link}
                  </a>
                </li>
              )
            })}
          </ol>
        )}
      </Section>
    </article>
  )
}
