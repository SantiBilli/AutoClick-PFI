import type { LucideIcon } from "lucide-react";
import { CalendarClock } from "lucide-react";
import { AnimatedHeadline } from "../ui/AnimatedHeadline";
import { Reveal } from "../ui/Reveal";

export function LegalHero({
  icon: Icon,
  badge,
  title,
  accentWord,
  description,
  lastUpdated,
}: {
  icon: LucideIcon;
  badge?: string;
  title: string;
  accentWord: string;
  description: string;
  lastUpdated: string;
}) {
  return (
    <Reveal as="div" className="legal-hero">
      <div className="legal-hero__top">
        <span className="legal-hero__icon">
          <Icon size={26} aria-hidden="true" />
        </span>
        {badge && <span className="legal-hero__badge">{badge}</span>}
      </div>
      <AnimatedHeadline as="h1" text={title} accentWord={accentWord} />
      <p className="legal-hero__desc">{description}</p>
      <p className="legal-hero__meta">
        <CalendarClock size={15} aria-hidden="true" /> Última actualización: {lastUpdated}
      </p>
    </Reveal>
  );
}
