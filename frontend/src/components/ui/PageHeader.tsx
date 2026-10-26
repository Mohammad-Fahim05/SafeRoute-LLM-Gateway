import React from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  description?: string;
  breadcrumbs?: Array<string | { label: string; href?: string }>;
  actions?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  description,
  breadcrumbs = ['SafeRoute'],
  actions,
}) => {
  const displaySubtitle = description || subtitle;

  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-[#33455E]/60 mb-6">
      <div className="min-w-0">
        {breadcrumbs && breadcrumbs.length > 0 && (
          <nav className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-[#95A6BE] mb-1.5 font-medium">
            {breadcrumbs.map((crumb, idx) => {
              const label = typeof crumb === 'string' ? crumb : crumb.label;
              return (
                <React.Fragment key={idx}>
                  {idx > 0 && <span className="text-[#3B4D66]">/</span>}
                  <span className={idx === breadcrumbs.length - 1 ? 'text-[#82A9FF]' : 'text-[#95A6BE] hover:text-[#C1CCDE]'}>
                    {label}
                  </span>
                </React.Fragment>
              );
            })}
          </nav>
        )}
        <h1 className="text-[28px] sm:text-[32px] font-semibold text-[#F0F4FC] tracking-tight leading-tight">
          {title}
        </h1>
        {displaySubtitle && (
          <p className="text-[14px] sm:text-[15px] text-[#C1CCDE] mt-1.5 leading-normal max-w-3xl">
            {displaySubtitle}
          </p>
        )}
      </div>

      {actions && (
        <div className="flex items-center gap-3 flex-shrink-0 self-start sm:self-center">
          {actions}
        </div>
      )}
    </div>
  );
};
