import React from 'react';
import type { LucideIcon } from 'lucide-react';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'outline';
export type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: LucideIcon;
  iconPosition?: 'left' | 'right';
  isLoading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'secondary',
  size = 'md',
  icon: Icon,
  iconPosition = 'left',
  isLoading = false,
  className = '',
  disabled,
  ...props
}) => {
  const baseClasses =
    'inline-flex items-center justify-center font-medium rounded-lg transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-[#82A9FF]/50 disabled:opacity-50 disabled:cursor-not-allowed select-none';

  const variantClasses: Record<ButtonVariant, string> = {
    primary:
      'bg-[#82A9FF] hover:bg-[#A4BEFF] text-[#121A2B] font-semibold shadow-sm active:bg-[#6D95EC]',
    secondary:
      'bg-[#2D405B] hover:bg-[#354D6E] text-[#F0F4FC] border border-[#3B4D66] active:bg-[#25364D]',
    outline:
      'bg-transparent hover:bg-[#2D405B] text-[#C1CCDE] hover:text-[#F0F4FC] border border-[#3B4D66]',
    danger:
      'bg-[#F18C9C]/15 hover:bg-[#F18C9C]/25 text-[#F18C9C] border border-[#F18C9C]/30',
    ghost:
      'bg-transparent hover:bg-[#2D405B]/60 text-[#C1CCDE] hover:text-[#F0F4FC]',
  };

  const sizeClasses: Record<ButtonSize, string> = {
    sm: 'h-[32px] px-3 text-[12px] gap-1.5',
    md: 'h-[38px] px-4 text-[13px] gap-2',
    lg: 'h-[44px] px-5 text-[14px] gap-2.5',
  };

  return (
    <button
      className={`${baseClasses} ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin flex-shrink-0" />
      ) : Icon && iconPosition === 'left' ? (
        <Icon className="w-4 h-4 flex-shrink-0" />
      ) : null}
      <span>{children}</span>
      {!isLoading && Icon && iconPosition === 'right' && (
        <Icon className="w-4 h-4 flex-shrink-0" />
      )}
    </button>
  );
};
