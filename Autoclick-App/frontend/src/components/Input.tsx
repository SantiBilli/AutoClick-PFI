import type { InputHTMLAttributes } from 'react';

export function Input({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`field-control h-[42px] w-full rounded-control bg-white px-3 text-text transition-[border-color,box-shadow] duration-150 ease-out placeholder:text-text-soft disabled:cursor-not-allowed disabled:bg-bg disabled:text-text-muted ${className}`}
      {...props}
    />
  );
}
