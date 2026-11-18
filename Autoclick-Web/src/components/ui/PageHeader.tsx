"use client";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { easeOutExpo } from "../../lib/motion";

/**
 * Full header with its own <h1>. Only for routes the topbar cannot title on its
 * own (detail pages), so the page never shows two competing headings.
 */
export function PageHeader({
  eyebrow,
  title,
  titleId,
  description,
  status,
  actions,
  back,
}: {
  eyebrow?: string;
  title: ReactNode;
  titleId?: string;
  description?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <motion.div className="page-header" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: easeOutExpo }}>
      {back && (
        <Link className="page-header__back" href={back.href}>
          <ArrowLeft size={15} aria-hidden="true" /> {back.label}
        </Link>
      )}
      <div className="page-header__row">
        <div className="page-header__copy">
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <div className="page-header__title-row">
            <h1 id={titleId}>{title}</h1>
            {status}
          </div>
          {description && <p className="portal-muted">{description}</p>}
        </div>
        {actions && <div className="page-header__side">{actions}</div>}
      </div>
    </motion.div>
  );
}

/**
 * Heading-less intro for section pages: the topbar already renders their <h1>,
 * so this only carries the supporting line and the page actions.
 */
export function PageIntro({ description, actions, status }: { description?: ReactNode; actions?: ReactNode; status?: ReactNode }) {
  return (
    <motion.div className="page-intro" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: easeOutExpo }}>
      {description && <p className="page-intro__text">{description}</p>}
      {(status || actions) && (
        <div className="page-header__side">
          {status}
          {actions}
        </div>
      )}
    </motion.div>
  );
}
