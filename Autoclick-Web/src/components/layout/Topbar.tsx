"use client";
import { Fragment, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useMotionValueEvent, useScroll } from "framer-motion";
import Link from "next/link";
import { ChevronRight, Menu, Search } from "lucide-react";
import { UserMenu } from "./UserMenu";
import { useDemoStore } from "../../lib/demo-store";
import { NotificationsMenu } from "./NotificationsMenu";
import { easeOutExpo } from "../../lib/motion";

export interface Crumb {
  label: string;
  href?: string;
}

export function Topbar({
  kicker,
  title,
  crumbs,
  onOpenMenu,
}: {
  kicker?: string;
  title?: string;
  crumbs?: Crumb[];
  onOpenMenu: () => void;
}) {
  const { role, hasDesktopAccess } = useDemoStore();
  const [scrolled, setScrolled] = useState(false);
  const { scrollY } = useScroll();
  useMotionValueEvent(scrollY, "change", (latest) => setScrolled(latest > 10));

  return (
    <header className={`portal-topbar ${scrolled ? "portal-topbar--scrolled" : ""}`.trim()}>
      <button className="portal-iconbtn portal-topbar__menu" type="button" aria-label="Abrir menú" onClick={onOpenMenu}>
        <Menu size={19} aria-hidden="true" />
      </button>

      <div className="portal-topbar__lead">
        <div className="portal-topbar__meta">
          {crumbs && crumbs.length > 0 && (
            <p className="portal-topbar__crumbs">
              {crumbs.map((crumb, index) => (
                <Fragment key={`${crumb.label}-${index}`}>
                  {index > 0 && <ChevronRight size={13} aria-hidden="true" />}
                  {crumb.href ? <Link href={crumb.href}>{crumb.label}</Link> : <span>{crumb.label}</span>}
                </Fragment>
              ))}
            </p>
          )}
          {kicker && <p className="portal-topbar__kicker">{kicker}</p>}
          {/* Estado de acceso a Desktop: la respuesta a "¿puedo trabajar ahora?". */}
          {role !== "AUTOCLICK_ADMIN" && (
            <span className={`ui-badge ui-badge--${hasDesktopAccess ? "green" : "amber"}`}>
              {hasDesktopAccess ? "Acceso activo" : "Acceso bloqueado"}
            </span>
          )}
        </div>
        <AnimatePresence mode="wait" initial={false}>
          {title && (
            <motion.h1
              key={title}
              className="portal-topbar__title"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.3, ease: easeOutExpo }}
            >
              {title}
            </motion.h1>
          )}
        </AnimatePresence>
      </div>

      <div className="portal-topbar__actions">
        <SearchField />
        <NotificationsMenu />
        <UserMenu />
      </div>
    </header>
  );
}

function SearchField() {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // "/" focuses the field, unless the user is already typing somewhere else.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      event.preventDefault();
      inputRef.current?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <label className="portal-search">
      <Search size={16} aria-hidden="true" />
      <input
        ref={inputRef}
        type="search"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Buscar áreas, personas…"
        aria-label="Buscar en el portal"
      />
      <kbd aria-hidden="true">/</kbd>
    </label>
  );
}
