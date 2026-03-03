import React from 'react'
import { severityClasses } from '../utils'

export function FilterBar({ filters, onChange, onApply }) {
  return (
    <div className="grid gap-3 rounded-2xl border border-line bg-panel/85 p-4 shadow-glow lg:grid-cols-6">
      {['project_id', 'cluster', 'namespace', 'service'].map((field) => (
        <input key={field} value={filters[field] || ''} onChange={(e) => onChange(field, e.target.value)} placeholder={field.replace('_', ' ')} className="rounded-xl border border-line bg-slatebg/70 px-4 py-3 text-sm outline-none focus:border-accent" />
      ))}
      <input type="datetime-local" value={filters.from || ''} onChange={(e) => onChange('from', e.target.value)} className="rounded-xl border border-line bg-slatebg/70 px-4 py-3 text-sm outline-none focus:border-accent" />
      <div className="flex gap-3">
        <input type="datetime-local" value={filters.to || ''} onChange={(e) => onChange('to', e.target.value)} className="min-w-0 flex-1 rounded-xl border border-line bg-slatebg/70 px-4 py-3 text-sm outline-none focus:border-accent" />
        <button onClick={onApply} className="rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-slatebg transition hover:scale-[1.02]">Apply</button>
      </div>
    </div>
  )
}

export function ProblemList({ problems, selectedId, onSelect }) {
  return (
    <div className="rounded-2xl border border-line bg-panel/85 p-3 shadow-glow">
      <div className="mb-3 flex items-center justify-between px-2">
        <h2 className="text-lg font-semibold">Problems</h2>
        <span className="text-xs text-slate-400">{problems.length} items</span>
      </div>
      <div className="space-y-2 overflow-y-auto max-h-[70vh] pr-1">
        {problems.map((problem) => (
          <button key={problem.problem_id} onClick={() => onSelect(problem.problem_id)} className={`w-full rounded-xl border p-4 text-left transition hover:border-accent ${selectedId === problem.problem_id ? 'border-accent bg-accent/5' : 'border-line bg-slatebg/40'}`}>
            <div className="mb-2 flex items-center justify-between gap-3">
              <span className="truncate text-sm font-semibold">{problem.service}</span>
              <span className={`rounded-full border px-2 py-1 text-[11px] uppercase tracking-wide ${severityClasses(problem.severity)}`}>{problem.severity}</span>
            </div>
            <div className="text-xs text-slate-400">{problem.cluster} / {problem.namespace}</div>
            <div className="mt-2 line-clamp-2 text-sm text-slate-200">{problem.impact_assessment}</div>
            <div className="mt-3 text-xs text-slate-500">Confidence {Math.round((problem.confidence || 0) * 100)}%</div>
          </button>
        ))}
      </div>
    </div>
  )
}

export function ProblemDetails({ problem }) {
  if (!problem) return <div className="rounded-2xl border border-line bg-panel/85 p-8 text-slate-400 shadow-glow">Select a problem to inspect Davis-style reasoning.</div>
  return (
    <div className="rounded-2xl border border-line bg-panel/85 p-6 shadow-glow">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-semibold">{problem.service}</h2>
        <span className={`rounded-full border px-3 py-1 text-xs uppercase tracking-[0.18em] ${severityClasses(problem.severity)}`}>{problem.severity}</span>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Info label="Project" value={problem.project_id} />
        <Info label="Cluster" value={problem.cluster} />
        <Info label="Namespace" value={problem.namespace} />
        <Info label="Root Cause Entity" value={problem.root_cause_entity} />
        <Info label="Start Time" value={new Date(problem.start_time).toLocaleString()} />
        <Info label="Confidence" value={`${Math.round((problem.confidence || 0) * 100)}%`} />
      </div>
      <Section title="Impact Assessment" content={problem.impact_assessment} />
      <Section title="Causal Chain" list={problem.causal_chain} />
      <Section title="Correlated Signals" list={problem.correlated_signals} />
      <Section title="Recommended Actions" list={problem.recommended_actions} />
      <Section title="Metrics Summary" content={JSON.stringify(problem.metrics_summary, null, 2)} mono />
    </div>
  )
}

function Info({ label, value }) {
  return <div className="rounded-xl border border-line bg-slatebg/45 p-4"><div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div><div className="mt-2 text-sm text-slate-100">{value || 'n/a'}</div></div>
}
function Section({ title, content, list, mono }) {
  return <div className="mt-5 rounded-xl border border-line bg-slatebg/45 p-4"><div className="mb-3 text-xs uppercase tracking-[0.18em] text-slate-500">{title}</div>{list ? <ul className="space-y-2 text-sm text-slate-100">{list.map((item) => <li key={item}>• {item}</li>)}</ul> : <pre className={`${mono ? 'font-mono text-xs whitespace-pre-wrap' : 'text-sm'} text-slate-100`}>{content}</pre>}</div>
}
