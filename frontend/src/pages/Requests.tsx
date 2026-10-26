import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { StatusBadge } from '../components/ui/StatusBadge';
import { PageHeader } from '../components/ui/PageHeader';
import { SectionCard } from '../components/ui/SectionCard';
import { Button } from '../components/ui/Button';
import { RequestDetailDrawer } from '../components/ui/RequestDetailDrawer';
import { EmptyState } from '../components/ui/EmptyState';
import {
  Search,
  RefreshCw,
  FileText,
  ChevronLeft,
  ChevronRight,
  Filter,
  ExternalLink,
  KeyRound,
} from 'lucide-react';
import type { RequestRecordItem, RequestDetail } from '../types';

export const Requests: React.FC = () => {
  const { authRequired, isAuthenticated, openAuthModal } = useAuth();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [providerFilter, setProviderFilter] = useState('');
  const [cacheFilter, setCacheFilter] = useState('');
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['requests', page, pageSize, search, statusFilter, providerFilter, cacheFilter],
    queryFn: () =>
      api.getRequests({
        page,
        page_size: pageSize,
        search: search || undefined,
        status: statusFilter ? Number(statusFilter) : undefined,
        provider: providerFilter || undefined,
        cache_status: cacheFilter || undefined,
      }),
    enabled: !authRequired || isAuthenticated,
  });

  const { data: detailData, isLoading: detailLoading } = useQuery<RequestDetail>({
    queryKey: ['requestDetail', selectedRequestId],
    queryFn: () => api.getRequestDetail(selectedRequestId!),
    enabled: !!selectedRequestId && (!authRequired || isAuthenticated),
  });

  const handleResetFilters = () => {
    setSearch('');
    setStatusFilter('');
    setProviderFilter('');
    setCacheFilter('');
    setPage(1);
  };

  const hasActiveFilters = Boolean(search || statusFilter || providerFilter || cacheFilter);

  if (authRequired && !isAuthenticated) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Request Explorer"
          subtitle="Search, filter, and inspect persisted gateway requests and execution traces."
          breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Requests' }]}
        />
        <div className="p-8 sm:p-12 rounded-xl bg-[#26364F] border border-[#3B4D66] text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/10 text-[#82A9FF] flex items-center justify-center mx-auto mb-4 border border-[#82A9FF]/20">
            <KeyRound className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-[#F0F4FC]">Authentication Required</h3>
          <p className="text-sm text-[#C1CCDE] mt-1.5 mb-6">
            Enter a valid client key to search and inspect persisted gateway requests.
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
        title="Request Explorer"
        subtitle="Search, filter, and inspect persisted gateway requests and execution traces from SQLite."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Requests' }]}
        actions={
          <Button
            onClick={() => refetch()}
            disabled={isFetching}
            variant="secondary"
            size="md"
            icon={RefreshCw}
            isLoading={isFetching}
          >
            Refresh Logs
          </Button>
        }
      />

      {/* Filter Toolbar SectionCard */}
      <SectionCard
        title="Filter & Search"
        subtitle="Filter requests by ID, model, status code, provider, or cache outcome"
        icon={Filter}
        actions={
          hasActiveFilters ? (
            <Button onClick={handleResetFilters} variant="ghost" size="sm">
              Reset Filters
            </Button>
          ) : undefined
        }
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5">
          {/* Search Input */}
          <div className="relative lg:col-span-2">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#95A6BE]" />
            <input
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Search by Request ID, Model, or Route..."
              className="w-full pl-9 pr-3 py-2 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] placeholder:text-[#95A6BE]/60 focus:outline-none focus:border-[#82A9FF] transition-colors"
            />
          </div>

          {/* Status Filter */}
          <div>
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="w-full px-3 py-2 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] focus:outline-none focus:border-[#82A9FF] transition-colors"
            >
              <option value="">All HTTP Statuses</option>
              <option value="200">200 OK</option>
              <option value="400">400 Bad Request</option>
              <option value="401">401 Unauthorized</option>
              <option value="429">429 Rate Limited</option>
              <option value="500">500 Server Error</option>
              <option value="503">503 Service Unavailable</option>
            </select>
          </div>

          {/* Provider Filter */}
          <div>
            <select
              value={providerFilter}
              onChange={(e) => {
                setProviderFilter(e.target.value);
                setPage(1);
              }}
              className="w-full px-3 py-2 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] focus:outline-none focus:border-[#82A9FF] transition-colors"
            >
              <option value="">All Providers</option>
              <option value="ollama">Ollama (Local)</option>
              <option value="mock">Mock Provider</option>
            </select>
          </div>

          {/* Cache Filter */}
          <div>
            <select
              value={cacheFilter}
              onChange={(e) => {
                setCacheFilter(e.target.value);
                setPage(1);
              }}
              className="w-full px-3 py-2 bg-[#1C2A40] border border-[#3B4D66] rounded-lg text-xs text-[#F0F4FC] focus:outline-none focus:border-[#82A9FF] transition-colors"
            >
              <option value="">All Cache States</option>
              <option value="HIT">Cache Hit (Exact)</option>
              <option value="SEMANTIC_HIT">Semantic Hit</option>
              <option value="MISS">Cache Miss</option>
              <option value="BYPASS">Cache Bypass</option>
            </select>
          </div>
        </div>
      </SectionCard>

      {/* Requests Table SectionCard */}
      <SectionCard noPadding>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-[13px]">
            <thead>
              <tr className="bg-[#202E46] border-b border-[#3B4D66] text-[11px] font-semibold uppercase tracking-wider text-[#95A6BE]">
                <th className="py-3 px-4">Request ID</th>
                <th className="py-3 px-4">Timestamp</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Provider / Model</th>
                <th className="py-3 px-4">Latency</th>
                <th className="py-3 px-4">Tokens</th>
                <th className="py-3 px-4">Cache</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#33455E] text-xs">
              {isLoading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={8} className="py-3.5 px-4">
                      <div className="h-4 bg-[#2D405B] rounded"></div>
                    </td>
                  </tr>
                ))
              ) : data && data.items.length > 0 ? (
                data.items.map((req: RequestRecordItem) => (
                  <tr
                    key={req.request_id}
                    onClick={() => setSelectedRequestId(req.request_id)}
                    className="hover:bg-[#2D405B]/40 transition-colors cursor-pointer group"
                  >
                    <td className="py-3 px-4 font-mono text-[12px] text-[#82A9FF] font-medium truncate max-w-[150px]">
                      {req.request_id}
                    </td>
                    <td className="py-3 px-4 text-[#95A6BE] whitespace-nowrap">
                      {req.created_at ? new Date(req.created_at).toLocaleTimeString() : 'Just now'}
                    </td>
                    <td className="py-3 px-4">
                      <StatusBadge status={String(req.http_status)} size="sm" />
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-col">
                        <span className="font-medium text-[#F0F4FC] capitalize text-xs">
                          {req.provider || 'Gateway'}
                        </span>
                        <span className="text-[#95A6BE] text-[11px] font-mono">
                          {req.model_actual || req.model_requested || 'none'}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 px-4 font-mono text-xs text-[#F0F4FC]">
                      {req.duration_ms ? `${req.duration_ms.toFixed(1)} ms` : '-'}
                    </td>
                    <td className="py-3 px-4 text-xs font-mono">
                      {req.total_tokens !== null && req.total_tokens !== undefined ? (
                        <span className="text-[#B1A0F8] font-medium">
                          {req.total_tokens.toLocaleString()}
                        </span>
                      ) : (
                        <span className="text-[#95A6BE]/60">-</span>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      <StatusBadge status={req.cache_status || 'MISS'} size="sm" />
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedRequestId(req.request_id);
                        }}
                        className="inline-flex items-center gap-1 text-[12px] text-[#82A9FF] hover:text-[#A4BEFF] font-medium transition-colors hover:underline"
                      >
                        Inspect
                        <ExternalLink className="w-3 h-3" />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} className="py-8">
                    <EmptyState
                      icon={FileText}
                      title="No request records found"
                      description="Try adjusting your search query, status filter, or provider selections."
                      action={
                        hasActiveFilters
                          ? { label: 'Reset filters', onClick: handleResetFilters }
                          : undefined
                      }
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        {data && data.total > 0 && (
          <div className="flex flex-col sm:flex-row items-center justify-between px-5 py-3.5 bg-[#202E46] border-t border-[#3B4D66] text-xs text-[#95A6BE] gap-3">
            <div>
              Showing <span className="font-semibold text-[#F0F4FC]">{Math.min(data.total, (page - 1) * pageSize + 1)}</span> to{' '}
              <span className="font-semibold text-[#F0F4FC]">{Math.min(data.total, page * pageSize)}</span> of{' '}
              <span className="font-semibold text-[#F0F4FC]">{data.total}</span> records
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="flex items-center gap-1 px-3 py-1.5 bg-[#26364F] hover:bg-[#2D405B] disabled:opacity-40 disabled:pointer-events-none border border-[#3B4D66] rounded-lg text-[#F0F4FC] text-xs transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> Prev
              </button>
              <span className="px-2 font-mono text-xs text-[#F0F4FC]">
                Page {page} of {data.total_pages || 1}
              </span>
              <button
                disabled={page >= data.total_pages}
                onClick={() => setPage((p) => p + 1)}
                className="flex items-center gap-1 px-3 py-1.5 bg-[#26364F] hover:bg-[#2D405B] disabled:opacity-40 disabled:pointer-events-none border border-[#3B4D66] rounded-lg text-[#F0F4FC] text-xs transition-colors"
              >
                Next <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </SectionCard>

      {/* Reusable Request Detail Drawer */}
      <RequestDetailDrawer
        requestId={selectedRequestId}
        detailData={detailData}
        isLoading={detailLoading}
        onClose={() => setSelectedRequestId(null)}
      />
    </div>
  );
};
