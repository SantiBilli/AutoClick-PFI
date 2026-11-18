import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { MotionConfig } from "framer-motion";
import "./globals.css";
// Imported after globals so the portal design system has the final word on
// any shared selector it deliberately restyles.
import "./dashboard.css";
import { DemoProvider } from "../components/demo/DemoProvider";

// Keep font assets in the repository so production builds do not fetch Google Fonts.
const manrope = localFont({
  src: "./fonts/Manrope-Variable.ttf",
  weight: "200 800",
  style: "normal",
  display: "swap",
  variable: "--font-manrope",
});
const jetbrainsMono = localFont({
  src: "./fonts/JetBrainsMono-Variable.ttf",
  weight: "400 600",
  style: "normal",
  display: "swap",
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: { default: "AutoClick | Automatización para equipos", template: "%s | AutoClick" },
  description: "Portal de AutoClick: consumo de tokens, áreas, usuarios y acceso a AutoClick Desktop.",
  applicationName: "AutoClick",
  openGraph: {
    title: "AutoClick | Automatización para equipos",
    description: "Portal de AutoClick: consumo de tokens, áreas, usuarios y acceso a AutoClick Desktop.",
    type: "website",
    locale: "es_AR",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#e7ebf4",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body className={`${manrope.variable} ${manrope.className} ${jetbrainsMono.variable}`}><MotionConfig reducedMotion="user"><DemoProvider>{children}</DemoProvider></MotionConfig></body>
    </html>
  );
}
