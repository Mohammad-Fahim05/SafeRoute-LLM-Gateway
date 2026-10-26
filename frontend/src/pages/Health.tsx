import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeader } from '../components/ui/PageHeader';
import { SectionCard } from '../components/ui/SectionCard';
import { ServiceHealthCard } from '../components/ui/ServiceHealthCard';
import { Button } from '../components/ui/Button';
import { parsePrometheusText, type PrometheusMetric } from '../utils/prometheus';
import {
  Activity,
  Database,
  Cpu,
  Search,
  RefreshCw,
  Server,
  Zap,
  KeyRound,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  Layers,
  Radio,
  FileCode2,
} from 'lucide-react';
import type { HealthSummary } from '../types';

export const Health: React.FC = () => {
  const { authRequired, isAuthenticated, openAuthModal } = useAuth();
  const [metricSearch, setMetricSearch] = useState('');
  const [selectedType, setSelectedType] = useState<string>('all');
  const [expandedMetric, setExpandedMetric] = useState<string | null>(null);
  const [showRawStream, setShowRawStream] = useState(false);
  const [rawCopied, setRawCopied] = useState(false);

  const {
    data: health,
    refetch: refetchHealth,
    isFetching: isHealthFetching,
  } = useQuery<HealthSummary>({
    queryKey: ['healthSummary'],
    queryFn: () => api.getHealthSummary(),
    enabled: !authRequired || isAuthenticated,
  });

  const {
    data: rawMetrics,
    isLoading: metricsLoading,
    refetch: refetchMetrics,
    isFetching: isMetricsFetching,
  } = useQuery<string>({
    queryKey: ['rawPrometheusMetrics'],
    queryFn: () => api.getRawMetrics(),
    enabled: !authRequired || isAuthenticated,
  });

  const isBusy = isHealthFetching || isMetricsFetching;

  // Parse Prometheus text into structured metric objects
  const parsedMetrics = useMemo(() => {
    if (!rawMetrics) return [];
    return parsePrometheusText(rawMetrics);
  }, [rawMetrics]);

  // Filter metrics based on search query and type selector
  const filteredMetrics = useMemo(() => {
    return parsedMetrics.filter((m) => {
      const matchesType = selectedType === 'all' || m.type === selectedType;
      if (!matchesType) return false;

      if (!metricSearch) return true;
      const q = metricSearch.toLowerCase();
      const inName = m.name.toLowerCase().includes(q);
      const inHelp = m.help.toLowerCase().includes(q);
      const inLabels = m.samples.some((s) =>
        Object.entries(s.labels).some(([k, v]) =>
          k.toLowerCase().includes(q) || v.toLowerCase().includes(q)
        )
      );
      return inName || inHelp || inLabels;
    });
  }, [parsedMetrics, metricSearch, selectedType]);

  // Calculate summary metric highlights
  const metricHighlights = useMemo(() => {
    const findMetric = (name: string) => parsedMetrics.find((m) => m.name === name);

    const requests = findMetric('saferoute_requests_total');
    const totalRequests = requests ? requests.latestValue : 0;

    const streams = findMetric('saferoute_streaming_requests_active');
    const activeStreams = streams ? streams.latestValue : 0;

    const cacheOps = findMetric('saferoute_cache_operations_total');
    const totalCacheOps = cacheOps ? cacheOps.latestValue : 0;

    const tokens = findMetric('saferoute_tokens_total');
    const totalTokens = tokens ? tokens.latestValue : 0;

    return { totalRequests, activeStreams, totalCacheOps, totalTokens };
  }, [parsedMetrics]);

  const handleCopyRaw = () => {
    if (rawMetrics) {
      navigator.clipboard.writeText(rawMetrics);
      setRawCopied(true);
      setTimeout(() => setRawCopied(false), 2000);
    }
  };

  const handleRunHealthChecks = () => {
    refetchHealth();
    refetchMetrics();
  };

  if (authRequired && !isAuthenticated) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="System Health"
          subtitle="Service status, runtime connectivity, and gateway observability."
          breadcrumbs={[{ label: 'SafeRoute' }, { label: 'System Health' }]}
        />
        <div className="p-8 rounded-xl bg-[#26364F] border border-[#3B4D66] text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/10 text-[#82A9FF] flex items-center justify-center mx-auto mb-4 border border-[#82A9FF]/20">
            <KeyRound className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-[#F0F4FC]">Authentication Required</h3>
          <p className="text-sm text-[#C1CCDE] mt-1.5 mb-6">
            Authenticate with a client API key to view system health checks and Prometheus metrics.
          </p>
          <Button onClick={openAuthModal} variant="primary" icon={KeyRound}>
            Authenticate Console
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-7">
      {/* Page Header */}
      <PageHeader
        title="System Health"
        subtitle="Service status, runtime connectivity, and gateway observability."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'System Health' }]}
        actions={
          <Button
            onClick={handleRunHealthChecks}
            disabled={isBusy}
            variant="primary"
            size="md"
            icon={RefreshCw}
            isLoading={isBusy}
          >
            Run Health Checks
          </Button>
        }
      />

      {/* Service Health Cards Section */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[19px] font-semibold text-[#F0F4FC] tracking-tight">
            Component Status
          </h2>
          <span className="text-[12px] text-[#95A6BE]">
            4 Core Subsystems Active
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {/* Gateway Core */}
          <ServiceHealthCard
            name="Gateway Core"
            icon={Server}
            status={health?.gateway || 'Healthy'}
            description="FastAPI reverse proxy, rate limiting & auth"
            diagnostics={[
              { label: 'Environment', value: health?.app_env || 'development' },
              { label: 'Endpoint', value: '127.0.0.1:8000', mono: true },
              { label: 'Auth Guard', value: 'HMAC-SHA256' },
            ]}
            lastChecked={health?.server_time}
            onAction={handleRunHealthChecks}
            actionLabel="Verify Core"
            isActionLoading={isBusy}
          />

          {/* SQLite Database */}
          <ServiceHealthCard
            name="SQLite Database"
            icon={Database}
            status={health?.database || 'Healthy'}
            description="Relational audit store & token usage accounting"
            diagnostics={[
              { label: 'Journal Mode', value: 'WAL Mode', mono: true },
              { label: 'Busy Timeout', value: '15,000 ms', mono: true },
              { label: 'Data File', value: 'data/saferoute.db', mono: true },
            ]}
            lastChecked={health?.server_time}
            onAction={handleRunHealthChecks}
            actionLabel="Check Storage"
            isActionLoading={isBusy}
          />

          {/* Redis Broker */}
          <ServiceHealthCard
            name="Redis Broker"
            icon={Zap}
            status={health?.redis || 'Connected'}
            description="Exact cache broker & atomic Lua rate limiter"
            diagnostics={[
              { label: 'Host', value: '127.0.0.1:6379', mono: true },
              { label: 'Limiter Policy', value: 'Atomic Fixed-Window' },
              { label: 'Failure Mode', value: 'Fail-Open (Resilient)' },
            ]}
            lastChecked={health?.server_time}
            onAction={handleRunHealthChecks}
            actionLabel="Ping Redis"
            isActionLoading={isBusy}
          />

          {/* Ollama Local AI */}
          <ServiceHealthCard
            name="Ollama Runtime"
            icon={Cpu}
            status={health?.ollama || 'Online'}
            description="Local zero-cost LLM inference engine"
            diagnostics={[
              { label: 'Host', value: '127.0.0.1:11434', mono: true },
              { label: 'Default Model', value: 'llama3.2:1b', mono: true },
              { label: 'Cloud Cost', value: '$0.0000 (Local)' },
            ]}
            lastChecked={health?.server_time}
            onAction={handleRunHealthChecks}
            actionLabel="Probe Models"
            isActionLoading={isBusy}
          />
        </div>
      </section>

      {/* Prometheus Telemetry Highlights */}
      <section>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="p-4 rounded-xl bg-[#26364F] border border-[#3B4D66]">
            <div className="flex items-center justify-between text-[#95A6BE] text-[12px] mb-1">
              <span>Total Requests Recorded</span>
              <Activity className="w-4 h-4 text-[#82A9FF]" />
            </div>
            <div className="text-[26px] font-semibold text-[#F0F4FC] font-mono">
              {metricHighlights.totalRequests.toLocaleString()}
            </div>
            <span className="text-[11px] text-[#63D6A7]">saferoute_requests_total</span>
          </div>

          <div className="p-4 rounded-xl bg-[#26364F] border border-[#3B4D66]">
            <div className="flex items-center justify-between text-[#95A6BE] text-[12px] mb-1">
              <span>Active SSE Streams</span>
              <Radio className="w-4 h-4 text-[#61C7B2]" />
            </div>
            <div className="text-[26px] font-semibold text-[#F0F4FC] font-mono">
              {metricHighlights.activeStreams}
            </div>
            <span className="text-[11px] text-[#85B8F9]">streaming_requests_active</span>
          </div>

          <div className="p-4 rounded-xl bg-[#26364F] border border-[#3B4D66]">
            <div className="flex items-center justify-between text-[#95A6BE] text-[12px] mb-1">
              <span>Cache Operations</span>
              <Zap className="w-4 h-4 text-[#F2C777]" />
            </div>
            <div className="text-[26px] font-semibold text-[#F0F4FC] font-mono">
              {metricHighlights.totalCacheOps.toLocaleString()}
            </div>
            <span className="text-[11px] text-[#F2C777]">cache_operations_total</span>
          </div>

          <div className="p-4 rounded-xl bg-[#26364F] border border-[#3B4D66]">
            <div className="flex items-center justify-between text-[#95A6BE] text-[12px] mb-1">
              <span>Evaluated Tokens</span>
              <Layers className="w-4 h-4 text-[#B1A0F8]" />
            </div>
            <div className="text-[26px] font-semibold text-[#F0F4FC] font-mono">
              {metricHighlights.totalTokens.toLocaleString()}
            </div>
            <span className="text-[11px] text-[#B1A0F8]">saferoute_tokens_total</span>
          </div>
        </div>
      </section>

      {/* Structured Prometheus Metrics Explorer */}
      <SectionCard
        title="Prometheus Metrics Explorer"
        subtitle="Structured telemetry parsed from /metrics endpoint with counters, gauges, and histograms"
        icon={Activity}
        actions={
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5 w-full sm:w-auto">
            {/* Metric Type Selector */}
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="px-3 py-1.5 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] focus:outline-none focus:border-[#82A9FF]"
            >
              <option value="all">All Metric Types</option>
              <option value="counter">Counter</option>
              <option value="gauge">Gauge</option>
              <option value="histogram">Histogram</option>
              <option value="summary">Summary</option>
            </select>

            {/* Metric Search Input */}
            <div className="relative w-full sm:w-64">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#95A6BE]" />
              <input
                type="text"
                value={metricSearch}
                onChange={(e) => setMetricSearch(e.target.value)}
                placeholder="Search metrics, labels..."
                className="w-full pl-9 pr-3 py-1.5 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] placeholder:text-[#95A6BE]/50 focus:outline-none focus:border-[#82A9FF] transition-colors"
              />
            </div>

            {/* Refresh Button */}
            <Button
              onClick={() => refetchMetrics()}
              disabled={isMetricsFetching}
              variant="secondary"
              size="sm"
              icon={RefreshCw}
              isLoading={isMetricsFetching}
            >
              Refresh
            </Button>
          </div>
        }
        noPadding
      >
        {metricsLoading ? (
          <div className="p-12 text-center text-[#95A6BE] animate-pulse">
            Scraping Prometheus metrics stream...
          </div>
        ) : filteredMetrics.length === 0 ? (
          <div className="p-12 text-center text-[#95A6BE]">
            No matching Prometheus metrics found.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-[13px]">
              <thead>
                <tr className="bg-[#202E46] border-b border-[#3B4D66] text-[#95A6BE] text-[11px] uppercase tracking-wider font-semibold">
                  <th className="py-3 px-4">Metric Name</th>
                  <th className="py-3 px-4">Type</th>
                  <th className="py-3 px-4">Value</th>
                  <th className="py-3 px-4">Labels / Dimensions</th>
                  <th className="py-3 px-4">Description</th>
                  <th className="py-3 px-4 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#33455E]">
                {filteredMetrics.map((metric: PrometheusMetric) => {
                  const isExpanded = expandedMetric === metric.name;
                  return (
                    <React.Fragment key={metric.name}>
                      <tr className="hover:bg-[#2D405B]/40 transition-colors">
                        <td className="py-3.5 px-4 font-mono font-medium text-[#82A9FF] text-[12px]">
                          {metric.name}
                        </td>
                        <td className="py-3.5 px-4">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase font-semibold border ${
                              metric.type === 'counter'
                                ? 'bg-[#82A9FF]/10 text-[#82A9FF] border-[#82A9FF]/25'
                                : metric.type === 'gauge'
                                ? 'bg-[#61C7B2]/10 text-[#61C7B2] border-[#61C7B2]/25'
                                : metric.type === 'histogram'
                                ? 'bg-[#B1A0F8]/10 text-[#B1A0F8] border-[#B1A0F8]/25'
                                : 'bg-[#95A6BE]/10 text-[#95A6BE] border-[#95A6BE]/25'
                            }`}
                          >
                            {metric.type}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 font-mono font-semibold text-[#F0F4FC] text-[13px]">
                          {metric.latestValue.toLocaleString()}
                        </td>
                        <td className="py-3.5 px-4">
                          <div className="flex flex-wrap gap-1.5 max-w-xs">
                            {metric.samples[0] &&
                            Object.keys(metric.samples[0].labels).length > 0 ? (
                              Object.entries(metric.samples[0].labels).map(([k, v]) => (
                                <span
                                  key={k}
                                  className="px-1.5 py-0.5 bg-[#1C2A40] border border-[#33455E] rounded text-[10px] font-mono text-[#C1CCDE]"
                                >
                                  {k}=<span className="text-[#85B8F9]">{v}</span>
                                </span>
                              ))
                            ) : (
                              <span className="text-[11px] text-[#95A6BE] italic">
                                None
                              </span>
                            )}
                            {metric.samples.length > 1 && (
                              <span className="text-[10px] text-[#82A9FF] font-medium self-center">
                                +{metric.samples.length - 1} samples
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-3.5 px-4 text-[#C1CCDE] text-[12px] max-w-sm truncate">
                          {metric.help}
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <button
                            onClick={() =>
                              setExpandedMetric(isExpanded ? null : metric.name)
                            }
                            className="p-1.5 rounded-lg text-[#95A6BE] hover:text-[#F0F4FC] hover:bg-[#2D405B] transition-colors"
                            title={isExpanded ? 'Collapse samples' : 'View all samples'}
                          >
                            {isExpanded ? (
                              <ChevronDown className="w-4 h-4 text-[#82A9FF]" />
                            ) : (
                              <ChevronRight className="w-4 h-4" />
                            )}
                          </button>
                        </td>
                      </tr>

                      {/* Expanded Sub-table for Multi-Sample Metrics */}
                      {isExpanded && (
                        <tr className="bg-[#1C2A40]/80">
                          <td colSpan={6} className="p-4 border-b border-[#3B4D66]">
                            <div className="space-y-3">
                              <div className="flex items-center justify-between text-xs text-[#95A6BE]">
                                <span className="font-semibold text-[#F0F4FC]">
                                  Full Scraped Samples ({metric.samples.length})
                                </span>
                                <span>{metric.help}</span>
                              </div>
                              <div className="space-y-1.5 max-h-56 overflow-y-auto">
                                {metric.samples.map((sample, idx) => (
                                  <div
                                    key={idx}
                                    className="p-2 rounded bg-[#26364F] border border-[#33455E] flex items-center justify-between font-mono text-[11px]"
                                  >
                                    <span className="text-[#C1CCDE] truncate pr-4">
                                      {sample.rawLine}
                                    </span>
                                    <span className="text-[#63D6A7] font-semibold flex-shrink-0">
                                      {sample.value}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {/* Collapsible Diagnostic Raw Metrics Panel */}
      <div className="rounded-xl bg-[#26364F] border border-[#3B4D66] overflow-hidden">
        <div
          onClick={() => setShowRawStream((prev) => !prev)}
          className="px-5 py-4 bg-[#223149] cursor-pointer flex items-center justify-between select-none hover:bg-[#273752] transition-colors"
        >
          <div className="flex items-center gap-3">
            <FileCode2 className="w-4 h-4 text-[#95A6BE]" />
            <div>
              <h3 className="text-[14px] font-semibold text-[#F0F4FC]">
                Raw Prometheus Exposition Stream
              </h3>
              <p className="text-[12px] text-[#95A6BE]">
                Unparsed Prometheus exposition text directly from /metrics endpoint
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-[#95A6BE] font-mono">
              {rawMetrics ? `${rawMetrics.split('\n').length} lines` : '0 lines'}
            </span>
            {showRawStream ? (
              <ChevronDown className="w-4 h-4 text-[#82A9FF]" />
            ) : (
              <ChevronRight className="w-4 h-4 text-[#95A6BE]" />
            )}
          </div>
        </div>

        {showRawStream && (
          <div className="p-5 border-t border-[#3B4D66] space-y-3">
            <div className="flex justify-end">
              <Button
                onClick={handleCopyRaw}
                variant="outline"
                size="sm"
                icon={rawCopied ? Check : Copy}
              >
                {rawCopied ? 'Copied' : 'Copy Raw Exposition'}
              </Button>
            </div>
            <pre className="p-4 rounded-lg bg-[#1C2A40] border border-[#33455E] font-mono text-[11px] text-[#A4BEFF] overflow-x-auto max-h-[380px] leading-relaxed selection:bg-[#82A9FF]/30">
              <code>{rawMetrics}</code>
            </pre>
          </div>
        )}
      </div>
    </div>
  );
};
