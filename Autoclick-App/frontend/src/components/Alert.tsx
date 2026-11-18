import { motion, useReducedMotion } from 'framer-motion';
import { AlertCircle } from 'lucide-react';
import type { ReactNode } from 'react';
import { easeOutExpo } from '@/lib/motion';

type Props = {
  children: ReactNode;
  className?: string;
  shake?: boolean;
};

export function Alert({ children, className = '', shake = true }: Props) {
  const reduceMotion = Boolean(useReducedMotion());
  const visible = { opacity: 1, height: 'auto', y: 0 };

  return (
    <motion.div
      animate={visible}
      className={`relative flex items-start gap-3 overflow-hidden rounded-control border border-red-100 bg-red-50/80 py-3 pr-3.5 pl-4 ${shake && !reduceMotion ? 'animate-shake' : ''} ${className}`}
      initial={reduceMotion ? visible : { opacity: 0, height: 0, y: -6 }}
      role="alert"
      transition={reduceMotion ? { duration: 0 } : { duration: 0.22, ease: easeOutExpo }}
    >
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-danger" />
      <span
        aria-hidden="true"
        className="grid size-7 shrink-0 place-items-center rounded-full bg-red-100 text-danger"
      >
        <AlertCircle size={15} />
      </span>
      <div className="min-w-0 flex-1 self-center text-[13px] leading-5 text-red-950">
        {children}
      </div>
    </motion.div>
  );
}
