import React from 'react';
import { X, ShieldAlert } from 'lucide-react';
import type { RequestDetail } from '../../types';
import { StatusBadge } from './StatusBadge';
import { JsonViewer } from './JsonViewer';

interface RequestDetailDrawerProps {
  request?: RequestDetail | null;
  requestId?: string | null;
  detailData?: RequestDetail | null;
  isLoading?: boolean;
  isOpen?: boolean;
  onClose: () => void;
}

export const RequestDetailDrawer: React.FC<RequestDetailDrawerProps> = ({
  request: directRequest,
  requestId,
  detailData,
  isLoading = false,
  isOpen: propIsOpen,
  onClose,
}) => {
  const request = detailData !== undefined ? detailData : directRequest;
  const isOpen = propIsOpen !== undefined ? propIsOpen : Boolean(requestId || request);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-[#101726]/80 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-2xl bg-[#1D2940] border-l border-[#3B4D66] shadow-elevated flex flex-col">
          {/* Drawer Header */}
          <div className="px-6 py-5 border-b border-[#3B4D66] flex items-center justify-between bg-[#202E46]">
            <div className="min-w-0 pr-4">
              <div className="flex items-center gap-2 text-xs text-[#95A6BE] mb-1">
                <span>Request Trace</span>
                <span>/</span>
                <span className="font-mono text-[#82A9FF] truncate">{request?.request_id || 'Loading...'}</span>
              </div>
              <h2 className="text-lg font-semibold text-[#F0F4FC] tracking-tight truncate">
                Audit Trail & Execution Details
              </h2>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-[#95A6BE] hover:text-[#F0F4FC] hover:bg-[#2D405B] transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Drawer Content */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {isLoading ? (
              <div className="space-y-4 animate-pulse">
                <div className="h-20 bg-[#26364F] rounded-xl border border-[#3B4D66]" />
                <div className="h-40 bg-[#26364F] rounded-xl border border-[#3B4D66]" />
                <div className="h-40 bg-[#26364F] rounded-xl border border-[#3B4D66]" />
              </div>
            ) : !request ? (
              <p className="text-sm text-[#C1CCDE] text-center my-12">No request details available.</p>
            ) : (
              <>
                {/* Zero Retention Compliance Banner */}
                <div className="p-3.5 rounded-xl bg-[#223149] border border-[#3B4D66] flex items-start gap-3">
                  <ShieldAlert className="w-4 h-4 text-[#61C7B2] flex-shrink-0 mt-0.5" />
                  <div className="text-[12px] text-[#C1CCDE]">
                    <span className="font-semibold text-[#F0F4FC]">Zero-Prompt Retention Guarantee:</span> Prompts, raw completions, and client PII are never retained in persistent database storage. Only execution metadata, token counts, and cost telemetry are preserved.
                  </div>
                </div>

                {/* Primary KPI Strip */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="p-3.5 rounded-xl bg-[#26364F] border border-[#3B4D66]">
                    <span className="text-[11px] font-medium text-[#95A6BE] uppercase">HTTP Status</span>
                    <div className="mt-1.5">
                      <StatusBadge status={String(request.http_status)} size="sm" />
                    </div>
                  </div>
                  <div className="p-3.5 rounded-xl bg-[#26364F] border border-[#3B4D66]">
                    <span className="text-[11px] font-medium text-[#95A6BE] uppercase">Latency</span>
                    <div className="mt-1 font-mono text-[16px] font-semibold text-[#F0F4FC]">
                      {request.duration_ms} ms
                    </div>
                  </div>
                  <div className="p-3.5 rounded-xl bg-[#26364F] border border-[#3B4D66]">
                    <span className="text-[11px] font-medium text-[#95A6BE] uppercase">Cache Status</span>
                    <div className="mt-1.5">
                      <StatusBadge status={request.cache_status} size="sm" />
                    </div>
                  </div>
                  <div className="p-3.5 rounded-xl bg-[#26364F] border border-[#3B4D66]">
                    <span className="text-[11px] font-medium text-[#95A6BE] uppercase">Tokens</span>
                    <div className="mt-1 font-mono text-[16px] font-semibold text-[#63D6A7]">
                      {request.total_tokens ? Number(request.total_tokens).toLocaleString() : '0'}
                    </div>
                  </div>
                </div>

                {/* Metadata Details Table */}
                <div className="rounded-xl bg-[#26364F] border border-[#3B4D66] overflow-hidden">
                  <div className="px-4 py-3 bg-[#223149] border-b border-[#3B4D66] text-xs font-semibold text-[#F0F4FC]">
                    Execution Metadata
                  </div>
                  <dl className="divide-y divide-[#33455E] text-xs">
                    <div className="px-4 py-2.5 flex justify-between">
                      <dt className="text-[#95A6BE]">Request ID</dt>
                      <dd className="font-mono text-[#F0F4FC] select-all">{request.request_id}</dd>
                    </div>
                    <div className="px-4 py-2.5 flex justify-between">
                      <dt className="text-[#95A6BE]">Client ID</dt>
                      <dd className="font-medium text-[#C1CCDE]">{request.client_id || 'local_dev'}</dd>
                    </div>
                    <div className="px-4 py-2.5 flex justify-between">
                      <dt className="text-[#95A6BE]">Requested Model</dt>
                      <dd className="font-medium text-[#82A9FF]">{request.model_requested}</dd>
                    </div>
                    <div className="px-4 py-2.5 flex justify-between">
                      <dt className="text-[#95A6BE]">Serving Provider</dt>
                      <dd className="capitalize text-[#F0F4FC]">{request.provider}</dd>
                    </div>
                    <div className="px-4 py-2.5 flex justify-between">
                      <dt className="text-[#95A6BE]">Transmission Type</dt>
                      <dd className="text-[#C1CCDE]">{request.stream ? 'Server-Sent Events (SSE Stream)' : 'Synchronous HTTP Payload'}</dd>
                    </div>
                    <div className="px-4 py-2.5 flex justify-between">
                      <dt className="text-[#95A6BE]">Recorded Timestamp</dt>
                      <dd className="text-[#C1CCDE]">{request.created_at ? new Date(request.created_at).toLocaleString() : '-'}</dd>
                    </div>
                  </dl>
                </div>

                {/* Failover / Attempts Breakdown */}
                {request.attempts && request.attempts.length > 0 && (
                  <div className="rounded-xl bg-[#26364F] border border-[#3B4D66] overflow-hidden">
                    <div className="px-4 py-3 bg-[#223149] border-b border-[#3B4D66] text-xs font-semibold text-[#F0F4FC] flex items-center justify-between">
                      <span>Routing & Failover Attempts</span>
                      <span className="text-[11px] text-[#95A6BE]">{request.attempts.length} attempt(s)</span>
                    </div>
                    <div className="divide-y divide-[#33455E]">
                      {request.attempts.map((att, idx) => (
                        <div key={idx} className="p-4 space-y-1.5 text-xs">
                          <div className="flex items-center justify-between">
                            <span className="font-medium text-[#F0F4FC]">
                              Attempt {att.attempt || idx + 1}: <span className="capitalize">{att.provider}</span> ({att.model})
                            </span>
                            <StatusBadge status={att.success ? 'success' : 'failed'} size="sm" />
                          </div>
                          {att.latency_ms !== undefined && (
                            <p className="text-[11px] text-[#95A6BE]">Attempt latency: {att.latency_ms}ms</p>
                          )}
                          {att.error_message && (
                            <p className="text-[11px] text-[#F18C9C] bg-[#F18C9C]/10 p-2 rounded border border-[#F18C9C]/20 mt-1">
                              {att.error_message}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Audit Record Raw JSON */}
                <div className="rounded-xl bg-[#26364F] border border-[#3B4D66] p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-[#F0F4FC]">Audit Record Payload</span>
                    <span className="text-[11px] text-[#63D6A7] font-medium">SQLite Verified</span>
                  </div>
                  <JsonViewer data={request} maxHeight="240px" />
                </div>
              </>
            )}
          </div>

          {/* Drawer Footer */}
          <div className="px-6 py-4 border-t border-[#3B4D66] bg-[#202E46] flex justify-end">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-[#2D405B] hover:bg-[#354D6E] border border-[#3B4D66] text-xs font-semibold text-[#F0F4FC] transition-colors"
            >
              Close Drawer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
