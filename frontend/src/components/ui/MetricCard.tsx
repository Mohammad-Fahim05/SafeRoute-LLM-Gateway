import React from 'react';
import type { LucideIcon } from 'lucide-react';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  trend?: {
    value: string;
    isPositive?: boolean;
  };
  accentColor?: 'primary' | 'secondary' | 'teal' | 'violet' | 'success' | 'warning' | 'error' | 'info' | 'indigo' | 'blue' | 'cyan' | 'rose';
  isLoading?: boolean;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  accentColor = 'primary',
  isLoading = false,
}) => {
  const colorMap: Record<string, { icon: string; iconBg: string }> = {
    primary: {
      icon: 'text-[#82A9FF]',
      iconBg: 'bg-[#82A9FF]/10 border-[#82A9FF]/20',
    },
    secondary: {
      icon: 'text-[#A4BEFF]',
      iconBg: 'bg-[#A4BEFF]/10 border-[#A4BEFF]/20',
    },
    teal: {
      icon: 'text-[#61C7B2]',
      iconBg: 'bg-[#61C7B2]/10 border-[#61C7B2]/20',
    },
    violet: {
      icon: 'text-[#B1A0F8]',
      iconBg: 'bg-[#B1A0F8]/10 border-[#B1A0F8]/20',
    },
    success: {
      icon: 'text-[#63D6A7]',
      iconBg: 'bg-[#63D6A7]/10 border-[#63D6A7]/20',
    },
    warning: {
      icon: 'text-[#F2C777]',
      iconBg: 'bg-[#F2C777]/10 border-[#F2C777]/20',
    },
    error: {
      icon: 'text-[#F18C9C]',
      iconBg: 'bg-[#F18C9C]/10 border-[#F18C9C]/20',
    },
    info: {
      icon: 'text-[#85B8F9]',
      iconBg: 'bg-[#85B8F9]/10 border-[#85B8F9]/20',
    },
    // Aliases
    indigo: {
      icon: 'text-[#82A9FF]',
      iconBg: 'bg-[#82A9FF]/10 border-[#82A9FF]/20',
    },
    blue: {
      icon: 'text-[#85B8F9]',
      iconBg: 'bg-[#85B8F9]/10 border-[#85B8F9]/20',
    },
    cyan: {
      icon: 'text-[#61C7B2]',
      iconBg: 'bg-[#61C7B2]/10 border-[#61C7B2]/20',
    },
  };

  const currentTheme = colorMap[accentColor] || colorMap.primary;

  if (isLoading) {
    return (
      <div className="bg-[#26364F] border border-[#3B4D66] rounded-xl p-5 shadow-card animate-pulse flex flex-col justify-between min-h-[120px]">
        <div className="flex justify-between items-start mb-3">
          <div className="h-3.5 bg-[#2D405B] rounded w-24"></div>
          <div className="h-8 w-8 bg-[#2D405B] rounded-lg"></div>
        </div>
        <div className="h-8 bg-[#2D405B] rounded w-28 mb-2"></div>
        <div className="h-3 bg-[#2D405B] rounded w-20"></div>
      </div>
    );
  }

  return (
    <div className="bg-[#26364F] border border-[#3B4D66] rounded-xl p-5 shadow-card hover:border-[#4A5F7D] transition-colors flex flex-col justify-between min-h-[120px]">
      <div className="flex justify-between items-start mb-3">
        <span className="text-[#C1CCDE] text-[13px] font-medium tracking-normal truncate max-w-[170px]">
          {title}
        </span>
        <div className={`p-2 rounded-lg border ${currentTheme.iconBg} ${currentTheme.icon} flex-shrink-0`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>

      <div>
        <div className="text-[28px] sm:text-[32px] font-semibold text-[#F0F4FC] tracking-tight leading-none">
          {value}
        </div>
        {(subtitle || trend) && (
          <div className="flex items-center gap-2 mt-2.5 text-[12px]">
            {trend && (
              <span
                className={`font-medium ${
                  trend.isPositive ? 'text-[#63D6A7]' : 'text-[#F18C9C]'
                }`}
              >
                {trend.value}
              </span>
            )}
            {subtitle && (
              <span className="text-[#95A6BE] truncate">{subtitle}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
