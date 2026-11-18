import type { Metadata } from "next";
import Link from "next/link";
import {
  Bot,
  Building2,
  Eye,
  Laptop,
  MessageCircle,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  User,
  Users,
} from "lucide-react";
import { LegalPageLayout } from "../../../components/legal/LegalPageLayout";
import { LegalSection } from "../../../components/legal/LegalSection";
import { LegalCallout } from "../../../components/legal/LegalCallout";
import { LegalSummaryCard } from "../../../components/legal/LegalSummaryCard";
import { LegalFlowDiagram } from "../../../components/legal/LegalFlowDiagram";
import { Reveal } from "../../../components/ui/Reveal";
import { LEGAL_CONTACT_HREF, LEGAL_LAST_UPDATED } from "../../../lib/legal";

export const metadata: Metadata = {
  title: "Términos de uso | AutoClick",
  description: "Conocé las reglas de uso de AutoClick, las responsabilidades del usuario y el funcionamiento de las propuestas generadas por ClickIA.",
};

const toc = [
  { id: "naturaleza", label: "1. Naturaleza del proyecto" },
  { id: "descripcion", label: "2. Descripción del servicio" },
  { id: "cuentas", label: "3. Cuentas" },
  { id: "organizaciones-roles", label: "4. Organizaciones y roles" },
  { id: "revision-humana", label: "5. Revisión humana" },
  { id: "limitaciones-clickia", label: "6. Limitaciones de ClickIA" },
  { id: "archivos-locales", label: "7. Archivos locales" },
  { id: "uso-permitido", label: "8. Uso permitido" },
  { id: "usos-prohibidos", label: "9. Usos prohibidos" },
  { id: "consumo", label: "10. Consumo" },
  { id: "servicios-externos", label: "11. Servicios externos" },
  { id: "propiedad-intelectual", label: "12. Propiedad intelectual" },
  { id: "disponibilidad", label: "13. Disponibilidad" },
  { id: "suspension", label: "14. Suspensión" },
  { id: "legislacion-contacto", label: "15. Legislación y contacto" },
];

const flowSteps = [
  { icon: <MessageCircle size={20} aria-hidden="true" />, title: "Vos describís." },
  { icon: <Bot size={20} aria-hidden="true" />, title: "ClickIA propone." },
  { icon: <Eye size={20} aria-hidden="true" />, title: "Vos revisás." },
  { icon: <Laptop size={20} aria-hidden="true" />, title: "Desktop ejecuta localmente." },
];

const roles = [
  { icon: ShieldCheck, title: "Administrador de AutoClick", text: "Gestiona la plataforma a nivel general." },
  { icon: Building2, title: "Propietario de organización", text: "Administra su organización y sus áreas." },
  { icon: Users, title: "Miembro de organización", text: "Participa dentro del alcance que le asignaron." },
  { icon: SlidersHorizontal, title: "Administrador de área", text: "Gestiona miembros y configuración de su área." },
  { icon: User, title: "Miembro de área", text: "Trabaja dentro de los permisos de su área." },
];

