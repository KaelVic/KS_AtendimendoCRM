// This file configures the initialization of Sentry on the server.
// The config you add here will be used whenever the server handles a request.
// https://docs.sentry.io/platforms/javascript/guides/nextjs/

import * as Sentry from "@sentry/nextjs";
import { resolveSentryDsn, isCommunityDsn } from "./lib/sentry/dsn";
import { sentryScrubHooks } from "./lib/sentry/scrub";

const sentryDsn = resolveSentryDsn(process.env.SENTRY_DSN);
const community = isCommunityDsn(sentryDsn);

Sentry.init({
  dsn: sentryDsn,

  // No Sentry do operador: amostragem padrão (100% erro / traces configuráveis).
  tracesSampleRate: community ? 0 : 1,
  enableLogs: true,
  sendDefaultPii: false,

  ...sentryScrubHooks,
});

// Transparência de telemetria: uma linha no boot dizendo o status atual.
if (!sentryDsn) {
  console.info("[telemetria] Desligada — nenhum erro é enviado (defina SENTRY_DSN para ativar seu próprio monitoramento).");
} else {
  console.info("[telemetria] Erros sendo enviados ao Sentry configurado em SENTRY_DSN.");
}
