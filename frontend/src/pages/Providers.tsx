import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeader } from '../components/ui/PageHeader';
import { SectionCard } from '../components/ui/SectionCard';
import { StatusBadge } from '../components/ui/StatusBadge';
import { Button } from '../components/ui/Button';
import {
  Server,
  Cpu,
  Layers,
  CheckCircle2,
  RefreshCw,
  KeyRound,
  ShieldCheck,
} from 'lucide-react';
import type { ProvidersStatus } from '../types';

export const Providers: React.FC = () => {
  const { authRequired, isAuthenticated, openAuthModal } = useAuth();

  const { data, refetch, isFetching } = useQuery<ProvidersStatus>({
    queryKey: ['providersStatus'],
    queryFn: () => api.getProvidersStatus(),
    enabled: !authRequired || isAuthenticated,
  });

  if (authRequired && !isAuthenticated) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Providers & Routing Engine"
          subtitle="Local AI inference runtime registry, model capabilities, and automated failover orchestration."
          breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Providers' }]}
        />
        <div className="p-8 sm:p-12 rounded-xl bg-[#26364F] border border-[#3B4D66] text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/10 text-[#82A9FF] flex items-center justify-center mx-auto mb-4 border border-[#82A9FF]/20">
            <KeyRound className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-[#F0F4FC]">Authentication Required</h3>
          <p className="text-sm text-[#C1CCDE] mt-1.5 mb-6">
            Authenticate with a client API key to inspect inference runtimes and model capabilities.
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
      {/* Header */}
      <PageHeader
        title="Providers & Routing Engine"
        subtitle="Local AI inference runtime registry, model capabilities, and automated failover orchestration."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Providers' }]}
        actions={
          <Button
            onClick={() => refetch()}
            disabled={isFetching}
            variant="secondary"
            size="md"
            icon={RefreshCw}
            isLoading={isFetching}
          >
            Probe Runtime
          </Button>
        }
      />

      {/* Scope Architecture Banner */}
      <div className="bg-[#26364F] border border-[#3B4D66] rounded-xl p-4 flex items-start gap-3 shadow-card">
        <ShieldCheck className="w-5 h-5 text-[#63D6A7] flex-shrink-0 mt-0.5" />
        <div className="text-[13px] text-[#C1CCDE] leading-relaxed">
          <span className="font-semibold text-[#F0F4FC]">Offline Local Architecture: </span>
          SafeRoute operates as a completely local AI inference gateway powered by <strong className="text-[#63D6A7] font-semibold">Ollama Local Runtime</strong> on port 11434 with zero external cloud dependencies, guaranteed data privacy, and $0.0000 API egress cost.
        </div>
      </div>

      {/* Provider Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Ollama Local Provider Card */}
        <SectionCard
          title="Ollama Runtime"
          subtitle="Primary local inference execution engine"
          icon={Cpu}
          actions={
            <StatusBadge
              status={data?.ollama?.is_online ? 'Online' : 'Offline'}
              variant={data?.ollama?.is_online ? 'success' : 'error'}
              size="sm"
            />
          }
        >
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
                <span className="text-[#95A6BE] text-[11px] block">Endpoint URL</span>
                <span className="text-[#F0F4FC] font-mono text-[11px] font-medium truncate block mt-0.5">
                  {data?.ollama?.base_url || 'http://localhost:11434'}
                </span>
              </div>
              <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
                <span className="text-[#95A6BE] text-[11px] block">Pulled Models</span>
                <span className="text-[#82A9FF] font-mono text-xs font-semibold block mt-0.5">
                  {data?.ollama?.pulled_models?.length || 0} models ready
                </span>
              </div>
            </div>

            {/* Model Tags */}
            <div className="space-y-2">
              <span className="text-[11px] font-medium text-[#95A6BE] uppercase tracking-wider block">
                Installed Models:
              </span>
              {data?.ollama?.pulled_models && data.ollama.pulled_models.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {data.ollama.pulled_models.map((m: string) => (
                    <span
                      key={m}
                      className="px-2.5 py-1 bg-[#1C2A40] text-[#F0F4FC] font-mono text-xs rounded-lg border border-[#3B4D66]"
                    >
                      {m}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-[#95A6BE] italic">
                  No local models detected on port 11434. Run `ollama pull llama3.2:1b` in terminal.
                </p>
              )}
            </div>
          </div>
        </SectionCard>

        {/* Mock Provider Card */}
        <SectionCard
          title="MockProvider Double"
          subtitle="Deterministic in-memory test double for testing and benchmarks"
          icon={Server}
          actions={
            <StatusBadge status="Test Double" variant="info" size="sm" />
          }
        >
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
                <span className="text-[#95A6BE] text-[11px] block">Synthetic Latency</span>
                <span className="text-[#F0F4FC] font-mono text-xs font-medium block mt-0.5">10 - 50 ms</span>
              </div>
              <div className="p-3 bg-[#1C2A40] rounded-lg border border-[#33455E]">
                <span className="text-[#95A6BE] text-[11px] block">Execution Scope</span>
                <span className="text-[#F0F4FC] text-xs font-medium block mt-0.5">CI/CD & Benchmarks</span>
              </div>
            </div>

            <p className="text-xs text-[#C1CCDE] leading-relaxed">
              Provides deterministic, ultra-fast mock completions during automated pytest suites and regression verification without requiring active GPU or Ollama daemon processes.
            </p>
          </div>
        </SectionCard>
      </div>

      {/* Capabilities Matrix */}
      <SectionCard
        title="Provider Capability & Feature Matrix"
        subtitle="Feature compliance and failover priority ranking"
        icon={Layers}
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-[13px]">
            <thead>
              <tr className="bg-[#202E46] border-b border-[#3B4D66] text-[#95A6BE] uppercase tracking-wider text-[11px] font-semibold">
                <th className="py-3 px-4">Provider / Model</th>
                <th className="py-3 px-4">Role / Scope</th>
                <th className="py-3 px-4">Chat Completions</th>
                <th className="py-3 px-4">SSE Token Streaming</th>
                <th className="py-3 px-4">Function / Tool Calls</th>
                <th className="py-3 px-4">Routing Tier</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#33455E] text-[#F0F4FC]">
              <tr className="hover:bg-[#2D405B]/40 transition-colors">
                <td className="py-3.5 px-4 font-semibold text-xs flex items-center gap-2">
                  <Cpu className="w-4 h-4 text-[#63D6A7]" />
                  <span>Ollama Local</span>
                </td>
                <td className="py-3.5 px-4">
                  <span className="text-[#63D6A7] font-medium text-xs">Primary Runtime</span>
                </td>
                <td className="py-3.5 px-4">
                  <CheckCircle2 className="w-4 h-4 text-[#63D6A7]" />
                </td>
                <td className="py-3.5 px-4">
                  <CheckCircle2 className="w-4 h-4 text-[#63D6A7]" />
                </td>
                <td className="py-3.5 px-4">
                  <CheckCircle2 className="w-4 h-4 text-[#63D6A7]" />
                </td>
                <td className="py-3.5 px-4 font-mono font-medium text-[#82A9FF] text-xs">Tier 1 (Default)</td>
              </tr>
              <tr className="hover:bg-[#2D405B]/40 transition-colors">
                <td className="py-3.5 px-4 font-semibold text-xs flex items-center gap-2">
                  <Server className="w-4 h-4 text-[#85B8F9]" />
                  <span>MockProvider</span>
                </td>
                <td className="py-3.5 px-4">
                  <span className="text-[#85B8F9] font-medium text-xs">Test Double</span>
                </td>
                <td className="py-3.5 px-4">
                  <CheckCircle2 className="w-4 h-4 text-[#63D6A7]" />
                </td>
                <td className="py-3.5 px-4">
                  <CheckCircle2 className="w-4 h-4 text-[#63D6A7]" />
                </td>
                <td className="py-3.5 px-4">
                  <span className="text-[#95A6BE]">-</span>
                </td>
                <td className="py-3.5 px-4 font-mono text-[#95A6BE] text-xs">Tier 2 (Fallback / CI)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
};