export default function TerminosPage() {
  return (
    <LegalPageLayout
      icon={ScrollText}
      title="Automatizá con reglas claras."
      accentWord="reglas claras"
      description="Estos términos explican cómo puede utilizarse AutoClick y por qué cada automatización requiere revisión y aprobación humana."
      lastUpdated={LEGAL_LAST_UPDATED}
      toc={toc}
      summary={
        <div className="legal-page-summary">
          <h2>Cómo se construye cada automatización</h2>
          <p>Cuatro pasos, con una revisión humana antes de cualquier ejecución.</p>
          <LegalFlowDiagram steps={flowSteps} />
          <LegalCallout variant="notice">
            <p>La inteligencia artificial asiste en el diseño, pero no reemplaza la decisión del usuario.</p>
          </LegalCallout>
        </div>
      }
    >
      <LegalSection id="naturaleza" title="1. Naturaleza del proyecto">
        <p>
          AutoClick es actualmente un prototipo desarrollado con fines académicos y de validación tecnológica. La información publicada
          no constituye una oferta comercial, una garantía de disponibilidad ni un compromiso de prestación definitiva.
        </p>
        <p>El modelo comercial, los precios, las licencias y los niveles de servicio todavía no se encuentran definidos.</p>
      </LegalSection>

      <LegalSection id="descripcion" title="2. Descripción del servicio">
        <p>AutoClick permite:</p>
        <ul>
          <li>Describir procesos en lenguaje natural.</li>
          <li>Generar borradores.</li>
          <li>Editar flujos mediante bloques.</li>
          <li>Configurar acciones.</li>
          <li>Validar el flujo.</li>
          <li>Ejecutarlo localmente.</li>
          <li>Guardarlo como JSON.</li>
          <li>Interactuar con web, aplicaciones, Excel y archivos.</li>
          <li>Solicitar asistencia a ClickIA.</li>
        </ul>
      </LegalSection>

      <LegalSection id="cuentas" title="3. Cuentas" tint>
        <ul>
          <li>Uso de correo y contraseña.</li>
          <li>Confirmación y recuperación.</li>
          <li>Responsabilidad sobre credenciales.</li>
          <li>Prohibición de compartir accesos sin autorización.</li>
          <li>Posibilidad de conservar o limitar la sesión.</li>
          <li>Obligación de reportar accesos indebidos.</li>
        </ul>
      </LegalSection>

      <LegalSection id="organizaciones-roles" title="4. Organizaciones y roles">
        <p>Los permisos dependen de la organización, el área y el estado de la membresía.</p>
        <Reveal as="div" stagger className="legal-summary-grid">
          {roles.map((role) => (
            <LegalSummaryCard icon={role.icon} title={role.title} key={role.title}>
              {role.text}
            </LegalSummaryCard>
          ))}
        </Reveal>
      </LegalSection>

      <LegalSection id="revision-humana" title="5. Revisión humana" tint>
        <p>
          Las respuestas y flujos generados por ClickIA son propuestas. No se ejecutan automáticamente. El usuario debe revisar,
          modificar, aceptar o rechazar cada propuesta antes de su ejecución.
        </p>
        <p>Antes de ejecutar, el usuario debe verificar:</p>
        <ul>
          <li>Los pasos.</li>
          <li>Los parámetros.</li>
          <li>Los archivos.</li>
          <li>Los sistemas involucrados.</li>
          <li>Las consecuencias de la ejecución.</li>
          <li>Que cuenta con autorización.</li>
        </ul>
      </LegalSection>

      <LegalSection id="limitaciones-clickia" title="6. Limitaciones de ClickIA">
        <p>ClickIA:</p>
        <ul>
          <li>Puede interpretar incorrectamente una instrucción.</li>
          <li>Puede generar respuestas incompletas.</li>
          <li>Puede solicitar aclaraciones.</li>
          <li>No reemplaza el criterio profesional.</li>
          <li>No garantiza que todos los procesos sean automatizables.</li>
          <li>No controla directamente el equipo.</li>
          <li>No ejecuta acciones sin intervención de Desktop y aprobación humana.</li>
        </ul>
      </LegalSection>

      <LegalSection id="archivos-locales" title="7. Archivos locales">
        <ul>
          <li>El usuario selecciona dónde guardar sus bots.</li>
          <li>Controla la carpeta y sus archivos.</li>
          <li>Debe mantener copias de seguridad.</li>
          <li>La eliminación puede ser permanente.</li>
          <li>AutoClick no puede recuperar archivos que nunca fueron almacenados en su infraestructura.</li>
        </ul>
      </LegalSection>

      <LegalSection id="uso-permitido" title="8. Uso permitido" tint>
        <p>Se permite utilizar AutoClick sobre:</p>
        <ul>
          <li>Sistemas propios.</li>
          <li>Sistemas autorizados.</li>
          <li>Datos respecto de los cuales el usuario posea permisos.</li>
          <li>Procesos legítimos y compatibles con las políticas de la organización.</li>
        </ul>
      </LegalSection>

      <LegalSection id="usos-prohibidos" title="9. Usos prohibidos">
        <p>Está prohibido utilizar AutoClick para:</p>
        <ul>
          <li>Acceso no autorizado.</li>
          <li>Obtención de credenciales.</li>
          <li>Distribución de malware.</li>
          <li>Evasión de controles.</li>
          <li>Actividades ilegales.</li>
          <li>Tratamiento de datos sin autorización.</li>
          <li>Vulneración de propiedad intelectual.</li>
          <li>Daño a sistemas.</li>
          <li>Uso de integraciones maliciosas.</li>
          <li>Automatización de decisiones críticas sin supervisión.</li>
        </ul>
      </LegalSection>

      <LegalSection id="consumo" title="10. Consumo de ClickIA" tint>
        <ul>
          <li>El consumo se mide en tokens.</li>
          <li>Puede haber límites por organización y área.</li>
          <li>Los administradores autorizados pueden consultar el consumo.</li>
          <li>Una solicitud puede contabilizarse aunque el usuario rechace posteriormente la propuesta.</li>
          <li>Las autorizaciones temporales pueden vencer.</li>
        </ul>
        <p>Estos términos no incluyen precios.</p>
      </LegalSection>

      <LegalSection id="servicios-externos" title="11. Servicios externos">
        <ul>
          <li>Los flujos pueden interactuar con aplicaciones y sitios de terceros.</li>
          <li>Esos servicios tienen sus propios términos.</li>
          <li>El usuario debe contar con autorización.</li>
          <li>Cambios en interfaces externas pueden afectar las automatizaciones.</li>
        </ul>
        <LegalCallout variant="info">
          <p>AutoClick no garantiza que una web externa mantenga permanentemente su estructura.</p>
        </LegalCallout>
      </LegalSection>

      <LegalSection id="propiedad-intelectual" title="12. Propiedad intelectual" tint>
        <ul>
          <li>La marca, la interfaz y el código de AutoClick pertenecen a sus titulares.</li>
          <li>El usuario conserva sus datos, archivos y automatizaciones.</li>
          <li>AutoClick recibe únicamente la autorización técnica necesaria para procesar el contexto enviado voluntariamente a ClickIA.</li>
          <li>El uso de ClickIA no transfiere automáticamente la propiedad del flujo.</li>
        </ul>
        <LegalCallout variant="warning">
          <p>El modelo definitivo de licencia todavía debe validarse antes del lanzamiento.</p>
        </LegalCallout>
      </LegalSection>

      <LegalSection id="disponibilidad" title="13. Disponibilidad">
        <ul>
          <li>Se trata de un prototipo.</li>
          <li>Puede sufrir cambios e interrupciones.</li>
          <li>No existe actualmente un SLA.</li>
          <li>Las funciones experimentales pueden cambiar.</li>
          <li>Una actualización web no modifica automáticamente los bots locales.</li>
        </ul>
      </LegalSection>

      <LegalSection id="suspension" title="14. Suspensión" tint>
        <p>El acceso puede limitarse cuando:</p>
        <ul>
          <li>La cuenta esté inactiva.</li>
          <li>La organización esté suspendida.</li>
          <li>La membresía no sea válida.</li>
          <li>Se superen límites.</li>
          <li>Se detecte un uso prohibido.</li>
          <li>Sea necesario proteger la plataforma.</li>
        </ul>
      </LegalSection>

      <LegalSection id="legislacion-contacto" title="15. Legislación y contacto">
        <p>El proyecto se desarrolla en Argentina. Los tribunales, el domicilio contractual y la jurisdicción comercial se definirán junto con el operador legal definitivo.</p>
        <p>
          Ante cualquier consulta sobre estos términos, podés escribirnos desde el <Link href={LEGAL_CONTACT_HREF}>formulario de contacto</Link>.
        </p>
      </LegalSection>
    </LegalPageLayout>
  );
}
