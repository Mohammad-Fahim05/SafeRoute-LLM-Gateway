import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeader } from '../components/ui/PageHeader';
import { MetricCard } from '../components/ui/MetricCard';
import { SectionCard } from '../components/ui/SectionCard';
import { Button } from '../components/ui/Button';
import {
  Zap,
  Download,
  DollarSign,
  PieChart as PieIcon,
  BarChart2,
  TrendingUp,
  Cpu,
  RefreshCw,
  Info,
  KeyRound,
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  PieChart,
  Pie
} from 'recharts';
import type { OverviewTelemetry } from '../types';

export const Usage: React.FC = () => {
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
          title="Usage & Token Analytics"
          subtitle="Audit token consumption, model allocation, and truthful cost accounting."
          breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Usage' }]}
        />
        <div className="p-8 sm:p-12 rounded-xl bg-[#26364F] border border-[#3B4D66] text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/10 text-[#82A9FF] flex items-center justify-center mx-auto mb-4 border border-[#82A9FF]/20">
            <KeyRound className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-[#F0F4FC]">Authentication Required</h3>
          <p className="text-sm text-[#C1CCDE] mt-1.5 mb-6">
            Authenticate with a client API key to observe token consumption metrics and export usage.
          </p>
          <Button onClick={openAuthModal} variant="primary" icon={KeyRound}>
            Authenticate Console
          </Button>
        </div>
      </div>
    );
  }

  const totalTokens = overview?.total_tokens || 0;
  const totalRequests = overview?.total_requests || 1;
  const avgTokensPerRequest = Math.round(totalTokens / Math.max(1, totalRequests));

  // Compute simulated avoided cloud cost
  const simulatedAvoidedCost = ((totalTokens / 1000) * 0.005).toFixed(4);

  // Compute model allocation from real overview counts
  const modelUsageData = overview?.model_counts && Object.keys(overview.model_counts).length > 0
    ? Object.entries(overview.model_counts).map(([name, reqCount]) => {
        const ratio = reqCount / totalRequests;
        return {
          name,
          tokens: Math.round(totalTokens * ratio),
          requests: reqCount,
        };
      })
    : [
        { name: 'llama3.2:1b', tokens: totalTokens, requests: totalRequests },
      ];

  const COLORS = ['#82A9FF', '#61C7B2', '#B1A0F8', '#85B8F9', '#F2C777'];

  const handleExportCsv = async () => {
    try {
      const blob = await api.exportUsageCsv();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `saferoute-usage-export-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(`Export failed: ${err.message}`);
    }
  };

  return (
    <div className="space-y-7">
      {/* Header */}
      <PageHeader
        title="Usage & Token Analytics"
        subtitle="Audit token consumption, model allocation, and truthful cost accounting."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Usage' }]}
        actions={
          <div className="flex items-center gap-2.5">
            <Button
              onClick={handleExportCsv}
              variant="primary"
              size="md"
              icon={Download}
            >
              Export Usage CSV
            </Button>
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
          </div>
        }
      />

      {/* Transparent Cost Notice */}
      <div className="bg-[#26364F] border border-[#3B4D66] rounded-xl p-4 flex items-start gap-3 shadow-card">
        <Info className="w-5 h-5 text-[#82A9FF] flex-shrink-0 mt-0.5" />
        <div className="text-[13px] text-[#C1CCDE] leading-relaxed">
          <span className="font-semibold text-[#F0F4FC]">Transparent Cost Accounting: </span>
          Ollama processes completions entirely on local hardware with <strong className="text-[#63D6A7] font-semibold">$0.00 in cloud API charges</strong>. Displayed cost savings reflect simulated commercial cloud pricing (e.g. GPT-4o equivalents at ~$5.00 / 1M tokens) avoided by hosting models locally.
        </div>
      </div>

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <MetricCard
          title="Total Tokens Processed"
          value={totalTokens.toLocaleString()}
          subtitle="Prompt + completion volume"
          icon={Zap}
          accentColor="violet"
        />
        <MetricCard
          title="Avg Tokens / Request"
          value={avgTokensPerRequest.toLocaleString()}
          subtitle="Mean workload complexity"
          icon={TrendingUp}
          accentColor="info"
        />
        <MetricCard
          title="Actual Incurred Cost"
          value="$0.0000"
          subtitle="100% Local GPU/CPU inference"
          icon={DollarSign}
          accentColor="success"
        />
        <MetricCard
          title="Estimated Cloud Savings"
          value={`$${simulatedAvoidedCost}`}
          subtitle="Compared to commercial cloud APIs"
          icon={Cpu}
          accentColor="teal"
        />
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Token Allocation by Model */}
        <SectionCard
          title="Token Distribution by Model"
          subtitle="Aggregated volume allocated per local model target"
          icon={BarChart2}
        >
          <div className="h-64 pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={modelUsageData}>
                <XAxis dataKey="name" stroke="#95A6BE" fontSize={11} tickLine={false} />
                <YAxis stroke="#95A6BE" fontSize={11} tickLine={false} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#202E46',
                    borderColor: '#3B4D66',
                    borderRadius: '8px',
                    color: '#F0F4FC',
                    fontSize: '12px',
                  }}
                />
                <Bar dataKey="tokens" radius={[4, 4, 0, 0]}>
                  {modelUsageData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        {/* Requests Share */}
        <SectionCard
          title="Request Share by Model"
          subtitle="Proportional request count distribution"
          icon={PieIcon}
        >
          <div className="h-56 flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={modelUsageData}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={80}
                  paddingAngle={4}
                  dataKey="requests"
                >
                  {modelUsageData.map((_, index) => (
                    <Cell key={`pie-cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#202E46',
                    borderColor: '#3B4D66',
                    borderRadius: '8px',
                    color: '#F0F4FC',
                    fontSize: '12px',
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex justify-center gap-4 text-xs pt-3 border-t border-[#33455E]">
            {modelUsageData.map((item, idx) => (
              <div key={item.name} className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }}></span>
                <span className="text-[#C1CCDE] font-mono text-xs">{item.name}</span>
              </div>
            ))}
          </div>
        </SectionCard>
      </div>
    </div>
  );
};
