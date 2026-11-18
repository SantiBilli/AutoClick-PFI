import type { Metadata } from "next";
import Link from "next/link";
import {
  Bot,
  Building2,
  Cloud,
  Database,
  Eye,
  Fingerprint,
  FolderLock,
  Hash,
  KeyRound,
  Laptop,
  Lock,
  Mail,
  Network,
  ShieldCheck,
  Timer,
  Users,
} from "lucide-react";
import { LegalPageLayout } from "../../../components/legal/LegalPageLayout";
import { LegalSection } from "../../../components/legal/LegalSection";
import { LegalCallout } from "../../../components/legal/LegalCallout";
import { LegalSummaryCard } from "../../../components/legal/LegalSummaryCard";
import { LegalFlowDiagram } from "../../../components/legal/LegalFlowDiagram";
import { Reveal } from "../../../components/ui/Reveal";
import { AAIP_RIGHTS_URL, LEGAL_CONTACT_HREF, LEGAL_LAST_UPDATED, TODO_PRIVACY_EMAIL } from "../../../lib/legal";

export const metadata: Metadata = {
  title: "Política de privacidad | AutoClick",
  description: "Conocé qué información utiliza AutoClick, qué datos permanecen en tu computadora y cómo se procesa la asistencia de inteligencia artificial.",
};

const toc = [
  { id: "quien-administra", label: "1. Quién administra AutoClick" },
  { id: "alcance", label: "2. Alcance" },
  { id: "informacion-utilizada", label: "3. Información utilizada" },
  { id: "datos-locales", label: "4. Datos almacenados localmente" },
  { id: "clickia", label: "5. ClickIA" },
  { id: "finalidades", label: "6. Finalidades" },
  { id: "infraestructura", label: "7. Infraestructura" },
  { id: "accesos-permisos", label: "8. Accesos y permisos" },
  { id: "conservacion", label: "9. Conservación" },
  { id: "seguridad", label: "10. Seguridad" },
  { id: "derechos", label: "11. Derechos" },
  { id: "cookies", label: "12. Cookies" },
  { id: "cambios-contacto", label: "13. Cambios y contacto" },
];

const summarySteps = [
  { icon: <Laptop size={20} aria-hidden="true" />, title: "Datos locales", description: "Los bots, archivos, configuraciones y resultados se almacenan en las ubicaciones seleccionadas por el usuario." },
  { icon: <Building2 size={20} aria-hidden="true" />, title: "Administración en AWS", description: "La identidad, las organizaciones, las áreas, los roles y el consumo se administran de forma centralizada." },
  { icon: <Bot size={20} aria-hidden="true" />, title: "Procesamiento temporal", description: "ClickIA procesa temporalmente la conversación y el contexto necesario para generar una respuesta o propuesta." },
];

const infoCards = [
  {
    icon: KeyRound,
    title: "Cuenta",
    items: ["Correo electrónico", "Identificador de Amazon Cognito", "Estado de la cuenta", "Información necesaria para autenticación y recuperación"],
  },
  {
    icon: Building2,
    title: "Contexto empresarial",
    items: ["Organizaciones", "Áreas", "Membresías", "Roles", "Permisos", "Límites de consumo"],
  },
  {
    icon: Bot,
    title: "Uso de ClickIA",
    items: ["Identificador de solicitud", "Usuario, organización y área", "Tokens de entrada y salida", "Estado de la solicitud", "Duración y datos técnicos mínimos"],
  },
  {
    icon: Mail,
    title: "Solicitudes Business",
    items: ["Datos efectivamente solicitados por el formulario", "Correo corporativo", "Empresa", "Mensaje o necesidad informada"],
  },
];

const infrastructure = [
  { icon: KeyRound, name: "Amazon Cognito", detail: "Autenticación" },
  { icon: Network, name: "API Gateway y Lambda", detail: "Autorización y backend" },
  { icon: Database, name: "Aurora PostgreSQL", detail: "Datos administrativos y consumo" },
  { icon: Cloud, name: "AWS Amplify", detail: "Alojamiento web" },
  { icon: Bot, name: "AutoClick-IA y Ollama", detail: "Procesamiento de IA" },
  { icon: FolderLock, name: "DonWeb", detail: "Registro del dominio" },
];

const securityControls = [
  { icon: Lock, title: "HTTPS", text: "Toda la comunicación viaja cifrada entre el cliente y los servicios de AutoClick." },
  { icon: KeyRound, title: "Cognito", text: "Autenticación centralizada de usuarios mediante Amazon Cognito." },
  { icon: Fingerprint, title: "Tokens JWT", text: "Cada sesión y solicitud se valida con tokens firmados." },
  { icon: Timer, title: "Autorizaciones de un solo uso", text: "Las solicitudes a ClickIA usan autorizaciones temporales y acotadas." },
  { icon: Hash, title: "Hash de tokens temporales", text: "Los tokens sensibles se almacenan aplicando hash, no en texto plano." },
  { icon: Users, title: "Roles y separación por organización", text: "Cada organización y área mantiene su propio alcance de datos." },
  { icon: ShieldCheck, title: "Validación con Zod y Pydantic", text: "Las entradas se validan en frontend y backend antes de procesarse." },
  { icon: Laptop, title: "Ejecución local", text: "Los bots corren en el equipo del usuario, cerca de sus archivos." },
  { icon: Eye, title: "Revisión humana", text: "Las propuestas de ClickIA se revisan antes de ejecutarse." },
];

