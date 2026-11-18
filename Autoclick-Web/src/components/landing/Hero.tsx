"use client";

import { motion } from "framer-motion";
import { ArrowRight, Check } from "lucide-react";
import { fadeUp, staggerContainer } from "../../lib/motion";
import { AnimatedHeadline } from "../ui/AnimatedHeadline";
import { CTALink } from "../ui/MotionLink";
import { HeroVisual } from "./HeroVisual";

export function Hero() {
  return <section className="landing-hero section-wrap" aria-labelledby="hero-title">
    <div className="hero-glow" aria-hidden="true" />
    <motion.div className="hero-copy" variants={staggerContainer} initial="hidden" animate="visible">
      <AnimatedHeadline as="h1" id="hero-title" text="Diseñá flujos que trabajan como tu equipo." accentWord="trabajan" />
      <motion.p className="hero-lead" variants={fadeUp}>AutoClick conecta tus tareas de Desktop, web, Excel y archivos en workflows visuales, ejecutados localmente y gobernados desde un mismo lugar.</motion.p>
      <motion.div className="hero-actions" variants={fadeUp}>
        <CTALink strong href="/request-business" className="ui-button ui-button--primary ui-button--lg">Solicitar AutoClick Business <ArrowRight size={17} /></CTALink>
        <CTALink href="/login" className="text-link">Iniciar sesión <ArrowRight size={16} /></CTALink>
      </motion.div>
      <motion.div className="hero-proof" variants={fadeUp}><Check size={16} /> Sin desplazar tus datos fuera de tu entorno de trabajo</motion.div>
    </motion.div>
    <HeroVisual />
  </section>;
}
