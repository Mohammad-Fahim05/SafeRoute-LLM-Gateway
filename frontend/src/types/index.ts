export interface OverviewTelemetry {
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  success_rate: number;
  avg_duration_ms: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  p99_duration_ms: number;
  exact_cache_hits: number;
  semantic_cache_hits: number;
  total_cache_hits: number;
  cache_misses: number;
  cache_hit_rate: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  estimated_total_cost: number;
  provider_counts: Record<string, number>;
  model_counts: Record<string, number>;
  status_counts: Record<string, number>;
  timeline: Array<{
    date: string;
    total: number;
    success: number;
    failed: number;
    cache_hits: number;
    avg_duration: number;
  }>;
  recent_requests: Array<{
    request_id: string;
    client_id: string | null;
    created_at: string | null;
    model: string;
    provider: string;
    http_status: number;
    status: string;
    duration_ms: number;
    cache_status: string;
    stream: boolean;
    failover_occurred: boolean;
  }>;
}

export interface RequestRecordItem {
  id: number;
  request_id: string;
  client_id: string | null;
  created_at: string | null;
  model_requested: string;
  model_actual: string | null;
  provider: string;
  http_status: number;
  status: string;
  error_code: string | null;
  error_message: string | null;
  duration_ms: number;
  provider_latency_ms: number | null;
  cache_status: string;
  attempts_count: number;
  failover_occurred: boolean;
  stream: boolean;
  stream_status: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  usage_source: string;
  total_cost: number;
  currency: string;
  calculation_status: string;
}

export interface RequestListResponse {
  items: RequestRecordItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface FailoverAttempt {
  attempt?: number;
  provider?: string;
  model?: string;
  success?: boolean;
  latency_ms?: number;
  error_code?: string | null;
  error_message?: string | null;
  failure_category?: string | null;
  raw?: string;
}

export interface RequestDetail extends RequestRecordItem {
  attempts: FailoverAttempt[];
  token_usage_status: string;
  usage: {
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    usage_source: string;
    is_estimate: boolean;
    pricing_version: string | null;
    input_cost: number;
    output_cost: number;
    total_cost: number;
    currency: string;
    calculation_status: string;
  } | null;
  retention_notice: string;
}

export interface DatabaseTableColumn {
  cid: number;
  name: string;
  type: string;
  not_null: boolean;
  default_value: string | null;
  primary_key: boolean;
}

export interface DatabaseTableInfo {
  table_name: string;
  row_count: number;
  columns: DatabaseTableColumn[];
}

export interface DatabaseOverview {
  database_url: string;
  database_path: string;
  file_size_bytes: number;
  journal_mode: string;
  tables: DatabaseTableInfo[];
  read_only: boolean;
}

export interface TableRecordsResponse {
  table_name: string;
  columns: string[];
  records: Record<string, any>[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface CacheTelemetry {
  redis_connected: boolean;
  redis_ping_latency_ms: number | null;
  redis_url: string;
  exact_cache: {
    enabled: boolean;
    ttl_seconds: number;
    namespace: string;
    failure_policy: string;
    hits: number;
    misses: number;
  };
  semantic_cache: {
    enabled: boolean;
    threshold: number;
    ttl_seconds: number;
    embedding_provider: string;
    embedding_model: string;
    hits: number;
    misses: number;
  };
  total_cache_hits: number;
  total_cache_misses: number;
  total_bypasses: number;
  overall_hit_rate: number;
  streaming_replay_enabled: boolean;
}

export interface ModelCapability {
  model_id: string;
  provider: string;
  status: string;
  supports_text: boolean;
  supports_streaming: boolean;
  supports_tools: boolean;
  supports_streaming_tools: boolean;
  evidence_level: string;
  notes: string | null;
}

export interface ProvidersStatus {
  active_provider: string;
  ollama: {
    base_url: string;
    is_online: boolean;
    ping_latency_ms: number | null;
    pulled_models: string[];
  };
  mock: {
    name: string;
    is_online: boolean;
    status: string;
    notes: string;
  };
  allowed_models: string[];
  default_model: string;
  capabilities: ModelCapability[];
  failover: {
    enabled: boolean;
    max_attempts: number;
    fallback_models: Record<string, string[]>;
    allow_mock_fallback: boolean;
  };
}

export interface HealthSummary {
  status: 'healthy' | 'degraded' | 'unavailable';
  gateway: string;
  database: string;
  redis: string;
  ollama: string;
  app_env: string;
  server_time: string;
}

export interface GatewayConfig {
  app_env: string;
  log_level: string;
  active_provider: string;
  ollama_base_url: string;
  allowed_models: string[];
  max_request_size_bytes: number;
  provider_timeout_seconds: number;
  cache: {
    enabled: boolean;
    ttl_seconds: number;
    namespace: string;
    failure_policy: string;
    semantic_cache_enabled: boolean;
    semantic_cache_threshold: number;
  };
  rate_limiting: {
    enabled: boolean;
    requests: number;
    window_seconds: number;
    failure_policy: string;
  };
  guardrails: {
    enabled: boolean;
    input_enabled: boolean;
    output_enabled: boolean;
    max_text_length: number;
    rules_count: number;
  };
  failover: {
    enabled: boolean;
    max_attempts: number;
    timeout_budget_seconds: number;
  };
  metrics: {
    enabled: boolean;
    path: string;
    require_auth: boolean;
  };
}
