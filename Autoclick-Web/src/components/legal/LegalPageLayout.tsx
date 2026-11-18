import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { LegalHero } from "./LegalHero";
import { LegalTableOfContents, type LegalTocItem } from "./LegalTableOfContents";

export function LegalPageLayout({
  icon,
  badge,
  title,
  accentWord,
  description,
  lastUpdated,
  toc,
  summary,
  children,
}: {
  icon: LucideIcon;
  badge?: string;
  title: string;
  accentWord: string;
  description: string;
  lastUpdated: string;
  toc: LegalTocItem[];
  summary?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="section-wrap legal-page">
      <Link className="legal-back" href="/">
        <ArrowLeft size={16} aria-hidden="true" /> Volver al inicio
      </Link>

      <LegalHero icon={icon} badge={badge} title={title} accentWord={accentWord} description={description} lastUpdated={lastUpdated} />

      {summary}

      <div className="legal-layout">
        <LegalTableOfContents items={toc} />
        <div className="legal-content">{children}</div>
      </div>
    </div>
  );
}
