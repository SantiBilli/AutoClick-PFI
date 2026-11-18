import { motion } from 'framer-motion';

type Props = {
  size?: number;
  active?: boolean;
  className?: string;
};

export function AiGlyph({ size = 18, active = false, className = '' }: Props) {
  return (
    <motion.svg
      aria-hidden="true"
      className={className}
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}>
      <motion.line
        animate={active ? { opacity: [1, 0.5, 1] } : undefined}
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.6"
        transition={{ duration: 2, repeat: Infinity }}
        x1="12"
        x2="12"
        y1="2.4"
        y2="5"
      />
      <motion.circle
        animate={active ? { scale: [1, 1.25, 1] } : undefined}
        cx="12"
        cy="1.9"
        fill="currentColor"
        r="1.15"
        style={{ transformOrigin: '12px 1.9px' }}
        transition={{ duration: 2, repeat: Infinity }}
      />
      <rect
        height="12.5"
        rx="4.2"
        stroke="currentColor"
        strokeWidth="1.6"
        width="17"
        x="3.5"
        y="6.2"
      />
      <motion.circle
        animate={active ? { scaleY: [1, 1, 0.15, 1] } : undefined}
        cx="8.6"
        cy="12.4"
        fill="currentColor"
        r="1.5"
        style={{ transformOrigin: '8.6px 12.4px' }}
        transition={{ duration: 3.6, repeat: Infinity, times: [0, 0.85, 0.92, 1] }}
      />
      <motion.circle
        animate={active ? { scaleY: [1, 1, 0.15, 1] } : undefined}
        cx="15.4"
        cy="12.4"
        fill="currentColor"
        r="1.5"
        style={{ transformOrigin: '15.4px 12.4px' }}
        transition={{ duration: 3.6, repeat: Infinity, times: [0, 0.85, 0.92, 1] }}
      />
      <path d="M0.8 10.8v3.2" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" />
      <path d="M23.2 10.8v3.2" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" />
    </motion.svg>
  );
}
