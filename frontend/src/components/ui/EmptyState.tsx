import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  action?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon: Icon = Inbox,
  action,
  className = '',
}) => {
  return (
    <div
      className={`p-8 text-center flex flex-col items-center justify-center rounded-xl bg-[#223149] border border-[#3B4D66] ${className}`}
    >
      <div className="w-12 h-12 rounded-xl bg-[#2D405B] border border-[#3B4D66] text-[#95A6BE] flex items-center justify-center mb-3">
        <Icon className="w-6 h-6 text-[#82A9FF]" />
      </div>
      <h4 className="text-[15px] font-semibold text-[#F0F4FC]">{title}</h4>
      {description && (
        <p className="text-[13px] text-[#C1CCDE] mt-1 max-w-sm leading-normal">
          {description}
        </p>
      )}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-4 px-4 py-2 rounded-lg bg-[#82A9FF] hover:bg-[#A4BEFF] text-[#121A2B] text-xs font-semibold shadow-sm transition-colors"
        >
          {action.label}
        </button>
      )}
    </div>
  );
};
