import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "KS Atendimento IA — Painel de Controle e Status",
  description: "Plataforma própria da KaelSolutions para CRM, WhatsApp, IA e Vendas",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
