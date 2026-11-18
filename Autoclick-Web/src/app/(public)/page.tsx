import { AiCapabilities } from "../../components/landing/AiCapabilities";
import { BusinessPlan } from "../../components/landing/BusinessPlan";
import { CapabilityGrid } from "../../components/landing/CapabilityGrid";
import { Faq } from "../../components/landing/Faq";
import { Governance } from "../../components/landing/Governance";
import { Hero } from "../../components/landing/Hero";
import { ProcessMarquee } from "../../components/landing/ProcessMarquee";

export default function HomePage() {
  return <><Hero /><ProcessMarquee /><CapabilityGrid /><AiCapabilities /><Governance /><BusinessPlan /><Faq /></>;
}
