import { motion } from 'framer-motion';

type Props = {
  size?: number;
  variant?: 'light' | 'dark';
  className?: string;
};

const sources = {
  light: '/imgs/AutoClick_Logo_Modo_Claro.png',
  dark: '/imgs/AutoClick_Logo_Modo_Oscuro.png',
} as const;

export function LogoMark({ size = 40, variant = 'light', className = '' }: Props) {
  return (
    <motion.img
      alt=""
      className={`inline-block shrink-0 rounded-xl object-contain ${className}`}
      src={sources[variant]}
      style={{ width: size, height: size }}
      transition={{ type: 'spring', stiffness: 320, damping: 18 }}
      whileHover={{ scale: 1.15 }}
      whileTap={{ scale: 1.05 }}
    />
  );
}
