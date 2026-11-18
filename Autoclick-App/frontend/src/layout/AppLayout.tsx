import { FolderOpen, Settings } from 'lucide-react';
import { motion, MotionConfig } from 'framer-motion';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { AiGlyph } from '@/components/AiGlyph';
import { LogoMark } from '@/components/LogoMark';

const links = [
  { to: '/explorer', label: 'Explorador', icon: FolderOpen, kind: 'lucide' as const },
  { to: '/autoclick-ai', label: 'Asistente IA', icon: AiGlyph, kind: 'glyph' as const },
  { to: '/settings', label: 'Configuración', icon: Settings, kind: 'lucide' as const },
];

export function AppLayout() {
  const location = useLocation();
  const aiRoute = location.pathname === '/autoclick-ai';

  return (
    <MotionConfig reducedMotion="user">
      <div
        className={
          aiRoute
            ? 'flex h-dvh min-h-0 flex-col overflow-hidden md:grid md:grid-cols-[240px_minmax(0,1fr)]'
            : 'flex min-h-screen flex-col md:grid md:h-screen md:grid-cols-[240px_minmax(0,1fr)]'
        }>
        <aside className="relative flex flex-col bg-sidebar px-3 pt-3 pb-2 text-white md:px-4 md:py-6">
          <div className="pointer-events-none absolute inset-0 bg-grid-glow opacity-40 md:opacity-50" />
          <div className="pointer-events-none absolute inset-0 bg-dot-grid opacity-[0.10] [mask-image:linear-gradient(180deg,black,transparent_75%)]" />

          <div className="relative mx-1 mb-4 flex items-center gap-2.5 text-[17px] font-extrabold md:mx-1 md:mb-7 md:text-[19px]">
            <LogoMark className="pointer-events-none" size={32} variant="dark" />
            AutoClick
          </div>

          <p className="relative mx-2 mb-2 hidden text-[10px] font-extrabold tracking-[0.16em] text-[#7c8aa3] uppercase md:block">
            Navegación
          </p>

          <nav
            aria-label="Navegación principal"
            className="relative flex gap-1 overflow-x-auto pb-1 md:block md:overflow-visible md:pb-0">
            {links.map(({ to, label, icon: Icon, kind }) => {
              const isActive = location.pathname === to;
              return (
                <NavLink
                  className="group relative flex shrink-0 items-center gap-2.5 rounded-control px-2 py-2 text-[13px] font-bold no-underline focus-visible:outline-none focus-visible:shadow-focus md:mb-1.5 md:py-2 md:text-[14px]"
                  key={to}
                  to={to}>
                  {isActive ? (
                    <motion.span
                      className="pointer-events-none absolute inset-0 rounded-control bg-gradient-to-r from-primary to-bright-blue shadow-glow-primary"
                      layoutId="nav-active-pill"
                      transition={{ type: 'spring', stiffness: 500, damping: 40 }}
                    />
                  ) : null}
                  <span
                    className={`pointer-events-none relative grid size-8 shrink-0 place-items-center rounded-[9px] border transition-colors duration-200 ${
                      isActive
                        ? 'border-white/25 bg-white/15 text-white'
                        : 'border-white/5 bg-white/[0.04] text-[#8f9cb5] group-hover:border-white/15 group-hover:bg-white/10 group-hover:text-white'
                    }`}>
                    <span className="pointer-events-none grid place-items-center">
                      {kind === 'glyph' ? (
                        <Icon active={isActive} size={16} />
                      ) : (
                        <Icon aria-hidden="true" size={16} />
                      )}
                    </span>
                  </span>
                  <span
                    className={`relative ${isActive ? 'text-white' : 'text-[#aeb9ca] transition-colors duration-150 group-hover:text-white'}`}>
                    {label}
                  </span>
                </NavLink>
              );
            })}
          </nav>

          <div className="relative mt-auto hidden pt-4 text-center md:block">
            <span className="font-mono text-[11px] font-medium tracking-wider text-[#7c8aa3]">
              v0.0.1
            </span>
          </div>
        </aside>
        <main
          className={`bg-app-canvas min-w-0 flex-1 p-4 sm:p-6 md:p-8 ${aiRoute ? 'min-h-0 overflow-hidden' : 'overflow-auto'}`}>
          <Outlet />
        </main>
      </div>
    </MotionConfig>
  );
}
