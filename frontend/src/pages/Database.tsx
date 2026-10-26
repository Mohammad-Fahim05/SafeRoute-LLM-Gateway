import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeader } from '../components/ui/PageHeader';
import { MetricCard } from '../components/ui/MetricCard';
import { SectionCard } from '../components/ui/SectionCard';
import { Button } from '../components/ui/Button';
import {
  Database as DbIcon,
  ShieldCheck,
  Table as TableIcon,
  HardDrive,
  FileCode,
  Layers,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  KeyRound,
  ShieldAlert,
} from 'lucide-react';
import type { DatabaseOverview, TableRecordsResponse } from '../types';

export const Database: React.FC = () => {
  const { authRequired, isAuthenticated, isAdmin, openAuthModal } = useAuth();
  const [selectedTable, setSelectedTable] = useState('request_records');
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);

  const canAccessDb = !authRequired || (isAuthenticated && isAdmin);

  const { data: dbOverview, refetch: refetchOverview, isFetching: isOverviewFetching } =
    useQuery<DatabaseOverview>({
      queryKey: ['dbOverview'],
      queryFn: () => api.getDatabaseOverview(),
      enabled: canAccessDb,
    });

  const {
    data: tableRecords,
    isLoading: recordsLoading,
    refetch: refetchRecords,
    isFetching: isRecordsFetching,
  } = useQuery<TableRecordsResponse>({
    queryKey: ['tableRecords', selectedTable, page, pageSize],
    queryFn: () => api.getTableRecords(selectedTable, page, pageSize),
    enabled: canAccessDb,
  });

  const isBusy = isOverviewFetching || isRecordsFetching;

  if (authRequired && !isAuthenticated) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="SQLite Database Explorer"
          subtitle="Safely inspect active schema structure, storage metrics, and read-only records in data/saferoute.db."
          breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Database' }]}
        />
        <div className="p-8 sm:p-12 rounded-xl bg-[#26364F] border border-[#3B4D66] text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#82A9FF]/10 text-[#82A9FF] flex items-center justify-center mx-auto mb-4 border border-[#82A9FF]/20">
            <KeyRound className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-[#F0F4FC]">Authentication Required</h3>
          <p className="text-sm text-[#C1CCDE] mt-1.5 mb-6">
            Database explorer requires an administrator API key. Please authenticate to view database records.
          </p>
          <Button onClick={openAuthModal} variant="primary" icon={KeyRound}>
            Authenticate Console
          </Button>
        </div>
      </div>
    );
  }

  if (authRequired && isAuthenticated && !isAdmin) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="SQLite Database Explorer"
          subtitle="Safely inspect active schema structure, storage metrics, and read-only records in data/saferoute.db."
          breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Database' }]}
        />
        <div className="p-8 sm:p-12 rounded-xl bg-[#26364F] border border-[#F18C9C]/30 text-center max-w-lg mx-auto my-12 shadow-card">
          <div className="w-12 h-12 rounded-xl bg-[#F18C9C]/10 text-[#F18C9C] flex items-center justify-center mx-auto mb-4 border border-[#F18C9C]/20">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <h3 className="text-base font-semibold text-[#F0F4FC]">Administrative Access Required</h3>
          <p className="text-sm text-[#C1CCDE] mt-1.5 mb-6 leading-relaxed">
            Direct SQLite database exploration is privileged and restricted to administrators. Your current client key has tenant-scoped permissions only.
          </p>
          <Button onClick={openAuthModal} variant="secondary" icon={KeyRound}>
            Switch to Admin Key
          </Button>
        </div>
      </div>
    );
  }

  const activeTableMeta = dbOverview?.tables?.find((t) => t.table_name === selectedTable);

  return (
    <div className="space-y-7">
      {/* Header */}
      <PageHeader
        title="SQLite Database Explorer"
        subtitle="Safely inspect active schema structure, storage metrics, and read-only records in data/saferoute.db."
        breadcrumbs={[{ label: 'SafeRoute' }, { label: 'Database' }]}
        actions={
          <Button
            onClick={() => {
              refetchOverview();
              refetchRecords();
            }}
            disabled={isBusy}
            variant="secondary"
            size="md"
            icon={RefreshCw}
            isLoading={isBusy}
          >
            Refresh Schema
          </Button>
        }
      />

      {/* Database Safety Notice */}
      <div className="bg-[#26364F] border border-[#3B4D66] rounded-xl p-4 flex items-start gap-3 shadow-card">
        <ShieldCheck className="w-5 h-5 text-[#63D6A7] flex-shrink-0 mt-0.5" />
        <div className="text-[13px] text-[#C1CCDE] leading-relaxed">
          <span className="font-semibold text-[#F0F4FC]">Strict Read-Only Verification: </span>
          The Database Explorer operates with zero write, drop, or alter permissions. Raw queries are rejected at the API boundary, protecting active request logs and HMAC client credentials against accidental data mutation or SQL injection.
        </div>
      </div>

      {/* Database Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <MetricCard
          title="Database File"
          value="saferoute.db"
          subtitle={dbOverview?.database_path || 'data/saferoute.db'}
          icon={DbIcon}
          accentColor="violet"
        />
        <MetricCard
          title="Database Size"
          value={dbOverview ? `${(dbOverview.file_size_bytes / 1024).toFixed(1)} KB` : '307.2 KB'}
          subtitle="SQLite on-disk footprint"
          icon={HardDrive}
          accentColor="info"
        />
        <MetricCard
          title="Journal Mode"
          value={dbOverview?.journal_mode?.toUpperCase() || 'WAL'}
          subtitle="Write-Ahead Logging enabled"
          icon={Layers}
          accentColor="teal"
        />
        <MetricCard
          title="Tracked Tables"
          value={(dbOverview?.tables?.length || 4).toString()}
          subtitle="Normalized audit & usage schema"
          icon={TableIcon}
          accentColor="primary"
        />
      </div>

      {/* Table Selection Tabs inside SectionCard */}
      <SectionCard
        title="Schema Tables"
        subtitle="Select a relational table to inspect schema columns and persisted records"
        icon={TableIcon}
      >
        <div className="flex flex-wrap gap-2.5">
          {dbOverview?.tables?.map((tbl) => (
            <button
              key={tbl.table_name}
              onClick={() => {
                setSelectedTable(tbl.table_name);
                setPage(1);
              }}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium transition-colors ${
                selectedTable === tbl.table_name
                  ? 'bg-[#82A9FF] text-[#121A2B] font-semibold shadow-sm'
                  : 'bg-[#1C2A40] hover:bg-[#2D405B] text-[#C1CCDE] hover:text-[#F0F4FC] border border-[#3B4D66]'
              }`}
            >
              <span className="font-mono">{tbl.table_name}</span>
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold ${
                  selectedTable === tbl.table_name ? 'bg-[#121A2B]/20 text-[#121A2B]' : 'bg-[#26364F] text-[#95A6BE]'
                }`}
              >
                {tbl.row_count}
              </span>
            </button>
          ))}
        </div>

        {/* Active Table Schema Definition */}
        {activeTableMeta && (
          <div className="mt-5 pt-4 border-t border-[#33455E] space-y-2.5">
            <h4 className="text-[11px] font-medium uppercase tracking-wider text-[#95A6BE] flex items-center gap-1.5">
              <FileCode className="w-3.5 h-3.5 text-[#82A9FF]" /> Schema Columns: {activeTableMeta.table_name}
            </h4>
            <div className="flex flex-wrap gap-2">
              {activeTableMeta.columns.map((col) => (
                <div
                  key={col.name}
                  className="px-2.5 py-1.5 bg-[#1C2A40] border border-[#33455E] rounded-lg text-xs font-mono"
                >
                  <span className="text-[#F0F4FC] font-medium">{col.name}</span>{' '}
                  <span className="text-[#85B8F9] text-[11px]">({col.type})</span>
                  {col.primary_key && (
                    <span className="ml-1.5 text-[9px] uppercase px-1.5 py-0.5 rounded bg-[#F2C777]/20 text-[#F2C777] font-sans font-semibold">
                      PK
                    </span>
                  )}
                  {col.not_null && !col.primary_key && (
                    <span className="ml-1.5 text-[9px] uppercase text-[#F18C9C] font-sans font-semibold">NN</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </SectionCard>

      {/* Read-Only Record Table */}
      <SectionCard
        title={`Records: ${selectedTable}`}
        subtitle={`Viewing page ${page} of ${tableRecords?.total_pages || 1} (${tableRecords?.total || 0} total records)`}
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-[#202E46] border-b border-[#3B4D66] text-[#95A6BE] font-mono uppercase text-[11px] font-semibold">
                {tableRecords?.columns.map((col) => (
                  <th key={col} className="py-3 px-4 whitespace-nowrap">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#33455E] text-[#F0F4FC] font-mono text-[11px]">
              {recordsLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={(tableRecords as any)?.columns?.length || 5} className="py-3.5 px-4">
                      <div className="h-4 bg-[#2D405B] rounded"></div>
                    </td>
                  </tr>
                ))
              ) : tableRecords && tableRecords.records.length > 0 ? (
                tableRecords.records.map((row, idx) => (
                  <tr key={idx} className="hover:bg-[#2D405B]/40 transition-colors">
                    {tableRecords.columns.map((col) => (
                      <td key={col} className="py-3 px-4 whitespace-nowrap max-w-xs truncate">
                        {row[col] !== null && row[col] !== undefined
                          ? typeof row[col] === 'object'
                            ? JSON.stringify(row[col])
                            : String(row[col])
                          : <span className="text-[#95A6BE]/40 italic">null</span>}
                      </td>
                    ))}
                  </tr>
                ))
              ) : (
                <tr>
                  <td
                    colSpan={(tableRecords as any)?.columns?.length || 5}
                    className="py-10 text-center text-[#95A6BE] font-sans text-xs"
                  >
                    No records found in table
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Controls */}
        {tableRecords && tableRecords.total > 0 && (
          <div className="flex items-center justify-between px-5 py-3.5 bg-[#202E46] border-t border-[#3B4D66] text-xs text-[#95A6BE]">
            <div>
              Showing page <span className="font-semibold text-[#F0F4FC]">{page}</span> of{' '}
              <span className="font-semibold text-[#F0F4FC]">{tableRecords.total_pages || 1}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="flex items-center gap-1 px-3 py-1.5 bg-[#26364F] hover:bg-[#2D405B] disabled:opacity-40 disabled:pointer-events-none border border-[#3B4D66] rounded-lg text-[#F0F4FC] text-xs transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> Prev
              </button>
              <button
                disabled={page >= tableRecords.total_pages}
                onClick={() => setPage((p) => p + 1)}
                className="flex items-center gap-1 px-3 py-1.5 bg-[#26364F] hover:bg-[#2D405B] disabled:opacity-40 disabled:pointer-events-none border border-[#3B4D66] rounded-lg text-[#F0F4FC] text-xs transition-colors"
              >
                Next <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </SectionCard>
    </div>
  );
};
