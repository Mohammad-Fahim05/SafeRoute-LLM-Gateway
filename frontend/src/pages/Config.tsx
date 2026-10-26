import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeader } from '../components/ui/PageHeader';
import { SectionCard } from '../components/ui/SectionCard';
import { JsonViewer } from '../components/ui/JsonViewer';
import { Button } from '../components/ui/Button';
import {
  Settings,
  ShieldCheck,
  Terminal,
  Layers,
  Copy,
  Check,
  ShieldAlert,
  KeyRound,
} from 'lucide-react';
import type { GatewayConfig } from '../types';

export const Config: React.FC = () => {
  const { authRequired, isAuthenticated, isAdmin, openAuthModal } = useAuth();
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null);

  const canAccessConfig = !authRequired || (isAuthenticated && isAdmin);

  const { data: config } = useQuery<GatewayConfig>({
    queryKey: ['gatewayConfig'],
    queryFn: () => api.getGatewayConfig(),
    enabled: canAccessConfig,
  });

  const copyToClipboard = (cmd: string, key: string) => {
    navigator.clipboard.writeText(cmd);
    setCopiedCmd(key);
    setTimeout(() => setCopiedCmd(null), 2000);
  };

  const commands = [
    {
      key: 'backend',
      label: 'Start Backend Server (Windows PowerShell)',
      cmd: 'python -m uvicorn app.main:app --host 127.0.0.1 --port 8000',
    },
    {
      key: 'frontend',
      label: 'Start Frontend Dev Server (Vite)',
      cmd: 'cd frontend; npm run dev -- --host 127.0.0.1 --port 5173',
    },
    {
      key: 'test',
      label: 'Run Full Regression Test Suite (Pytest)',
      cmd: 'pytest -v',
    },
    {
      key: 'benchmark',
      label: 'Run Separated Performance Benchmarks',
      cmd: 'python scripts/benchmark_hardening_verified.py',
    },
    {
      key: 'ollama',
      label: 'Pull Recommended Local Ollama Model',
      cmd: 'ollama pull llama3.2:1b',
    },
  ];

  return (
    <div className="space-y-7">
      {/* Header */}
      <PageHeader
        title="Configuration & Documentation"
        subtitle="Sanitized runtime gateway parameters, operational runbooks, and developer command cheatsheets."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Config' }]}
      />

      {/* Architecture Overview Flow inside SectionCard */}
      <SectionCard
        title="Gateway Execution Pipeline Lifecycle"
        subtitle="Ordered request lifecycle from ingress authentication to response dispatch and audit persistence"
        icon={Layers}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3 text-center text-xs">
          <div className="p-3.5 bg-[#1C2A40] rounded-xl border border-[#33455E] flex flex-col justify-center items-center">
            <span className="text-[10px] uppercase font-mono font-medium text-[#95A6BE]">Step 1</span>
            <span className="font-semibold text-[#F0F4FC] mt-1 text-xs">Bearer Token</span>
            <span className="text-[11px] text-[#82A9FF] font-mono mt-0.5">HMAC-SHA256</span>
          </div>
          <div className="p-3.5 bg-[#1C2A40] rounded-xl border border-[#33455E] flex flex-col justify-center items-center">
            <span className="text-[10px] uppercase font-mono font-medium text-[#95A6BE]">Step 2</span>
            <span className="font-semibold text-[#F0F4FC] mt-1 text-xs">Rate Limiter</span>
            <span className="text-[11px] text-[#B1A0F8] font-mono mt-0.5">Redis Lua Window</span>
          </div>
          <div className="p-3.5 bg-[#1C2A40] rounded-xl border border-[#33455E] flex flex-col justify-center items-center">
            <span className="text-[10px] uppercase font-mono font-medium text-[#95A6BE]">Step 3</span>
            <span className="font-semibold text-[#F0F4FC] mt-1 text-xs">Input Guardrails</span>
            <span className="text-[11px] text-[#61C7B2] font-mono mt-0.5">PII & Injection</span>
          </div>
          <div className="p-3.5 bg-[#1C2A40] rounded-xl border border-[#33455E] flex flex-col justify-center items-center">
            <span className="text-[10px] uppercase font-mono font-medium text-[#95A6BE]">Step 4</span>
            <span className="font-semibold text-[#F0F4FC] mt-1 text-xs">Exact Cache</span>
            <span className="text-[11px] text-[#85B8F9] font-mono mt-0.5">SHA-256 Match</span>
          </div>
          <div className="p-3.5 bg-[#1C2A40] rounded-xl border border-[#33455E] flex flex-col justify-center items-center">
            <span className="text-[10px] uppercase font-mono font-medium text-[#95A6BE]">Step 5</span>
            <span className="font-semibold text-[#F0F4FC] mt-1 text-xs">Local Inference</span>
            <span className="text-[11px] text-[#63D6A7] font-mono mt-0.5">Ollama (11434)</span>
          </div>
          <div className="p-3.5 bg-[#1C2A40] rounded-xl border border-[#33455E] flex flex-col justify-center items-center">
            <span className="text-[10px] uppercase font-mono font-medium text-[#95A6BE]">Step 6</span>
            <span className="font-semibold text-[#F0F4FC] mt-1 text-xs">Audit & Metrics</span>
            <span className="text-[11px] text-[#F2C777] font-mono mt-0.5">SQLite & Prometheus</span>
          </div>
        </div>
      </SectionCard>

      {/* Developer Command Cheatsheet */}
      <SectionCard
        title="Operational Startup Commands"
        subtitle="Developer terminal commands for starting and verifying the gateway daemon stack"
        icon={Terminal}
      >
        <div className="space-y-3">
          {commands.map((c) => (
            <div
              key={c.key}
              className="p-3.5 bg-[#1C2A40] rounded-xl border border-[#33455E] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"
            >
              <div>
                <span className="text-[11px] font-medium text-[#95A6BE] block">{c.label}</span>
                <code className="text-xs text-[#F0F4FC] font-mono selection:bg-[#82A9FF]/30 mt-0.5 block">
                  {c.cmd}
                </code>
              </div>
              <Button
                onClick={() => copyToClipboard(c.cmd, c.key)}
                variant="outline"
                size="sm"
                icon={copiedCmd === c.key ? Check : Copy}
              >
                {copiedCmd === c.key ? 'Copied' : 'Copy'}
              </Button>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Sanitized Runtime Configuration JSON */}
      <SectionCard
        title="Active Runtime Settings (Sanitized)"
        subtitle="Reflects active environment parameters. All secrets, keys, and credentials are permanently masked."
        icon={Settings}
        actions={
          <span className="flex items-center gap-1.5 text-xs text-[#63D6A7] font-medium">
            <ShieldCheck className="w-4 h-4" /> Secrets Masked
          </span>
        }
      >
        {authRequired && !isAuthenticated ? (
          <div className="p-8 rounded-xl bg-[#1C2A40] border border-[#3B4D66] text-center max-w-md mx-auto my-4">
            <KeyRound className="w-8 h-8 text-[#82A9FF] mx-auto mb-2.5" />
            <h4 className="text-sm font-semibold text-[#F0F4FC] mb-1">Authentication Required</h4>
            <p className="text-xs text-[#C1CCDE] mb-4">
              Authentication required to inspect active gateway configuration.
            </p>
            <Button onClick={openAuthModal} variant="primary" size="sm" icon={KeyRound}>
              Authenticate
            </Button>
          </div>
        ) : authRequired && !isAdmin ? (
          <div className="p-8 rounded-xl bg-[#1C2A40] border border-[#F18C9C]/30 text-center max-w-md mx-auto my-4">
            <ShieldAlert className="w-8 h-8 text-[#F18C9C] mx-auto mb-2.5" />
            <h4 className="text-sm font-semibold text-[#F0F4FC] mb-1">Administrative Access Required</h4>
            <p className="text-xs text-[#C1CCDE] mb-4">
              Runtime gateway configuration inspection is restricted to administrator keys.
            </p>
            <Button onClick={openAuthModal} variant="secondary" size="sm" icon={KeyRound}>
              Switch Key
            </Button>
          </div>
        ) : (
          <JsonViewer data={config} maxHeight="340px" />
        )}
      </SectionCard>
    </div>
  );
};
