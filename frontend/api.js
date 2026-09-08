async function request(url, options = {}) {
  const response = await fetch(url, options);
  let body = null;
  try {
    body = await response.json();
  } catch {
    // Preserve the HTTP fallback when a non-JSON response is returned.
  }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    if (body?.detail) message = body.detail;
    const error = new Error(message);
    error.payload = body;
    throw error;
  }
  return body;
}

export const api = {
  status: () => request("/api/status"),
  schema: () => request("/api/schema"),
  upload: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/api/upload", { method: "POST", body });
  },
  board: (board, params) => request(`/api/data/${board}?${params}`),
  crfBook: (params) => request(`/api/crf-book?${params}`),
  checkConversion: (checkRowId) => request(`/api/checks/${checkRowId}/conversion`)
};

