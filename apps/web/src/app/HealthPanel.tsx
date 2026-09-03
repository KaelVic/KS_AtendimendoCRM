"use client";

import { useCallback, useEffect, useState } from "react";

type HealthDetails = {
  connection?: string;
  relink_required?: boolean;
  last_webhook?: string;
  last_receipt?: string;
  last_failure_code?: string;
  owner_or_shard?: string;
};

type HealthComponent = {
  status: string;
  message?: string | null;
  version?: string | null;
  session_label?: string | null;
  details?: HealthDetails;
};

type HealthResponse = { status: string; components: Record<string, HealthComponent> };

export default function HealthPanel({ apiUrl, token }: { apiUrl: string; token: string }) {
  const [report, setReport] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const response = await fetch(`${apiUrl}/health/owner`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    const body = (await response.json().catch(() => null)) as HealthResponse | null;
    if (!response.ok || !body) throw new Error("Não foi possível consultar a saúde");
    setReport(body);
    setError(null);
  }, [apiUrl, token]);

  useEffect(() => {
    void refresh().catch((cause: unknown) =>
      setError(cause instanceof Error ? cause.message : "Falha na consulta de saúde"),
    );
    const timer = window.setInterval(() => {
      void refresh().catch(() => setError("Falha na atualização de saúde"));
    }, 10000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const session = report?.components.whatsapp_session;
  const details = session?.details;

  return (
    <section className="health-panel" aria-label="Saúde das integrações">
      <div className="section-heading">
        <div><span className="eyebrow">Operação</span><h2>Saúde do canal</h2></div>
        <span className={`health-badge ${report?.status === "healthy" ? "healthy" : "unhealthy"}`}>
          {report?.status === "healthy" ? "READY" : report ? "ATENÇÃO" : "CONSULTANDO"}
        </span>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="health-grid">
        <div><span>Conexão</span><strong>{details?.connection ?? "unknown"}</strong></div>
        <div><span>Relink</span><strong>{details?.relink_required ? "necessário" : "não indicado"}</strong></div>
        <div><span>Último webhook</span><strong>{details?.last_webhook ?? "unknown"}</strong></div>
        <div><span>Último receipt</span><strong>{details?.last_receipt ?? "unknown"}</strong></div>
        <div><span>Owner/shard</span><strong>{details?.owner_or_shard ?? "unknown"}</strong></div>
        <div><span>Falha</span><strong>{details?.last_failure_code ?? "none"}</strong></div>
      </div>
      <small className="health-note">
        Sessão {session?.session_label ?? "não identificada"} · versão {session?.version ?? "unknown"}. QR e credenciais nunca são renderizados.
      </small>
    </section>
  );
}
