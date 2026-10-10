import React from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'danger' | 'ghost' | 'badge';
export type ButtonSize = 'sm' | 'md' | 'lg' | 'icon';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: React.ReactNode;
  isLoading?: boolean;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: 'bg-slate-900 text-white hover:bg-slate-800 active:bg-slate-950 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white shadow-xs border border-transparent font-bold',
  secondary: 'bg-slate-100 text-slate-800 hover:bg-slate-200 active:bg-slate-300 dark:bg-neutral-800 dark:text-neutral-200 dark:hover:bg-neutral-700 border border-slate-200/80 dark:border-neutral-700 font-semibold',
  outline: 'bg-transparent text-slate-700 hover:bg-slate-100 dark:text-neutral-200 dark:hover:bg-neutral-800 border border-slate-300 dark:border-neutral-700 font-semibold',
  danger: 'bg-white hover:bg-rose-50 text-rose-600 dark:bg-neutral-900 dark:text-rose-400 dark:hover:bg-rose-950/30 border border-rose-300 dark:border-rose-800/60 hover:border-rose-400 font-semibold',
  ghost: 'bg-transparent text-slate-600 hover:text-slate-900 hover:bg-slate-100 dark:text-neutral-400 dark:hover:text-white dark:hover:bg-neutral-800 border-0 font-medium',
  badge: 'bg-transparent text-slate-700 dark:text-neutral-300 hover:bg-slate-100 dark:hover:bg-neutral-800 border border-slate-200 dark:border-neutral-700 font-mono uppercase text-xs font-semibold'
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1 text-xs rounded-lg gap-1.5',
  md: 'px-3.5 py-1.5 text-xs rounded-xl gap-2',
  lg: 'px-4 py-2 text-sm rounded-xl gap-2',
  icon: 'p-1.5 rounded-lg'
};

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'secondary',
  size = 'md',
  icon,
  isLoading,
  className = '',
  disabled,
  ...props
}) => {
  const baseClasses = 'inline-flex items-center justify-center transition-all duration-150 select-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-slate-400/40 disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none shadow-xs';
  const variantClass = variantStyles[variant] || variantStyles.secondary;
  const sizeClass = sizeStyles[size] || sizeStyles.md;

  return (
    <button
      disabled={disabled || isLoading}
      className={`${baseClasses} ${variantClass} ${sizeClass} ${className}`}
      {...props}
    >
      {isLoading ? (
        <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin mr-1.5 shrink-0" />
      ) : icon ? (
        <span className="shrink-0 flex items-center">{icon}</span>
      ) : null}
      {children}
    </button>
  );
};

export default Button;