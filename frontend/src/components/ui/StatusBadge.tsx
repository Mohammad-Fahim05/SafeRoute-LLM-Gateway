import React from 'react';

export type StatusVariant = 'success' | 'healthy' | 'warning' | 'degraded' | 'error' | 'unavailable' | 'info' | 'neutral' | 'disabled';

interface StatusBadgeProps {
  status: string;
  variant?: StatusVariant;
  size?: 'sm' | 'md' | 'lg';
  dot?: boolean;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  variant,
  size = 'md',
  dot = true,
  className = '',
}) => {
  // Infer variant from status string if not explicitly passed
  const resolvedVariant: StatusVariant =
    variant ||
    (() => {
      const lower = status.toLowerCase();
      if (['healthy', 'connected', 'online', 'active', 'ok', 'success', '200', 'pass'].includes(lower)) return 'success';
      if (['degraded', 'warning', 'slow', 'fallback', 'rate_limited'].includes(lower)) return 'warning';
      if (['error', 'unavailable', 'down', 'failed', '500', '502', '503', '504'].includes(lower)) return 'error';
      if (['info', 'mock', 'hit', 'cached', 'streaming'].includes(lower)) return 'info';
      if (['disabled', 'off', 'inactive'].includes(lower)) return 'disabled';
      return 'neutral';
    })();

  const styles: Record<StatusVariant, { bg: string; text: string; border: string; dotBg: string }> = {
    success: {
      bg: 'bg-[#63D6A7]/10',
      text: 'text-[#63D6A7]',
      border: 'border-[#63D6A7]/30',
      dotBg: 'bg-[#63D6A7]',
    },
    healthy: {
      bg: 'bg-[#63D6A7]/10',
      text: 'text-[#63D6A7]',
      border: 'border-[#63D6A7]/30',
      dotBg: 'bg-[#63D6A7]',
    },
    warning: {
      bg: 'bg-[#F2C777]/10',
      text: 'text-[#F2C777]',
      border: 'border-[#F2C777]/30',
      dotBg: 'bg-[#F2C777]',
    },
    degraded: {
      bg: 'bg-[#F2C777]/10',
      text: 'text-[#F2C777]',
      border: 'border-[#F2C777]/30',
      dotBg: 'bg-[#F2C777]',
    },
    error: {
      bg: 'bg-[#F18C9C]/10',
      text: 'text-[#F18C9C]',
      border: 'border-[#F18C9C]/30',
      dotBg: 'bg-[#F18C9C]',
    },
    unavailable: {
      bg: 'bg-[#F18C9C]/10',
      text: 'text-[#F18C9C]',
      border: 'border-[#F18C9C]/30',
      dotBg: 'bg-[#F18C9C]',
    },
    info: {
      bg: 'bg-[#85B8F9]/10',
      text: 'text-[#85B8F9]',
      border: 'border-[#85B8F9]/30',
      dotBg: 'bg-[#85B8F9]',
    },
    disabled: {
      bg: 'bg-[#95A6BE]/10',
      text: 'text-[#95A6BE]',
      border: 'border-[#95A6BE]/30',
      dotBg: 'bg-[#95A6BE]',
    },
    neutral: {
      bg: 'bg-[#2D405B]',
      text: 'text-[#C1CCDE]',
      border: 'border-[#3B4D66]',
      dotBg: 'bg-[#95A6BE]',
    },
  };

  const current = styles[resolvedVariant];

  const sizeClasses = {
    sm: 'text-[11px] px-2 py-0.5 gap-1.5',
    md: 'text-[12px] px-2.5 py-1 gap-1.5',
    lg: 'text-[13px] px-3 py-1.5 gap-2',
  }[size];

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium border ${current.bg} ${current.text} ${current.border} ${sizeClasses} ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${current.dotBg} flex-shrink-0`} />}
      <span className="capitalize leading-none">{status}</span>
    </span>
  );
};
