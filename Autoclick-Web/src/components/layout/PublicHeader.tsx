"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { motion, useMotionValueEvent, useScroll } from "framer-motion";
import { BrandMark } from "../ui/BrandMark";
import { CTALink } from "../ui/MotionLink";

export function PublicHeader() {
  const [scrolled, setScrolled] = useState(false);
  const { scrollY, scrollYProgress } = useScroll();
  const pathname = usePathname();
  const isAuth = pathname === "/login" || pathname === "/register";

  useMotionValueEvent(scrollY, "change", (latest) => setScrolled(latest > 8));

  if (isAuth) {
    return (
      <header className="public-header public-header--auth">
        <Link href="/" aria-label="AutoClick, inicio">
          <BrandMark />
        </Link>
        {pathname !== "/login" && (
          <div className="public-header__actions">
            <Link className="public-header__back" href="/">Volver al inicio</Link>
            <Link className="ui-button ui-button--outline ui-button--sm" href="/login">Iniciar sesión</Link>
          </div>
        )}
      </header>
    );
  }

  return (
    <>
      <motion.div className="scroll-progress" style={{ scaleX: scrollYProgress }} />
      <header className={`public-header ${scrolled ? "public-header--scrolled" : ""}`.trim()}>
        <Link href="/" aria-label="AutoClick, inicio">
          <BrandMark />
        </Link>
        <div className="public-header__actions">
          <CTALink className="public-header__login" href="/login">Iniciar sesión</CTALink>
          <CTALink className="ui-button ui-button--outline ui-button--sm" href="/request-business">Solicitar AutoClick Business</CTALink>
        </div>
      </header>
    </>
  );
}
