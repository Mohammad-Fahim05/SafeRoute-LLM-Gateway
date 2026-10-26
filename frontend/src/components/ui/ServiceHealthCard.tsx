import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { StatusBadge, type StatusVariant } from './StatusBadge';

interface DiagnosticItem {
  label: string;
  value: string | number;
  mono?: boolean;
}

interface ServiceHealthCardProps {
  name: string;
  icon: LucideIcon;
  status: string;
  statusVariant?: StatusVariant;
  description: string;
  diagnostics?: DiagnosticItem[];
  lastChecked?: string | Date;
  onAction?: () => void;
  actionLabel?: string;
  isActionLoading?: boolean;
}

export const ServiceHealthCard: React.FC<ServiceHealthCardProps> = ({
  name,
  icon: Icon,
  status,
  statusVariant,
  description,
  diagnostics = [],
  lastChecked,
  onAction,
  actionLabel = 'Check Status',
  isActionLoading = false,
}) => {
  const formattedTime =
    lastChecked instanceof Date
      ? lastChecked.toLocaleTimeString()
      : typeof lastChecked === 'string'
      ? (Number.isNaN(Date.parse(lastChecked)) ? lastChecked : new Date(lastChecked).toLocaleTimeString())
      : 'Just now';

  return (
    <div className="bg-[#26364F] border border-[#3B4D66] rounded-xl p-5 shadow-card flex flex-col justify-between hover:border-[#4A5F7D] transition-colors">
      <div>
        {/* Header with Icon, Name and Status Badge */}
        <div className="flex items-start justify-between gap-3 mb-3.5">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2.5 rounded-lg bg-[#2D405B] border border-[#3B4D66] text-[#82A9FF] flex-shrink-0">
              <Icon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <h3 className="text-[15px] font-semibold text-[#F0F4FC] truncate tracking-tight">
                {name}
              </h3>
              <p className="text-[12px] text-[#95A6BE] truncate mt-0.5">
                {description}
              </p>
            </div>
          </div>
          <StatusBadge status={status} variant={statusVariant} size="sm" />
        </div>

        {/* Diagnostics block */}
        {diagnostics.length > 0 && (
          <div className="my-4 p-3 rounded-lg bg-[#1C2A40] border border-[#33455E] space-y-1.5">
            {diagnostics.map((item, idx) => (
              <div key={idx} className="flex items-center justify-between text-[12px]">
                <span className="text-[#95A6BE]">{item.label}</span>
                <span
                  className={`text-[#F0F4FC] font-medium truncate max-w-[160px] ${
                    item.mono ? 'font-mono text-[11px]' : ''
                  }`}
                >
                  {item.value}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer with Timestamp and Optional Action */}
      <div className="pt-3 border-t border-[#33455E] flex items-center justify-between text-[11px] text-[#95A6BE] mt-2">
        <span>Checked: {formattedTime}</span>
        {onAction && (
          <button
            onClick={onAction}
            disabled={isActionLoading}
            className="text-[#82A9FF] hover:text-[#A4BEFF] font-medium hover:underline transition-colors disabled:opacity-50"
          >
            {isActionLoading ? 'Checking...' : actionLabel}
          </button>
        )}
      </div>
    </div>
  );
};
