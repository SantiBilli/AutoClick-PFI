import type { Metadata } from "next";
import { Reveal, RevealItem } from "../../../components/ui/Reveal";
import { RobotHelper } from "../../../components/ui/RobotHelper";
import { RequestForm } from "../../../components/public/RequestForm";
import { RequestContact, RequestFlow } from "../../../components/public/RequestFlow";

export const metadata: Metadata = {
  title: "Solicitar AutoClick Business",
  description: "Contanos qué proceso querés automatizar y armamos el alcance de AutoClick para tu organización.",
};

export default function RequestBusinessPage() {
  return (
    <div className="request-page">
      <section className="request-hero section-wrap" aria-labelledby="request-title">
        <span className="request-hero__glow" aria-hidden="true" />

        <Reveal as="div" className="request-hero__copy" stagger>
          <RevealItem as="div">
            <p className="eyebrow">AutoClick Business</p>
          </RevealItem>
          <RevealItem as="div">
            <h1 id="request-title">Contanos qué proceso querés automatizar.</h1>
          </RevealItem>
          <RevealItem as="div">
            <p className="request-hero__lead">
              Revisamos tu caso, te mostramos cómo queda el flujo en AutoClick y armamos el alcance para tu equipo.
            </p>
          </RevealItem>
          <RevealItem as="div" className="request-hero__mascot">
            <RobotHelper pose="explaining" size="xl" />
          </RevealItem>
        </Reveal>

        <div className="request-hero__form">
          <RequestForm />
        </div>
      </section>

      <RequestFlow />
      <RequestContact />
    </div>
  );
}
