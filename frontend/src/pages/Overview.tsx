import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  CheckCircle2,
  Clock,
  Zap,
  Coins,
  Cpu,
  Layers,
  ArrowRight,
  ShieldAlert,
  KeyRound,
  Server,
  RefreshCw,
  ExternalLink,
} from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeader } from '../components/ui/PageHeader';
import { MetricCard } from '../components/ui/MetricCard';
import { SectionCard } from '../components/ui/SectionCard';
import { StatusBadge } from '../components/ui/StatusBadge';
import { EmptyState } from '../components/ui/EmptyState';
import { Button } from '../components/ui/Button';
import { RequestDetailDrawer } from '../components/ui/RequestDetailDrawer';
import type { RequestDetail } from '../types';

export const Overview: React.FC = () => {
  const navigate = useNavigate();
  const { authRequired, isAuthenticated, openAuthModal } = useAuth();
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['management-overview'],
    queryFn: () => api.getOverview(),
    enabled: !authRequired || isAuthenticated,
    refetchInterval: 10000,
  });

  const { data: detailData, isLoading: detailLoading } = useQuery<RequestDetail>({
    queryKey: ['requestDetail', selectedRequestId],
    queryFn: () => api.getRequestDetail(selectedRequestId!),
    enabled: !!selectedRequestId && (!authRequired || isAuthenticated),
  });

  if (authRequired && !isAuthenticated) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Gateway Operations Overview"
          subtitle="Real-time telemetry aggregated from persistent SQLite records, Redis cache, and Prometheus metrics."
        />
        <div className="p-8 sm:p-12 rounded-xl bg-[#26364F] border border-[#3B4D66] text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/15 border border-[#82A9FF]/30 text-[#82A9FF] flex items-center justify-center mx-auto mb-4">
            <KeyRound className="w-6 h-6" />
          </div>
          <h3 className="text-[17px] font-semibold text-[#F0F4FC]">Console Authentication Required</h3>
          <p className="text-[13px] text-[#C1CCDE] mt-2 mb-6 leading-normal">
            SafeRoute management endpoints are protected. Authenticate with a client API key to load live telemetry.
          </p>
          <Button onClick={openAuthModal} variant="primary" icon={KeyRound}>
            Enter Client Key
          </Button>
        </div>
      </div>
    );
  }

  if (error) {
    const isAuthError = (error as any)?.status === 401;
    return (
      <div className="p-5 rounded-xl bg-[#26364F] border border-[#F18C9C]/40 text-[#F18C9C] flex items-start justify-between gap-4 shadow-card">
        <div className="flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-[#F0F4FC]">Failed to load overview telemetry</h3>
            <p className="text-xs text-[#C1CCDE] mt-1">{(error as Error).message}</p>
          </div>
        </div>
        {isAuthError && (
          <Button onClick={openAuthModal} variant="danger" size="sm">
            Authenticate
          </Button>
        )}
      </div>
    );
  }

  const avoidedCost = ((Number(data?.total_tokens || 0) / 1000) * 0.005).toFixed(4);

  return (
    <div className="space-y-7">
      {/* SECTION A: Page Header & Live Poll Control */}
      <PageHeader
        title="Gateway Operations Overview"
        subtitle="Real-time operational metrics aggregated from persistent SQLite records, Redis cache broker, and Ollama local inference."
        actions={
          <div className="flex items-center gap-2.5">
            <Button
              onClick={() => refetch()}
              disabled={isFetching}
              variant="secondary"
              size="sm"
              icon={RefreshCw}
              isLoading={isFetching}
            >
              Refresh Metrics
            </Button>
            <span className="text-[11px] font-mono px-2.5 py-1.5 rounded-lg bg-[#1C2A40] border border-[#3B4D66] text-[#95A6BE]">
              Live 10s Poll
            </span>
          </div>
        }
      />

      {/* SECTION B: Balanced 4-Column Responsive KPI Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <MetricCard
          title="Total Requests"
          value={data?.total_requests ?? 0}
          subtitle={`${data?.successful_requests ?? 0} successful / ${data?.failed_requests ?? 0} failed`}
          icon={Activity}
          accentColor="primary"
          isLoading={isLoading}
        />
        <MetricCard
          title="Success Rate"
          value={`${data?.success_rate ?? 100}%`}
          subtitle={data?.failed_requests ? `${data.failed_requests} error(s) logged` : 'Zero errors recorded'}
          icon={CheckCircle2}
          accentColor="success"
          isLoading={isLoading}
        />
        <MetricCard
          title="P95 Latency"
          value={`${data?.p95_duration_ms ?? 0} ms`}
          subtitle={`Average latency: ${data?.avg_duration_ms ?? 0} ms`}
          icon={Clock}
          accentColor="info"
          isLoading={isLoading}
        />
        <MetricCard
          title="Cache Hit Rate"
          value={`${data?.cache_hit_rate ?? 0}%`}
          subtitle={`${data?.total_cache_hits ?? 0} hits / ${data?.cache_misses ?? 0} misses`}
          icon={Zap}
          accentColor="teal"
          isLoading={isLoading}
        />
        <MetricCard
          title="Total Tokens"
          value={data?.total_tokens ? Number(data.total_tokens).toLocaleString() : '0'}
          subtitle={`${Number(data?.total_input_tokens ?? 0).toLocaleString()} in · ${Number(data?.total_output_tokens ?? 0).toLocaleString()} out`}
          icon={Cpu}
          accentColor="violet"
          isLoading={isLoading}
        />
        <MetricCard
          title="Avoided Cloud Cost"
          value={`$${avoidedCost}`}
          subtitle="Estimated savings vs frontier cloud APIs"
          icon={Coins}
          accentColor="warning"
          isLoading={isLoading}
        />
        <MetricCard
          title="Exact Cache Hits"
          value={data?.exact_cache_hits ?? 0}
          subtitle="SHA-256 deterministic matches"
          icon={Layers}
          accentColor="teal"
          isLoading={isLoading}
        />
        <MetricCard
          title="Serving Models"
          value={data?.model_counts ? Object.keys(data.model_counts).length : 1}
          subtitle="Local Ollama models served"
          icon={Server}
          accentColor="secondary"
          isLoading={isLoading}
        />
      </div>

      {/* SECTION C: Main Charts (Responsive Layout) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Request Timeline Chart (2 cols) */}
        <SectionCard
          title="Request Volume & Cache Hits Timeline"
          subtitle="Daily aggregated request volume and cache intercept rates from SQLite"
          icon={Activity}
          className="lg:col-span-2"
        >
          <div className="h-[280px] w-full pt-2">
            {isLoading ? (
              <div className="h-full flex items-center justify-center text-xs text-[#95A6BE] animate-pulse">
                Loading telemetry chart...
              </div>
            ) : data?.timeline && data.timeline.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.timeline} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="reqGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#82A9FF" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#82A9FF" stopOpacity={0.0} />
                    </linearGradient>
                    <linearGradient id="hitGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#61C7B2" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#61C7B2" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" stroke="#95A6BE" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis stroke="#95A6BE" fontSize={11} tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#202E46',
                      borderColor: '#3B4D66',
                      borderRadius: '0.5rem',
                      color: '#F0F4FC',
                      fontSize: '12px',
                      boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                  <Area
                    type="monotone"
                    dataKey="total"
                    name="Total Requests"
                    stroke="#82A9FF"
                    fillOpacity={1}
                    fill="url(#reqGrad)"
                    strokeWidth={2}
                  />
                  <Area
                    type="monotone"
                    dataKey="cache_hits"
                    name="Cache Hits"
                    stroke="#61C7B2"
                    fillOpacity={1}
                    fill="url(#hitGrad)"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState
                title="No historical timeline data"
                description="Gateway requests recorded in SQLite will display here automatically."
              />
            )}
          </div>
        </SectionCard>

        {/* Model Distribution (1 col) */}
        <SectionCard
          title="Model Distribution"
          subtitle="Requests by target model ID"
          icon={Layers}
          className="flex flex-col"
        >
          <div className="flex-1 space-y-3 pt-1">
            {data?.model_counts && Object.keys(data.model_counts).length > 0 ? (
              Object.entries(data.model_counts).map(([model, count]) => {
                const total = data.total_requests || 1;
                const percentage = Math.round((count / total) * 100);
                return (
                  <div key={model} className="p-3 rounded-lg bg-[#223149] border border-[#3B4D66]">
                    <div className="flex items-center justify-between text-xs mb-1.5">
                      <span className="font-semibold text-[#F0F4FC] truncate max-w-[170px]" title={model}>
                        {model}
                      </span>
                      <span className="text-[#82A9FF] font-mono text-[11px]">
                        {count} ({percentage}%)
                      </span>
                    </div>
                    <div className="w-full h-1.5 bg-[#1C2A40] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-[#82A9FF] to-[#A4BEFF]"
                        style={{ width: `${percentage}%` }}
                      />
                    </div>
                  </div>
                );
              })
            ) : (
              <EmptyState
                title="No model distribution"
                description="Model queries will appear here once processed."
              />
            )}
          </div>
        </SectionCard>
      </div>

      {/* SECTION D: Recent Requests Table */}
      <SectionCard
        title="Recent Requests Log"
        subtitle="Last requests intercepted, audited, and persisted to SQLite"
        icon={Activity}
        actions={
          <Button
            onClick={() => navigate('/requests')}
            variant="outline"
            size="sm"
            icon={ArrowRight}
            iconPosition="right"
          >
            Request Explorer
          </Button>
        }
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-[13px]">
            <thead>
              <tr className="bg-[#202E46] border-b border-[#3B4D66] text-[#95A6BE] text-[11px] uppercase tracking-wider font-semibold">
                <th className="py-3 px-4">Request ID</th>
                <th className="py-3 px-4">Timestamp</th>
                <th className="py-3 px-4">Model</th>
                <th className="py-3 px-4">Provider</th>
                <th className="py-3 px-4">Latency</th>
                <th className="py-3 px-4">Cache</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4 text-right">Inspect</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#33455E]">
              {data?.recent_requests && data.recent_requests.length > 0 ? (
                data.recent_requests.slice(0, 8).map((req) => (
                  <tr
                    key={req.request_id}
                    onClick={() => setSelectedRequestId(req.request_id)}
                    className="hover:bg-[#2D405B]/40 cursor-pointer transition-colors"
                  >
                    <td className="py-3 px-4 font-mono font-medium text-[#82A9FF] text-[12px] truncate max-w-[140px]">
                      {req.request_id}
                    </td>
                    <td className="py-3 px-4 text-[#95A6BE] text-[12px] whitespace-nowrap">
                      {req.created_at ? new Date(req.created_at).toLocaleTimeString() : '-'}
                    </td>
                    <td className="py-3 px-4 font-medium text-[#F0F4FC] text-[12px]">
                      {req.model}
                    </td>
                    <td className="py-3 px-4 capitalize text-[#C1CCDE] text-[12px]">
                      {req.provider}
                    </td>
                    <td className="py-3 px-4 font-mono text-[#F0F4FC] text-[12px]">
                      {req.duration_ms} ms
                    </td>
                    <td className="py-3 px-4">
                      <StatusBadge status={req.cache_status} size="sm" />
                    </td>
                    <td className="py-3 px-4">
                      <StatusBadge status={String(req.http_status)} size="sm" />
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedRequestId(req.request_id);
                        }}
                        className="text-[#82A9FF] hover:text-[#A4BEFF] font-medium text-[12px] inline-flex items-center gap-1 hover:underline"
                      >
                        Inspect
                        <ExternalLink className="w-3 h-3" />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-[#95A6BE]">
                    No request records found in persistent storage.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* Request Inspection Drawer */}
      <RequestDetailDrawer
        requestId={selectedRequestId}
        detailData={detailData}
        isLoading={detailLoading}
        onClose={() => setSelectedRequestId(null)}
      />
    </div>
  );
};
