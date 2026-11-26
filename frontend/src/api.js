// Thin wrapper around the FastAPI backend. Every call throws an Error with a readable message.

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(`/api${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new Error('Cannot reach the backend. Is it running on port 8000?')
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = 'Please enter a topic of at least 5 characters.'
    } catch {
      /* keep default message */
    }
    throw new Error(message)
  }
  return res.json()
}

export const api = {
  health: () => request('/health'),
  startResearch: (topic) => request('/research', { method: 'POST', body: JSON.stringify({ topic }) }),
  jobStatus: (jobId) => request(`/jobs/${jobId}`),
  history: () => request('/research'),
  getResearch: (id) => request(`/research/${id}`),
  deleteResearch: (id) => request(`/research/${id}`, { method: 'DELETE' }),
  pdfUrl: (id) => `/api/research/${id}/pdf`,
}
