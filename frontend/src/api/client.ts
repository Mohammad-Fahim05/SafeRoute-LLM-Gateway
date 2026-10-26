import type {
  CacheTelemetry,
  DatabaseOverview,
  GatewayConfig,
  HealthSummary,
  OverviewTelemetry,
  ProvidersStatus,
  RequestDetail,
  RequestListResponse,
  TableRecordsResponse,
} from '../types';

const API_BASE = ''; // Proxied by Vite dev server or served from same origin

export function getStoredApiKey(): string {
  return sessionStorage.getItem('saferoute_api_key') || localStorage.getItem('saferoute_api_key') || '';
}

export function setStoredApiKey(key: string, persist = false): void {
  const cleanKey = key.trim();
  sessionStorage.setItem('saferoute_api_key', cleanKey);
  if (persist) {
    localStorage.setItem('saferoute_api_key', cleanKey);
  } else {
    localStorage.removeItem('saferoute_api_key');
  }
}

export function clearStoredApiKey(): void {
  sessionStorage.removeItem('saferoute_api_key');
  localStorage.removeItem('saferoute_api_key');
}

function formatAuthHeader(apiKey: string): string {
  const trimmed = apiKey.trim();
  return trimmed.toLowerCase().startsWith('bearer ') ? trimmed : `Bearer ${trimmed}`;
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const apiKey = getStoredApiKey();
  const headers = new Headers(options.headers || {});

  if (apiKey && !headers.has('Authorization')) {
    headers.set('Authorization', formatAuthHeader(apiKey));
  }
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorMessage = `HTTP Error ${response.status}: ${response.statusText}`;
    try {
      const errJson = await response.json();
      if (errJson.error && errJson.error.message) {
        errorMessage = errJson.error.message;
      } else if (errJson.detail) {
        errorMessage = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // Non-JSON error body
    }
    const err = new Error(errorMessage) as any;
    err.status = response.status;
    throw err;
  }

  return response.json();
}

export const api = {
  // Auth
  getAuthStatus: () => request<{ auth_enabled: boolean; key_prefix: string; registered_clients_count: number }>('/api/management/auth/status'),
  verifyKey: (key: string) => request<{ valid: boolean; client_id?: string; role?: string; is_admin?: boolean; error?: string }>('/api/management/auth/verify', {
    method: 'POST',
    body: JSON.stringify({ api_key: key }),
  }),

  // Telemetry & Requests
  getOverview: () => request<OverviewTelemetry>('/api/management/overview'),
  getRequests: (params: Record<string, any>) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') {
        query.append(k, String(v));
      }
    });
    return request<RequestListResponse>(`/api/management/requests?${query.toString()}`);
  },
  getRequestDetail: (id: string) => request<RequestDetail>(`/api/management/requests/${id}`),

  // Database
  getDatabaseOverview: () => request<DatabaseOverview>('/api/management/database/overview'),
  getTableRecords: (tableName: string, page = 1, pageSize = 20) =>
    request<TableRecordsResponse>(`/api/management/database/tables/${tableName}/records?page=${page}&page_size=${pageSize}`),

  // Cache & Redis
  getCacheTelemetry: () => request<CacheTelemetry>('/api/management/cache'),

  // Providers & Routing
  getProvidersStatus: () => request<ProvidersStatus>('/api/management/providers'),

  // Health & Config
  getHealthSummary: () => request<HealthSummary>('/api/management/health/summary'),
  getGatewayConfig: () => request<GatewayConfig>('/api/management/config'),
  getRawMetrics: async () => {
    const apiKey = getStoredApiKey();
    const headers = new Headers();
    if (apiKey) headers.set('Authorization', formatAuthHeader(apiKey));
    const resp = await fetch(`${API_BASE}/metrics`, { headers });
    if (!resp.ok) throw new Error(`Metrics endpoint failed: ${resp.status}`);
    return resp.text();
  },
  exportUsageCsv: async () => {
    const apiKey = getStoredApiKey();
    const headers = new Headers();
    if (apiKey) headers.set('Authorization', formatAuthHeader(apiKey));
    const resp = await fetch(`${API_BASE}/v1/usage/export`, { headers });
    if (!resp.ok) throw new Error(`Export failed: ${resp.status}`);
    return resp.blob();
  },


  // LLM Playground Chat Completion (with real streaming support)
  sendChatCompletion: async (
    payload: {
      model: string;
      messages: Array<{ role: string; content: string }>;
      temperature?: number;
      max_tokens?: number;
      stream?: boolean;
    },
    onChunk?: (delta: string) => void,
    signal?: AbortSignal
  ) => {
    const apiKey = getStoredApiKey();
    const headers = new Headers({
      'Content-Type': 'application/json',
    });
    if (apiKey) headers.set('Authorization', formatAuthHeader(apiKey));

    const startTime = performance.now();
    const reqBody: Record<string, any> = {
      model: payload.model,
      messages: payload.messages,
      stream: !!payload.stream,
    };
    if (payload.temperature !== undefined) reqBody.temperature = payload.temperature;
    if (payload.max_tokens !== undefined) reqBody.max_completion_tokens = payload.max_tokens;

    const resp = await fetch(`${API_BASE}/v1/chat/completions`, {
      method: 'POST',
      headers,
      body: JSON.stringify(reqBody),
      signal,
    });

    if (!resp.ok) {
      let msg = `Request failed with status ${resp.status}`;
      try {
        const errJson = await resp.json();
        if (errJson.error?.message) msg = errJson.error.message;
      } catch {}
      throw new Error(msg);
    }

    const durationMs = Math.round(performance.now() - startTime);
    const requestId = resp.headers.get('X-Request-ID') || 'unknown';
    const cacheHeader = resp.headers.get('X-Cache') || 'UNKNOWN';
    const servingProvider = resp.headers.get('X-Serving-Provider') || 'ollama';
    const servingModel = resp.headers.get('X-Serving-Model') || payload.model;

    if (payload.stream && resp.body) {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let fullContent = '';
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith(':')) continue;
          if (trimmed === 'data: [DONE]') continue;

          if (trimmed.startsWith('data: ')) {
            try {
              const parsed = JSON.parse(trimmed.slice(6));
              const deltaText = parsed.choices?.[0]?.delta?.content || '';
              if (deltaText) {
                fullContent += deltaText;
                if (onChunk) onChunk(deltaText);
              }
            } catch {
              // Ignore partial JSON chunks
            }
          }
        }
      }

      return {
        id: requestId,
        content: fullContent,
        model: servingModel,
        provider: servingProvider,
        durationMs,
        cacheStatus: cacheHeader,
        stream: true,
      };
    } else {
      const data = await resp.json();
      const content = data.choices?.[0]?.message?.content || '';
      return {
        id: data.id || requestId,
        content,
        model: data.model || servingModel,
        provider: servingProvider,
        durationMs,
        cacheStatus: cacheHeader,
        usage: data.usage,
        stream: false,
      };
    }
  },
};
