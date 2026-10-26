import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeader } from '../components/ui/PageHeader';
import { MetricCard } from '../components/ui/MetricCard';
import { SectionCard } from '../components/ui/SectionCard';
import { Button } from '../components/ui/Button';
import {
  Database,
  Zap,
  Layers,
  ShieldAlert,
  CheckCircle2,
  RefreshCw,
  Info,
  KeyRound,
} from 'lucide-react';
import type { CacheTelemetry } from '../types';

export const Cache: React.FC = () => {
  const { authRequired, isAuthenticated, openAuthModal } = useAuth();

  const { data, refetch, isFetching } = useQuery<CacheTelemetry>({
    queryKey: ['cacheTelemetry'],
    queryFn: () => api.getCacheTelemetry(),
    enabled: !authRequired || isAuthenticated,
  });

  if (authRequired && !isAuthenticated) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Cache & Redis Observability"
          subtitle="Real-time telemetry across Redis exact hash caching, semantic similarity, and fail-open resilience."
          breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Cache' }]}
        />
        <div className="p-8 sm:p-12 rounded-xl bg-[#26364F] border border-[#3B4D66] text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/10 text-[#82A9FF] flex items-center justify-center mx-auto mb-4 border border-[#82A9FF]/20">
            <KeyRound className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-[#F0F4FC]">Authentication Required</h3>
          <p className="text-sm text-[#C1CCDE] mt-1.5 mb-6">
            Authenticate with a client API key to observe live cache telemetry and Redis statistics.
          </p>
          <Button onClick={openAuthModal} variant="primary" icon={KeyRound}>
            Authenticate Console
          </Button>
        </div>
      </div>
    );
  }

  const totalExactLookups = (data?.exact_cache?.hits || 0) + (data?.exact_cache?.misses || 0);
  const exactHitRate =
    totalExactLookups > 0
      ? (((data?.exact_cache?.hits || 0) / totalExactLookups) * 100).toFixed(1)
      : '0.0';

  return (
    <div className="space-y-7">
      {/* Header */}
      <PageHeader
        title="Cache & Redis Observability"
        subtitle="Real-time telemetry across Redis exact hash caching, semantic similarity, and fail-open resilience."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Cache' }]}
        actions={
          <Button
            onClick={() => refetch()}
            disabled={isFetching}
            variant="secondary"
            size="md"
            icon={RefreshCw}
            isLoading={isFetching}
          >
            Refresh Metrics
          </Button>
        }
      />

      {/* Architecture Clarification Banner */}
      <div className="bg-[#26364F] border border-[#3B4D66] rounded-xl p-4 flex items-start gap-3 shadow-card">
        <Info className="w-5 h-5 text-[#61C7B2] flex-shrink-0 mt-0.5" />
        <div className="text-[13px] text-[#C1CCDE] leading-relaxed space-y-1">
          <p>
            <strong className="text-[#F0F4FC]">Decoupled Cache Architecture: </strong>
            SafeRoute decouples caching into three isolated domains: (1) <strong>Redis Server</strong> as an in-memory key-value broker on port 6379, (2) <strong>Exact Response Cache</strong> keyed on SHA-256 parameter hashes, and (3) <strong>Streaming Cache Replay</strong> emitting standard Server-Sent Events.
          </p>
          <p className="text-[11px] text-[#95A6BE]">
            Note: Frontend UI state cached by TanStack Query in your browser is completely separate from backend Redis caching.
          </p>
        </div>
      </div>

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <MetricCard
          title="Redis Broker"
          value={data?.redis_connected ? 'Connected' : 'Disconnected'}
          subtitle={
            data?.redis_connected
              ? `Ping latency: ${data.redis_ping_latency_ms ? data.redis_ping_latency_ms.toFixed(1) : '< 1'} ms`
              : 'Failing Open to Live Runtime'
          }
          icon={Database}
          accentColor={data?.redis_connected ? 'success' : 'error'}
        />
        <MetricCard
          title="Exact Cache Hit Rate"
          value={`${exactHitRate}%`}
          subtitle={`${data?.exact_cache?.hits || 0} hits of ${totalExactLookups} lookups`}
          icon={Zap}
          accentColor="teal"
        />
        <MetricCard
          title="Exact Cache Hits"
          value={(data?.exact_cache?.hits || 0).toLocaleString()}
          subtitle="Identical prompt queries intercepted"
          icon={CheckCircle2}
          accentColor="primary"
        />
        <MetricCard
          title="Streaming Cache Replay"
          value={data?.streaming_replay_enabled ? 'Active' : 'Standby'}
          subtitle="Instant SSE chunk replay from Redis"
          icon={Layers}
          accentColor="violet"
        />
      </div>

      {/* Detailed Technical Breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Exact Cache Engine Configuration */}
        <SectionCard
          title="Exact Response Caching (SHA-256)"
          subtitle="Direct hash-lookup configuration and latency benchmarks"
          icon={Zap}
        >
          <div className="space-y-3 text-xs">
            <div className="flex justify-between p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
              <span className="text-[#95A6BE]">Hash Signature:</span>
              <span className="font-mono text-[#82A9FF] text-[11px]">SHA256(client_id + model + temp + messages)</span>
            </div>
            <div className="flex justify-between p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
              <span className="text-[#95A6BE]">Configured TTL:</span>
              <span className="font-mono text-[#F0F4FC] font-medium">
                {data?.exact_cache?.ttl_seconds ? `${data.exact_cache.ttl_seconds} seconds` : '3600 seconds'}
              </span>
            </div>
            <div className="flex justify-between p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
              <span className="text-[#95A6BE]">Warm Cache Latency:</span>
              <span className="font-mono text-[#63D6A7] font-semibold">~104 ms (p50)</span>
            </div>
            <div className="flex justify-between p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
              <span className="text-[#95A6BE]">Uncached Model Latency:</span>
              <span className="font-mono text-[#95A6BE]">~523 ms (llama3.2:1b p50)</span>
            </div>
          </div>
        </SectionCard>

        {/* Fail-Open Policy & Safety Rules */}
        <SectionCard
          title="High Availability & Safety Policy"
          subtitle="Resilience protocols and tenant cryptographic isolation"
          icon={ShieldAlert}
        >
          <div className="space-y-3 text-xs leading-relaxed">
            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
              <div className="flex items-center gap-1.5 text-[#63D6A7] font-medium mb-1">
                <CheckCircle2 className="w-3.5 h-3.5" /> Fail-Open on Redis Outage
              </div>
              <p className="text-[#C1CCDE] text-[12px]">
                If the Redis broker terminates or becomes unreachable, SafeRoute fails open without dropping customer completions. Incoming requests automatically bypass caching and invoke local Ollama directly with zero downtime.
              </p>
            </div>
            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
              <div className="flex items-center gap-1.5 text-[#82A9FF] font-medium mb-1">
                <CheckCircle2 className="w-3.5 h-3.5" /> Cryptographic Tenant Isolation
              </div>
              <p className="text-[#C1CCDE] text-[12px]">
                Every cache key namespaces the authenticated <code className="text-[#82A9FF]">client_id</code>. Client Alice can never access or replay responses generated by Client Bob, even with identical prompts.
              </p>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
};
