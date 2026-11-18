"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

export interface LegalTocItem {
  id: string;
  label: string;
}

export function LegalTableOfContents({ items }: { items: LegalTocItem[] }) {
  const [active, setActive] = useState(items[0]?.id ?? "");
  const detailsRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const elements = items
      .map((item) => document.getElementById(item.id))
      .filter((el): el is HTMLElement => el !== null);
    if (elements.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-110px 0px -70% 0px", threshold: 0 },
    );

    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [items]);

  function closeMobileMenu() {
    if (detailsRef.current) detailsRef.current.open = false;
  }

  return (
    <>
      <nav className="legal-toc" aria-label="Índice del documento">
        <p className="legal-toc__label">Índice</p>
        {items.map((item) => (
          <a key={item.id} href={`#${item.id}`} aria-current={active === item.id ? "true" : undefined}>
            {item.label}
          </a>
        ))}
      </nav>

      <div className="legal-toc-mobile">
        <details ref={detailsRef}>
          <summary>
            Índice del documento
            <ChevronDown size={18} aria-hidden="true" />
          </summary>
          <nav aria-label="Índice del documento">
            {items.map((item) => (
              <a
                key={item.id}
                href={`#${item.id}`}
                aria-current={active === item.id ? "true" : undefined}
                onClick={closeMobileMenu}
              >
                {item.label}
              </a>
            ))}
          </nav>
        </details>
      </div>
    </>
  );
}
