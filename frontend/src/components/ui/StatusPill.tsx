import React from 'react';

interface StatusPillProps {
  status: string | number;
  size?: 'sm' | 'md';
  pulse?: boolean;
}

export const StatusPill: React.FC<StatusPillProps> = ({
  status,
  size = 'md',
  pulse = false,
}) => {
  const str = String(status);
  const norm = str.toLowerCase().trim();

  let styles = 'bg-[#273454] text-[#BBC5E0] border-[#354364]';
  let dotColor = 'bg-[#8E9BBB]';

  if (['200', 'success', 'healthy', 'active', 'online', 'hit', 'exact_hit', 'semantic_hit'].includes(norm)) {
    styles = 'bg-[#54D6A4]/10 text-[#54D6A4] border-[#54D6A4]/30';
    dotColor = 'bg-[#54D6A4]';
  } else if (['400', '401', '403', '404', '429', '500', '502', '503', '504', 'failed', 'error', 'unavailable', 'offline'].includes(norm)) {
    styles = 'bg-[#F47F98]/10 text-[#F47F98] border-[#F47F98]/30';
    dotColor = 'bg-[#F47F98]';
  } else if (['warning', 'degraded'].includes(norm)) {
    styles = 'bg-[#F4C66D]/10 text-[#F4C66D] border-[#F4C66D]/30';
    dotColor = 'bg-[#F4C66D]';
  } else if (['miss', 'exact_miss', 'semantic_miss'].includes(norm)) {
    styles = 'bg-[#60A5FA]/10 text-[#60A5FA] border-[#60A5FA]/30';
    dotColor = 'bg-[#60A5FA]';
  } else if (['bypass', 'disabled', 'not_applicable'].includes(norm)) {
    styles = 'bg-[#7C83FF]/10 text-[#7C83FF] border-[#7C83FF]/30';
    dotColor = 'bg-[#7C83FF]';
  }

  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-[12px]';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium rounded-full border ${sizeClasses} ${styles} whitespace-nowrap`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColor} ${
          pulse ? 'animate-pulse' : ''
        }`}
      />
      <span>{str.replace(/_/g, ' ')}</span>
    </span>
  );
};

export const StatusBadge = StatusPill;
