import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';

export type MascotState = 'idle' | 'wave' | 'present' | 'thinking' | 'celebrate' | 'walk' | 'face';

const sources: Record<MascotState, string> = {
  idle: '/mascot/AutoClick_Robot_Neutral.png',
  wave: '/mascot/wave.png',
  present: '/mascot/AutoClick_Robot_Explicando.png',
  thinking: '/mascot/AutoClick_Robot_Pensando.png',
  celebrate: '/mascot/AutoClick_Robot_Exito.png',
  walk: '/mascot/AutoClick_Robot_Caminando.png',
  face: '/mascot/face.png',
};

const descriptions: Record<MascotState, string> = {
  idle: 'ClickIA, la mascota de AutoClick',
  wave: 'ClickIA saludando',
  present: 'ClickIA presentando',
  thinking: 'ClickIA pensando',
  celebrate: 'ClickIA celebrando',
  walk: 'ClickIA caminando',
  face: 'ClickIA',
};

type Props = {
  size?: number;
  className?: string;
  decorative?: boolean;
  float?: boolean;
  interactive?: boolean;
  state?: MascotState;
  entrance?: 'default' | 'bounce' | 'soft';
  blink?: boolean;
};

export function Mascot({
  size = 96,
  className = '',
  decorative = true,
  float = true,
  interactive = true,
  state = 'wave',
  entrance = 'default',
  blink = true,
}: Props) {
  const reduceMotion = useReducedMotion();
  const shouldFloat = float && !reduceMotion;
  const bounce = entrance === 'bounce' && !reduceMotion;
  const soft = entrance === 'soft' && !reduceMotion;

  return (
    <AnimatePresence initial={bounce || soft} mode="wait">
      <motion.span
        animate={{ opacity: 1, scale: 1, rotate: 0, y: 0 }}
        className={`relative inline-block shrink-0 ${className}`}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.94 }}
        initial={
          reduceMotion
            ? { opacity: 0 }
            : bounce
              ? { opacity: 0, scale: 0, y: -40 }
              : soft
                ? { opacity: 0, scale: 0.9, y: 10 }
                : { opacity: 0, scale: 0.82, rotate: -8 }
        }
        key={state}
        style={{ width: size }}
        transition={
          reduceMotion
            ? { duration: 0.12 }
            : bounce
              ? { type: 'spring', stiffness: 420, damping: 12 }
              : soft
                ? { type: 'spring', stiffness: 220, damping: 22 }
                : { type: 'spring', stiffness: 260, damping: 14 }
        }
        whileHover={interactive ? { scale: 1.08, rotate: -4 } : undefined}
        whileTap={interactive ? { scale: 0.94, rotate: 0 } : undefined}
      >
        <motion.img
          alt={decorative ? '' : descriptions[state]}
          animate={{
            y: shouldFloat ? (state === 'walk' ? [0, -4, 0] : [0, -7, 0]) : 0,
            x: shouldFloat && state === 'walk' ? [-3, 3, -3] : 0,
            rotate: shouldFloat && state === 'wave' ? [0, -8, 5, 0] : 0,
          }}
          className="pointer-events-none block w-full origin-bottom select-none"
          decoding="async"
          src={sources[state]}
          transition={{
            y: shouldFloat
              ? state === 'walk'
                ? { duration: 0.7, repeat: Infinity, ease: 'easeInOut' }
                : { duration: 3, repeat: Infinity, ease: 'easeInOut' }
              : { duration: 0.2 },
            x:
              shouldFloat && state === 'walk'
                ? { duration: 0.7, repeat: Infinity, ease: 'easeInOut' }
                : { duration: 0.2 },
            rotate: shouldFloat && state === 'wave'
              ? { duration: 1.6, repeat: Infinity, repeatDelay: 3.6, ease: 'easeInOut' }
              : { duration: 0.2 },
          }}
        />
        {state === 'face' && !reduceMotion && blink ? (
          <motion.span
            animate={{ opacity: [0, 0, 1, 1, 0, 0] }}
            aria-hidden="true"
            className="pointer-events-none absolute rounded-[50%] bg-[#eef4fd] blur-[1px]"
            style={{ left: '22%', top: '47%', width: '56%', height: '17%' }}
            transition={{ duration: 2.8, ease: 'easeInOut', repeat: Infinity, times: [0, 0.7, 0.78, 0.86, 0.94, 1] }}
          />
        ) : null}
      </motion.span>
    </AnimatePresence>
  );
}
