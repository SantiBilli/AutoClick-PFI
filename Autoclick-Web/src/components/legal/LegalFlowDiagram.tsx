"use client";

import { Fragment } from "react";
import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { easeOutExpo } from "../../lib/motion";

export interface LegalFlowStep {
  icon: ReactNode;
  title: string;
  description?: string;
}

export function LegalFlowDiagram({ steps }: { steps: LegalFlowStep[] }) {
  return (
    <div className="legal-flow" role="list" aria-label="Flujo del proceso">
      {steps.map((step, index) => (
        <Fragment key={step.title}>
          {index > 0 && (
            <span className="legal-flow-connector" aria-hidden="true">
              <motion.span
                className="legal-flow-connector-line"
                initial={{ scaleX: 0 }}
                whileInView={{ scaleX: 1 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.5, delay: index * 0.15, ease: easeOutExpo }}
              />
            </span>
          )}
          <motion.div
            className="ui-card legal-flow-step"
            role="listitem"
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ duration: 0.5, delay: index * 0.15, ease: easeOutExpo }}
          >
            <span className="legal-flow-step__badge">{index + 1}</span>
            <span className="legal-flow-step__icon">{step.icon}</span>
            <strong>{step.title}</strong>
            {step.description && <p>{step.description}</p>}
          </motion.div>
        </Fragment>
      ))}
    </div>
  );
}
