import type { ComponentPropsWithRef } from 'react';

type Props = ComponentPropsWithRef<'button'> & {
  variant?: 'primary' | 'secondary';
};

const variants = {
  primary:
    'border-transparent bg-primary text-white shadow-[0_1px_2px_rgb(15_23_42/10%)] hover:bg-primary-hover hover:shadow-glow-primary',
  secondary: 'border-border bg-white text-text hover:border-blue-200 hover:bg-blue-50/60',
};

export function Button({ variant = 'primary', className = '', ...props }: Props) {
  return (
    <button
      className={`inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-control border px-4 font-bold transition-[color,background-color,border-color,box-shadow] duration-200 ease-out focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-55 disabled:shadow-none ${variants[variant]} ${className}`}
      {...props}
    />
  );
}
