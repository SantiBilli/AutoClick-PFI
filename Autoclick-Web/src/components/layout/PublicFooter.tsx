"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BrandMark } from "../ui/BrandMark";
import { Reveal } from "../ui/Reveal";

const links = [
  ["Privacidad", "/privacidad"],
  ["Términos de uso", "/terminos"],
] as const;

const authLinks = [
  ["Privacidad", "/privacidad"],
  ["Términos de uso", "/terminos"],
] as const;

export function PublicFooter() {
  const pathname = usePathname();
  const isAuth = pathname === "/login" || pathname === "/register";

  if (pathname === "/login") return null;

  if (isAuth) {
    return (
      <footer className="public-footer public-footer--auth">
        <nav aria-label="Enlaces del pie de página">
          {authLinks.map(([label, href]) => (
            <Link key={href} href={href}>
              {label}
            </Link>
          ))}
        </nav>
      </footer>
    );
  }

  return (
    <Reveal as="footer" className="public-footer">
      <Link href="/" aria-label="AutoClick, inicio">
        <BrandMark />
      </Link>
      <p>Procesos que avanzan con inteligencia.</p>
        <nav aria-label="Enlaces del pie de página">
          {links.map(([label, href]) => (
            <Link key={href} href={href}>
              {label}
            </Link>
          ))}
          <span>Contacto</span>
        </nav>
    </Reveal>
  );
}
