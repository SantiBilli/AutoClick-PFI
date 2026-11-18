import { motion, MotionConfig } from 'framer-motion';
import { Mascot } from '@/components/Mascot';

export function RouteLoading({ label }: { label: string }) {
  return (
    <MotionConfig reducedMotion="user">
      <motion.div
        animate={{ opacity: 1 }}
        className="grid min-h-[60vh] w-full place-items-center"
        initial={{ opacity: 0 }}
        role="status"
        transition={{ duration: 0.25, delay: 0.15 }}
      >
        <div className="flex flex-col items-center gap-3">
          <Mascot interactive={false} size={72} state="walk" />
          <p className="m-0 text-[13px] font-bold text-text-muted">{label}</p>
        </div>
      </motion.div>
    </MotionConfig>
  );
}
