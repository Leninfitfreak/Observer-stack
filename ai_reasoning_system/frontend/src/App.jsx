import React, { useEffect, useMemo, useState } from 'react'
import { fetchProblem, fetchProblems } from './api'
import { FilterBar, ProblemDetails, ProblemList } from './components/ProblemUI'

function toLocalInput(date) {
  const d = new Date(date)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

export default function App() {
  const [filters, setFilters] = useState({ project_id: '', cluster: '', namespace: '', service: '', from: toLocalInput(Date.now() - 1000 * 60 * 60 * 24), to: toLocalInput(new Date()) })
  const [problems, setProblems] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')

  const queryFilters = useMemo(() => ({
    ...filters,
    from: filters.from ? new Date(filters.from).toISOString() : '',
    to: filters.to ? new Date(filters.to).toISOString() : '',
  }), [filters])

  async function loadProblems() {
    try {
      setError('')
      const rows = await fetchProblems(queryFilters)
      setProblems(rows)
      if (rows.length && !selectedId) {
        setSelectedId(rows[0].problem_id)
      }
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => { loadProblems() }, [])
  useEffect(() => {
    if (!selectedId) return
    fetchProblem(selectedId).then(setSelected).catch((err) => setError(err.message))
  }, [selectedId])

  return (
    <div className="min-h-screen px-4 py-6 lg:px-8">
      <div className="mx-auto max-w-[1700px]">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.28em] text-accent">AI Observer</div>
            <h1 className="mt-2 text-4xl font-semibold">Problems Intelligence Console</h1>
            <p className="mt-2 text-slate-400">Davis-style incident reasoning powered by ClickHouse telemetry, Go core orchestration, and Ollama Cloud analysis.</p>
          </div>
        </div>
        <FilterBar filters={filters} onChange={(k, v) => setFilters((s) => ({ ...s, [k]: v }))} onApply={loadProblems} />
        {error ? <div className="mt-4 rounded-xl border border-critical/40 bg-critical/10 px-4 py-3 text-sm text-critical">{error}</div> : null}
        <div className="mt-6 grid gap-6 xl:grid-cols-[420px,1fr]">
          <ProblemList problems={problems} selectedId={selectedId} onSelect={setSelectedId} />
          <ProblemDetails problem={selected} />
        </div>
      </div>
    </div>
  )
}
