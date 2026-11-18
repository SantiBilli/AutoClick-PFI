"use client";
import { useRef, useState } from "react";
import { motion, useReducedMotion, useScroll, useSpring, useTransform } from "framer-motion";
import { Download, MonitorDown, ShieldAlert } from "lucide-react";
import { Panel } from "../ui/Panel";
import { formatNumber } from "../../lib/formatters";
import { easeOutExpo } from "../../lib/motion";
import { useCloudStore } from "../../lib/cloud-store";
import { cloudApi, authMessage } from "../../lib/cloud-auth";
import { DESKTOP_DOWNLOADS_ENABLED } from "../../lib/desktop-downloads";

export function DesktopDownloadCard({
  version,
  hasAccess,
  blockedReason,
  usage,
  limit,
}: {
  version: string;
  hasAccess: boolean;
  blockedReason: string;
  usage: number;
  limit: number;
}) {
  const reduceMotion = useReducedMotion();
  const { downloadUrl } = useCloudStore();
  const available = hasAccess && downloadUrl === '/v1/desktop/download';
  const [downloadError, setDownloadError] = useState('');
  const [downloading, setDownloading] = useState(false);
  async function download() {
    if (!DESKTOP_DOWNLOADS_ENABLED || !available) return;
    setDownloading(true); setDownloadError('');
    try { const result = await cloudApi<{ url: string }>(downloadUrl); window.location.assign(result.url); }
    catch (e) { setDownloadError(authMessage(e)); }
    finally { setDownloading(false); }
  }
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const rawY = useTransform(scrollYProgress, [0, 1], [26, -26]);
  const parallaxY = useSpring(rawY, { stiffness: 120, damping: 24, mass: 0.6 });
  const percent = limit > 0 ? Math.min(100, Math.round((usage / limit) * 100)) : 0;

  return (
    <Panel className="dash-feature" hover spotlight>
      <div>
        <p className="dash-eyebrow">Trabajo en tu computadora</p>
        <h2>Descargá AutoClick Desktop</h2>
        <p>
          {hasAccess
            ? "Ejecutá tus automatizaciones desde tu equipo con la misma sesión y los mismos límites de tokens del portal."
            : `La descarga está bloqueada. ${blockedReason}`}
        </p>
        <div className="dash-feature__meta">
          <button className="ui-button ui-button--primary ui-button--md" type="button" disabled={!DESKTOP_DOWNLOADS_ENABLED || !available || downloading} onClick={() => void download()} aria-describedby={hasAccess ? undefined : "desktop-download-blocked"}>
            <Download size={16} aria-hidden="true" /> Descargar AutoClick Desktop
          </button>
          <span className="dash-feature__version">
            {hasAccess ? <MonitorDown size={13} aria-hidden="true" /> : <ShieldAlert size={13} aria-hidden="true" />}
            Versión {version}
          </span>
        </div>
        {!hasAccess && <p id="desktop-download-blocked" className="sr-only">La descarga no está disponible mientras el acceso a Desktop esté bloqueado.</p>}
        {hasAccess && !available && <p className="portal-muted">El instalador todavía no está publicado.</p>}
        {downloadError && <p className="form-error" role="alert">{downloadError}</p>}
      </div>

      {/* Static wrapper is the scroll target; the transform lives on the child so
          the parallax never feeds its own measurements back into useScroll. */}
      <div className="dash-feature__art" ref={ref} aria-hidden="true">
        <span className="dash-feature__glow" />
        <motion.div
          style={reduceMotion ? undefined : { y: parallaxY }}
          initial={{ opacity: 0, scale: 0.94, rotate: -3 }}
          whileInView={{ opacity: 1, scale: 1, rotate: -1.5 }}
          viewport={{ once: true }}
          transition={{ duration: 0.7, ease: easeOutExpo }}
        >
          <div className="app-card">
            <div className="app-card__bar">
              <span /><span /><span />
              <strong>AutoClick {version}</strong>
            </div>
            <div className="app-card__body">
              <span className="app-card__label">Tokens del período</span>
              <span className="app-card__value">{formatNumber(usage)}</span>
              <div className="app-card__rows">
                <span className="app-card__row app-card__row--fill">
                  <motion.span
                    initial={{ width: 0 }}
                    whileInView={{ width: `${percent || 8}%` }}
                    viewport={{ once: true }}
                    transition={{ duration: 1, ease: easeOutExpo, delay: 0.2 }}
                  />
                </span>
                <span className="app-card__row" style={{ width: "72%" }} />
                <span className="app-card__row" style={{ width: "48%" }} />
              </div>
            </div>
            <div className="app-card__foot">
              <span>{limit > 0 ? `${percent}% del límite` : "Sin límite configurado"}</span>
              <span>{hasAccess ? "Sesión activa" : "Bloqueado"}</span>
            </div>
          </div>
        </motion.div>
      </div>
    </Panel>
  );
}
