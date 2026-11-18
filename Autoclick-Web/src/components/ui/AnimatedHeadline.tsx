"use client";

import { motion } from "framer-motion";
import { easeOutExpo, staggerFast, word as wordVariant } from "../../lib/motion";

function stripPunctuation(text: string) {
  return text.replace(/[.,!?¿¡:;]/g, "").toLowerCase();
}

export function AnimatedHeadline({
  as: Tag = "h2",
  text,
  accentWord,
  id,
  className,
}: {
  as?: "h1" | "h2";
  text: string;
  accentWord?: string;
  id?: string;
  className?: string;
}) {
  const words = text.split(" ");
  const strippedWords = words.map(stripPunctuation);
  const accentWords = accentWord ? accentWord.split(" ").map(stripPunctuation) : [];
  let accentStart = -1;
  for (let i = 0; accentWords.length > 0 && i <= strippedWords.length - accentWords.length; i++) {
    if (accentWords.every((w, j) => strippedWords[i + j] === w)) {
      accentStart = i;
      break;
    }
  }
  const accentEnd = accentStart >= 0 ? accentStart + accentWords.length - 1 : -1;
  const MotionTag = motion[Tag];

  return (
    <MotionTag id={id} className={className} aria-label={text} variants={staggerFast} initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-80px" }}>
      {words.map((w, index) => {
        const isAccent = accentStart >= 0 && index >= accentStart && index <= accentEnd;
        return (
          <span className="word-wrap" aria-hidden="true" key={index}>
            <motion.span className={`word-inner ${isAccent ? "headline-accent" : ""}`.trim()} variants={wordVariant}>
              {w}
              {isAccent && (
                <motion.span
                  className="headline-underline"
                  aria-hidden="true"
                  initial={{ scaleX: 0 }}
                  whileInView={{ scaleX: 1 }}
                  viewport={{ once: true, margin: "-80px" }}
                  transition={{ duration: 0.55, delay: 0.45, ease: easeOutExpo }}
                />
              )}
            </motion.span>
          </span>
        );
      })}
    </MotionTag>
  );
}