export default function PrivacidadPage() {
  return (
    <LegalPageLayout
      icon={ShieldCheck}
      title="Tu información, bajo control."
      accentWord="control"
      description="Esta política explica qué información utiliza AutoClick, dónde se procesa y qué decisiones permanecen en manos del usuario."
      lastUpdated={LEGAL_LAST_UPDATED}
      toc={toc}
      summary={
        <div className="legal-page-summary">
          <h2>Así se mueve tu información</h2>
          <p>Tres planos separados: tu computadora, la administración centralizada y el procesamiento temporal de ClickIA.</p>
          <LegalFlowDiagram steps={summarySteps} />
          <LegalCallout variant="notice">
            <p>
              Los archivos locales no se envían automáticamente a AWS. Cuando utilizás ClickIA, la conversación y el contexto necesario sí se
              transmiten temporalmente al servicio de inteligencia artificial.
            </p>
          </LegalCallout>
        </div>
      }
    >
      <LegalSection id="quien-administra" title="1. Quién administra AutoClick">
        <p>
          AutoClick es actualmente un prototipo desarrollado en el marco del Proyecto Final de Ingeniería en Informática de la Universidad
          Argentina de la Empresa. La identificación definitiva del responsable del tratamiento será incorporada antes de cualquier
          lanzamiento comercial.
        </p>
        <LegalCallout variant="warning">
          <p>La participación académica de UADE no implica que la universidad opere la plataforma ni sea responsable del tratamiento de sus datos.</p>
        </LegalCallout>
        <p>
          {TODO_PRIVACY_EMAIL ? (
            <>Podés escribirnos a <a href={`mailto:${TODO_PRIVACY_EMAIL}`}>{TODO_PRIVACY_EMAIL}</a> o desde el <Link href={LEGAL_CONTACT_HREF}>formulario de contacto</Link>.</>
          ) : (
            <>Mientras se define un correo legal dedicado, podés escribirnos desde el <Link href={LEGAL_CONTACT_HREF}>formulario de contacto</Link>.</>
          )}
        </p>
      </LegalSection>

      <LegalSection id="alcance" title="2. Alcance">
        <p>Esta política se aplica a:</p>
        <ul>
          <li>autoclick.website.</li>
          <li>El portal web autenticado.</li>
          <li>AutoClick Desktop.</li>
          <li>ClickIA o AutoClick-IA.</li>
          <li>Formularios de contacto y solicitudes Business.</li>
        </ul>
      </LegalSection>

      <LegalSection id="informacion-utilizada" title="3. Información utilizada">
        <p>Agrupamos la información que utiliza AutoClick en cuatro categorías, según de dónde proviene y para qué se usa.</p>
        <Reveal as="div" stagger className="legal-summary-grid legal-summary-grid--four">
          {infoCards.map((card) => (
            <LegalSummaryCard icon={card.icon} title={card.title} key={card.title}>
              <ul>
                {card.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </LegalSummaryCard>
          ))}
        </Reveal>
      </LegalSection>

      <LegalSection id="datos-locales" title="4. Datos almacenados localmente" tint>
        <p>En la computadora del usuario se almacenan:</p>
        <ul>
          <li>Bots en formato JSON.</li>
          <li>Nombre y descripción.</li>
          <li>Bloques y parámetros.</li>
          <li>Archivos utilizados o generados.</li>
          <li>Configuración local.</li>
          <li>Ruta de la carpeta elegida.</li>
          <li>Eventos temporales de ejecución.</li>
          <li>Estado de conversación o propuesta cuando forme parte del bot.</li>
        </ul>
        <LegalCallout variant="info">
          <p>AutoClick no envía automáticamente a AWS el contenido de los bots, los documentos procesados ni los archivos generados.</p>
        </LegalCallout>
        <p>El usuario controla la ubicación y la eliminación de esos archivos en todo momento.</p>
      </LegalSection>

      <LegalSection id="clickia" title="5. ClickIA">
        <p>ClickIA puede recibir temporalmente:</p>
        <ul>
          <li>La conversación.</li>
          <li>La instrucción del usuario.</li>
          <li>Una representación acotada del bot.</li>
          <li>El bloque seleccionado.</li>
          <li>Las capacidades disponibles.</li>
          <li>El contexto necesario.</li>
        </ul>
        <p>El procesamiento ocurre bajo las siguientes condiciones:</p>
        <ul>
          <li>Comunicación mediante HTTPS.</li>
          <li>Procesamiento en infraestructura de AutoClick.</li>
          <li>Modelo administrado mediante Ollama.</li>
          <li>No persistencia de prompts, respuestas, bots, documentos ni capturas en Aurora PostgreSQL.</li>
          <li>Logs limitados a identificadores, etapa, duración y métricas.</li>
          <li>La IA no ejecuta directamente acciones sobre la computadora.</li>
        </ul>
        <LegalCallout variant="notice">
          <p>ClickIA genera propuestas. AutoClick Desktop vuelve a validarlas y el usuario decide si desea aceptarlas, rechazarlas o ejecutarlas temporalmente.</p>
        </LegalCallout>
      </LegalSection>

      <LegalSection id="finalidades" title="6. Finalidades">
        <p>La información descripta se utiliza para:</p>
        <ul>
          <li>Autenticar usuarios.</li>
          <li>Recuperar cuentas.</li>
          <li>Administrar organizaciones y áreas.</li>
          <li>Aplicar roles y permisos.</li>
          <li>Autorizar solicitudes de IA.</li>
          <li>Controlar límites y consumo.</li>
          <li>Generar respuestas y propuestas.</li>
          <li>Atender consultas Business.</li>
          <li>Prevenir usos no autorizados.</li>
          <li>Diagnosticar errores técnicos sin registrar contenido innecesario.</li>
        </ul>
      </LegalSection>

      <LegalSection id="infraestructura" title="7. Infraestructura">
        <p>AutoClick se apoya en los siguientes servicios:</p>
        <div className="legal-infra-list">
          {infrastructure.map((item) => (
            <div className="legal-infra-item" key={item.name}>
              <span className="legal-infra-item__icon">
                <item.icon size={17} aria-hidden="true" />
              </span>
              <span>
                <strong>{item.name}</strong>
                <span>{item.detail}</span>
              </span>
            </div>
          ))}
        </div>
        <LegalCallout variant="warning">
          <p>La región de AWS, las transferencias internacionales y los proveedores definitivos todavía no están definidos y se incorporarán antes del lanzamiento comercial.</p>
        </LegalCallout>
      </LegalSection>

      <LegalSection id="accesos-permisos" title="8. Accesos y permisos" tint>
        <ul>
          <li>Los usuarios acceden solamente a su contexto autorizado.</li>
          <li>Los propietarios gestionan organizaciones.</li>
          <li>Los administradores gestionan áreas y miembros.</li>
          <li>Los permisos se vuelven a validar en el backend.</li>
          <li>Los administradores no reciben acceso automático a los bots ni a los archivos locales.</li>
          <li>AutoClick no vende datos personales.</li>
        </ul>
      </LegalSection>

      <LegalSection id="conservacion" title="9. Conservación">
        <ul>
          <li>Los archivos locales permanecen hasta que el usuario los elimine.</li>
          <li>Los eventos de ejecución se mantienen temporalmente en memoria.</li>
          <li>ClickIA procesa temporalmente la conversación y el contexto.</li>
          <li>Los datos de cuenta y consumo se conservan mientras sean necesarios para administrar la plataforma.</li>
        </ul>
        <LegalCallout variant="warning">
          <p>Los plazos concretos de retención y el procedimiento de eliminación todavía no están definidos.</p>
        </LegalCallout>
      </LegalSection>

      <LegalSection id="seguridad" title="10. Seguridad">
        <p>AutoClick aplica controles técnicos a distintos niveles del sistema.</p>
        <Reveal as="div" stagger className="legal-summary-grid legal-summary-grid--four">
          {securityControls.map((control) => (
            <LegalSummaryCard icon={control.icon} title={control.title} key={control.title}>
              {control.text}
            </LegalSummaryCard>
          ))}
        </Reveal>
        <p>AutoClick aplica medidas orientadas a reducir riesgos, aunque ningún sistema puede garantizar seguridad absoluta.</p>
      </LegalSection>

      <LegalSection id="derechos" title="11. Derechos">
        <p>Como usuario de AutoClick, podés ejercer los siguientes derechos sobre tus datos:</p>
        <ul>
          <li>Acceso.</li>
          <li>Rectificación.</li>
          <li>Actualización.</li>
          <li>Supresión.</li>
          <li>Consulta sobre el uso de los datos.</li>
        </ul>
        <p>
          Podés conocer el detalle de estos derechos en el sitio oficial de la{" "}
          <a href={AAIP_RIGHTS_URL} target="_blank" rel="noopener noreferrer">
            Agencia de Acceso a la Información Pública (AAIP)
          </a>
          .
        </p>
      </LegalSection>

      <LegalSection id="cookies" title="12. Cookies" tint>
        <p>
          AutoClick no utiliza actualmente cookies publicitarias ni perfiles de seguimiento. La aplicación puede utilizar almacenamiento
          técnico necesario para autenticación, sesión y funcionamiento de la interfaz.
        </p>
      </LegalSection>

      <LegalSection id="cambios-contacto" title="13. Cambios y contacto">
        <p>Última actualización: {LEGAL_LAST_UPDATED}. Versión del documento: académica, sujeta a cambios previos al lanzamiento comercial.</p>
        <p>
          Los cambios relevantes en esta política se van a comunicar actualizando esta misma página. Ante cualquier consulta, podés
          escribirnos desde el <Link href={LEGAL_CONTACT_HREF}>formulario de contacto</Link>.
        </p>
      </LegalSection>
    </LegalPageLayout>
  );
}
