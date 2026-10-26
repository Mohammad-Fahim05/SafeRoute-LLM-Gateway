import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeader } from '../components/ui/PageHeader';
import { MetricCard } from '../components/ui/MetricCard';
import { SectionCard } from '../components/ui/SectionCard';
import { StatusBadge } from '../components/ui/StatusBadge';
import { Button } from '../components/ui/Button';
import {
  AlertTriangle,
  ShieldAlert,
  RotateCcw,
  CheckCircle2,
  RefreshCw,
  ServerOff,
  BarChart2,
  KeyRound,
} from 'lucide-react';
import type { OverviewTelemetry } from '../types';

export const Reliability: React.FC = () => {
  const { authRequired, isAuthenticated, openAuthModal } = useAuth();

  const { data: overview, refetch, isFetching } = useQuery<OverviewTelemetry>({
    queryKey: ['overview'],
    queryFn: () => api.getOverview(),
    enabled: !authRequired || isAuthenticated,
  });

  if (authRequired && !isAuthenticated) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Errors & Gateway Reliability"
          subtitle="Audit error categorization, failover sequences, rate-limit throttles, and circuit breaker resilience."
          breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Reliability' }]}
        />
        <div className="p-8 sm:p-12 rounded-xl bg-[#26364F] border border-[#3B4D66] text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/10 text-[#82A9FF] flex items-center justify-center mx-auto mb-4 border border-[#82A9FF]/20">
            <KeyRound className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-[#F0F4FC]">Authentication Required</h3>
          <p className="text-sm text-[#C1CCDE] mt-1.5 mb-6">
            Authenticate with a client API key to audit gateway reliability and error telemetry.
          </p>
          <Button onClick={openAuthModal} variant="primary" icon={KeyRound}>
            Authenticate Console
          </Button>
        </div>
      </div>
    );
  }

  const totalRequests = overview?.total_requests || 0;
  const successful = overview?.successful_requests || 0;
  const failed = overview?.failed_requests || 0;

  return (
    <div className="space-y-7">
      {/* Header */}
      <PageHeader
        title="Errors & Gateway Reliability"
        subtitle="Audit error categorization, failover sequences, rate-limit throttles, and circuit breaker resilience."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Reliability' }]}
        actions={
          <Button
            onClick={() => refetch()}
            disabled={isFetching}
            variant="secondary"
            size="md"
            icon={RefreshCw}
            isLoading={isFetching}
          >
            Refresh
          </Button>
        }
      />

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <MetricCard
          title="Total Gateway Invocations"
          value={totalRequests.toLocaleString()}
          subtitle="All recorded requests"
          icon={BarChart2}
          accentColor="violet"
        />
        <MetricCard
          title="Overall Success Rate"
          value={`${overview?.success_rate ? overview.success_rate.toFixed(1) : '100'}%`}
          subtitle={`${successful} clean 200 OK completions`}
          icon={CheckCircle2}
          accentColor="success"
        />
        <MetricCard
          title="Failed Requests"
          value={failed.toString()}
          subtitle="Client errors (4xx) & server faults (5xx)"
          icon={AlertTriangle}
          accentColor={failed > 0 ? 'error' : 'success'}
        />
        <MetricCard
          title="Failover Retry Policy"
          value="3 Attempts"
          subtitle="Exponential backoff with jitter"
          icon={RotateCcw}
          accentColor="info"
        />
      </div>

      {/* Error Taxonomy & Policies */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Error Categories Breakdown */}
        <SectionCard
          title="Error Category Taxonomy"
          subtitle="Standard HTTP classification of gateway responses"
          icon={ServerOff}
        >
          <div className="space-y-3 text-xs">
            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E] flex items-center justify-between">
              <div>
                <span className="font-semibold text-[#F0F4FC] block">HTTP 401 Unauthorized</span>
                <span className="text-[#95A6BE] text-[11px]">Missing, malformed, or invalid HMAC Bearer key</span>
              </div>
              <StatusBadge status="Auth Guard" variant="warning" size="sm" />
            </div>

            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E] flex items-center justify-between">
              <div>
                <span className="font-semibold text-[#F0F4FC] block">HTTP 429 Rate Limited</span>
                <span className="text-[#95A6BE] text-[11px]">Redis atomic fixed-window threshold exceeded</span>
              </div>
              <StatusBadge status="Throttled" variant="warning" size="sm" />
            </div>

            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E] flex items-center justify-between">
              <div>
                <span className="font-semibold text-[#F0F4FC] block">HTTP 400 Bad Request</span>
                <span className="text-[#95A6BE] text-[11px]">Pydantic schema validation or guardrail rejections</span>
              </div>
              <StatusBadge status="Client Error" variant="error" size="sm" />
            </div>

            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E] flex items-center justify-between">
              <div>
                <span className="font-semibold text-[#F0F4FC] block">HTTP 502 / 503 Provider Fault</span>
                <span className="text-[#95A6BE] text-[11px]">Local Ollama runtime unreachable or output blocked</span>
              </div>
              <StatusBadge status="Upstream" variant="error" size="sm" />
            </div>
          </div>
        </SectionCard>

        {/* Resilience Architecture */}
        <SectionCard
          title="Active Fault-Tolerance Features"
          subtitle="Built-in reliability guarantees and runtime protection"
          icon={ShieldAlert}
        >
          <div className="space-y-3 text-xs leading-relaxed">
            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
              <span className="font-semibold text-[#F0F4FC] block mb-1">
                Zero-Drop Fail-Open Cache Policy
              </span>
              <p className="text-[#C1CCDE] text-[12px]">
                If the Redis broker terminates or network sockets drop, SafeRoute automatically bypasses caching and routes directly to local Ollama. Clients never experience an outage due to caching issues.
              </p>
            </div>
            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
              <span className="font-semibold text-[#F0F4FC] block mb-1">
                Constant-Time HMAC Timing Attack Defense
              </span>
              <p className="text-[#C1CCDE] text-[12px]">
                Client API keys are verified with constant-time comparison (<code className="text-[#82A9FF]">hmac.compare_digest</code>), eliminating timing-based credential extraction attacks.
              </p>
            </div>
            <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
              <span className="font-semibold text-[#F0F4FC] block mb-1">
                SQLite Write-Ahead Logging (WAL) & 15s Busy Timeout
              </span>
              <p className="text-[#C1CCDE] text-[12px]">
                SQLite operates in WAL mode with <code className="text-[#82A9FF]">PRAGMA busy_timeout=15000</code>, ensuring thread-safe transactional commits without database locks under heavy concurrent load.
              </p>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
};
