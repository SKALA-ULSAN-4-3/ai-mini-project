// Vue 컴포넌트에서 import해 사용한다. 실제 인증은 BE 연결 시 적용한다.
export function createBidClient(baseUrl = 'http://localhost:8001') {
  async function request(path, body) {
    const response = await fetch(`${baseUrl}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      const failure = new Error(typeof error.detail === 'string' ? error.detail :
        error.detail?.message ?? `요청 실패: ${response.status}`);
      failure.runId = error.detail?.run_id;
      throw failure;
    }
    return response.json();
  }
  return {
    discover: (conditions) => request('/bid-runs', conditions),
    recommendations: (runId) => request(`/bid-runs/${runId}/recommendations`),
    refreshRecommendations: (runId) => request(`/bid-runs/${runId}/recommendations`, {}),
    select: (runId, bidIds) => request(`/bid-runs/${runId}/selection`, { bid_ids: bidIds }),
    downloadUrl: (path) => `${baseUrl}${path}`,
  };
}
