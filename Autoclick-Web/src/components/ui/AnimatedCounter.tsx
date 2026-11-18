"use client";
import { useEffect, useRef, useState } from "react";
import { animate, useReducedMotion } from "framer-motion";
import { formatNumber } from "../../lib/formatters";

export function AnimatedCounter({
  value,
  duration = 1,
  formatter = formatNumber,
  className = "",
}: {
  value: number;
  duration?: number;
  formatter?: (value: number) => string;
  className?: string;
}) {
  const reduceMotion = useReducedMotion();
  const [display, setDisplay] = useState(0);
  const fromRef = useRef(0);
  const mountedRef = useRef(false);

  useEffect(() => {
    if (reduceMotion) {
      setDisplay(value);
      fromRef.current = value;
      return;
    }
    const from = mountedRef.current ? fromRef.current : 0;
    mountedRef.current = true;
    const controls = animate(from, value, {
      duration,
      ease: "easeOut",
      onUpdate: (latest) => setDisplay(Math.round(latest)),
      onComplete: () => {
        fromRef.current = value;
      },
    });
    return () => controls.stop();
  }, [value, duration, reduceMotion]);

  return <span className={className}>{formatter(display)}</span>;
}
