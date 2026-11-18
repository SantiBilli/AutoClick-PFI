"use client";

import Image from "next/image";
import { motion } from "framer-motion";
import { ArrowRight, Building2, KeyRound, ShieldCheck, Users, Zap, Workflow } from "lucide-react";
import { Reveal, RevealItem } from "../ui/Reveal";
import { AnimatedCheck } from "../ui/AnimatedCheck";
import { SectionHeading } from "../ui/SectionHeading";
import { SectionConnector } from "../ui/SectionConnector";
import { CTALink } from "../ui/MotionLink";
import { easeOutExpo } from "../../lib/motion";

const benefits = [
  [Workflow, "tint-1", "Flujos visuales", "Flujos visuales para Desktop, web y archivos"],
  [Users, "tint-2", "Roles y auditoría", "Roles, áreas y auditoría operativa"],
  [KeyRound, "tint-3", "Procesos y permisos", "Procesos guiados y permisos administrables"],
] as const;

const avatars = [
  ["business-scene__avatar--1", Users],
  ["business-scene__avatar--2", ShieldCheck],
  ["business-scene__avatar--3", Workflow],
] as const;

export function BusinessPlan() {
  return <section className="business-band" id="precios" aria-labelledby="plan-title">
    <div className="section-wrap">
      <SectionConnector height={32} />
      <div className="business-layout">
        <div className="business-illustration">
          <div className="business-scene">
            <svg className="business-scene__lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <motion.path d="M16 80 L42 60" initial={{ pathLength: 0, opacity: 0 }} whileInView={{ pathLength: 1, opacity: 1 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.6, delay: 0.65, ease: easeOutExpo }} />
              <motion.path d="M85 54 L60 55" initial={{ pathLength: 0, opacity: 0 }} whileInView={{ pathLength: 1, opacity: 1 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.6, delay: 0.8, ease: easeOutExpo }} />
              <motion.path d="M27 15 L46 40" initial={{ pathLength: 0, opacity: 0 }} whileInView={{ pathLength: 1, opacity: 1 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.6, delay: 0.95, ease: easeOutExpo }} />
              <motion.path d="M74 23 L58 44" initial={{ pathLength: 0, opacity: 0 }} whileInView={{ pathLength: 1, opacity: 1 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.6, delay: 1.1, ease: easeOutExpo }} />
            </svg>

            <motion.div className="business-scene__hq" initial={{ opacity: 0, scale: 0.85 }} whileInView={{ opacity: 1, scale: 1 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.5, delay: 0.5, ease: easeOutExpo }}>
              <Building2 size={26} />
              <span className="business-scene__hq-dots" aria-hidden="true"><i /><i /><i /></span>
            </motion.div>

            {avatars.map(([className, Icon], index) => <motion.span
              className={`business-scene__avatar ${className}`}
              key={className}
              initial={{ opacity: 0, scale: 0.6 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.45, delay: 0.75 + index * 0.15, ease: easeOutExpo }}
            >
              <Icon size={16} />
              <motion.span className="business-scene__avatar-pulse" aria-hidden="true" initial={{ scale: 1, opacity: 0 }} whileInView={{ scale: 1.35, opacity: [0, 0.5, 0] }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 1.1, delay: 1.1 + index * 0.15, ease: "easeOut" }} />
            </motion.span>)}

            <motion.div className="business-scene__panel" initial={{ opacity: 0, x: 12 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.5, delay: 1.2, ease: easeOutExpo }}>
              <span className="business-scene__panel-head"><ShieldCheck size={12} /> Permisos</span>
              <span className="business-scene__panel-bar"><span style={{ width: "78%" }} /></span>
              <span className="business-scene__panel-bar"><span style={{ width: "45%" }} /></span>
            </motion.div>

            <motion.span className="business-scene__chip business-scene__chip--1" initial={{ opacity: 0, y: 8 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.45, delay: 1.35, ease: easeOutExpo }}>
              <Zap size={11} /> Flujo activo
            </motion.span>

            <motion.div className="business-scene__mascot" initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.5, delay: 1.5, ease: easeOutExpo }}>
              <motion.div animate={{ y: [0, -6, 0] }} transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}>
                <Image src="/mascot/AutoClick_Robot_Exito.png" alt="" width={84} height={84} />
              </motion.div>
            </motion.div>
          </div>
        </div>

        <div className="business-info">
          <SectionHeading id="plan-title" title="AutoClick Business" accentWord="Business" description="Un plan para organizaciones que necesitan ordenar la automatización con acompañamiento y gobierno." />

          <Reveal as="div" stagger className="business-benefits">
            {benefits.map(([Icon, tint, title, text], index) => <RevealItem as="div" className="business-benefit" key={title}>
              <span className={`business-benefit__icon ${tint}`}><Icon size={18} /></span>
              <span className="business-benefit__body">
                <strong>{title} <AnimatedCheck delay={0.2 + index * 0.1} /></strong>
                <p>{text}</p>
              </span>
            </RevealItem>)}
          </Reveal>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.4, delay: 0.55, ease: easeOutExpo }}
          >
            <CTALink strong href="/request-business" className="ui-button ui-button--primary">Solicitar AutoClick Business <ArrowRight size={17} /></CTALink>
          </motion.div>
        </div>
      </div>
    </div>
  </section>;
}
