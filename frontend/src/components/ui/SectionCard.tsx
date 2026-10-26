import React from 'react';
import type { LucideIcon } from 'lucide-react';

interface SectionCardProps {
  title?: string;
  subtitle?: string;
  icon?: LucideIcon | React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  headerClassName?: string;
  bodyClassName?: string;
  noPadding?: boolean;
}

export const SectionCard: React.FC<SectionCardProps> = ({
  title,
  subtitle,
  icon,
  actions,
  children,
  className = '',
  headerClassName = '',
  bodyClassName = '',
  noPadding = false,
}) => {
  const hasHeader = title || subtitle || icon || actions;

  const renderIcon = () => {
    if (!icon) return null;
    if (React.isValidElement(icon)) {
      return icon;
    }
    const IconComp = icon as LucideIcon;
    return (
      <div className="p-2 rounded-lg bg-[#2D405B] border border-[#3B4D66] text-[#82A9FF] flex-shrink-0">
        <IconComp className="w-4 h-4" />
      </div>
    );
  };

  return (
    <div
      className={`bg-[#26364F] border border-[#3B4D66] rounded-xl shadow-card transition-colors duration-200 overflow-hidden ${className}`}
    >
      {hasHeader && (
        <div
          className={`px-5 py-4 bg-[#223149] border-b border-[#33455E] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 ${headerClassName}`}
        >
          <div className="flex items-center gap-3 min-w-0">
            {renderIcon()}
            <div className="min-w-0">
              {title && (
                <h3 className="text-[15px] sm:text-[16px] font-semibold text-[#F0F4FC] tracking-tight truncate">
                  {title}
                </h3>
              )}
              {subtitle && (
                <p className="text-[12px] sm:text-[13px] text-[#95A6BE] mt-0.5 truncate">
                  {subtitle}
                </p>
              )}
            </div>
          </div>

          {actions && (
            <div className="flex items-center gap-2.5 flex-shrink-0 self-start sm:self-center">
              {actions}
            </div>
          )}
        </div>
      )}

      <div className={noPadding ? bodyClassName : `p-5 sm:p-6 ${bodyClassName}`}>
        {children}
      </div>
    </div>
  );
};
