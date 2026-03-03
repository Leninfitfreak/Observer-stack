const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:18081'

export async function fetchProblems(filters = {}) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v) })
  const response = await fetch(`${API_BASE}/api/problems?${params.toString()}`)
  if (!response.ok) throw new Error('Failed to load problems')
  return response.json()
}

export async function fetchProblem(problemId) {
  const response = await fetch(`${API_BASE}/api/problems/${problemId}`)
  if (!response.ok) throw new Error('Failed to load problem details')
  return response.json()
}
