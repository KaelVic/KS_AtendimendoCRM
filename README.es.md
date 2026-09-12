<div align="center">

[🇧🇷 Português](README.md) · [🇺🇸 English](README.en.md) · 🇪🇸 Español

# KS Atendimento IA

**CRM, atención por WhatsApp e inteligencia artificial para centralizar conversaciones, leads, procesos comerciales y agentes de IA.**

Producto desarrollado y mantenido por **[KaelSolutions](https://kaelsolutions.com.br/)**.

[**Sitio Oficial**](https://kaelsolutions.com.br/) · [**Instagram**](https://instagram.com/kaelsolutions) · [**⚡ Implementación**](#-implementación) · [**🔄 Actualización**](#-actualización) · [**🧭 Visión**](VISION.md) · [**🏗️ Arquitectura**](ARCHITECTURE.md)

</div>

---

## 🌟 Sobre la Plataforma

**KS Atendimento IA** es una plataforma de **KaelSolutions** diseñada para centralizar y potenciar la operación de ventas y relacionamiento con clientes.

La plataforma unifica en una única interfaz:

- **Atención por WhatsApp:** Conexiones resilientes mediante código QR o canal oficial Meta Cloud API, con protección anti-bloqueo, distribución de conversaciones y cola en tiempo real.
- **CRM y Gestión de Leads:** Visión 360° del cliente, historial completo de mensajes, notas internas, etiquetas y embudos personalizables.
- **Agentes de Inteligencia Artificial:** Agentes autónomos nativos que operan el CRM, califican contactos, ejecutan tareas y responden dudas con contexto real de negocio.
- **Automatizaciones:** Puntos de captación y reglas configurables (CUANDO / SI / ENTONCES) para automatización de procesos comerciales e integración con sistemas externos.
- **RAG / Base de Conocimiento:** Indexación vectorial (`pgvector`) aislada por organización para respuestas contextualizadas y precisas de la IA.
- **Agenda:** Gestión de citas y compromisos integrada a la conversación y al historial del cliente.
- **Gestión de Contactos:** Directorio unificado de clientes con cronología de interacciones y detección de duplicados.
- **Embudo Comercial:** Tablero Kanban visual ágil con etapas personalizables y terminología adaptable a cualquier sector.
- **Colaboración entre IA y Atención Humana:** Handoff asistido y auditado, con pausas inteligentes de la IA cuando un agente humano interviene en la conversación.
- **Operación Multiempresa (Multi-tenant):** Aislamiento estructural de datos mediante Row Level Security (RLS) en la base de datos.
- **Implementación Self-hosted:** Ejecución en infraestructura propia o servidor VPS dedicado, garantizando soberanía completa sobre los datos y las reglas operativas.

---

## ⚡ Implementación

KS Atendimento IA está preparado para implementarse directamente en su propia infraestructura en la nube o servidor VPS mediante Docker.

### Requisitos recomendados

| Recurso | Recomendación |
|---|---|
| **Servidor / VPS** | 2 vCPUs, 4 GB de RAM (Ubuntu 22.04+ con Docker) |
| **Dominio** | Registro DNS tipo A apuntando a la IP del servidor |
| **Base de Datos** | Supabase Postgres (con extensiones `vector`, `citext`, `pg_trgm`) |
| **Proveedor de IA** | Clave de API de su elección (OpenRouter, Anthropic, OpenAI o Google) |
| **WhatsApp** | Línea activa para conexión vía código QR o Meta Cloud API |

### Instalación en el Servidor

Conéctese a su servidor mediante terminal SSH y ejecute:

```bash
git clone https://github.com/KaelVic/KS_AtendimendoCRM.git
cd KS_AtendimendoCRM
bash hostgator-setup-kit/install.sh
```

El asistente interactivo valida los parámetros técnicos, aprovisiona certificados HTTPS automáticos, configura la estructura de la base de datos e inicializa los contenedores del sistema.

---

## 🔄 Actualización

El sistema cuenta con mecanismos integrados de actualización segura con respaldo previo:

### Desde la Interfaz
Cuando se publica una nueva versión, el panel muestra una notificación en **Configuración → Actualización**. La actualización con un clic realiza un respaldo automático de la base de datos y actualiza los contenedores sin necesidad de usar el terminal.

### Desde el Terminal
```bash
cd /ruta/hacia/KS_AtendimendoCRM
bash hostgator-setup-kit/update.sh
```

El script genera un respaldo de seguridad, aplica actualizaciones de esquema de forma idempotente y descarga las imágenes actualizadas de producción.

---

## 🧱 Arquitectura Tecnológica

| Capa | Tecnología | Finalidad |
|---|---|---|
| **Aplicación** | Next.js 16 (App Router / Turbopack) + React 19 + TypeScript | Aplicación web y API REST corporativa (169 endpoints) |
| **Diseño e Interfaz** | Tailwind CSS 4 + Design System KaelSolutions | Tokens de diseño e interfaz de alto contraste accesible (WCAG) |
| **Base de Datos** | Supabase Postgres + RLS + pgvector | Multi-tenancy nativo y búsqueda semántica para RAG |
| **Autenticación** | Supabase Auth + MFA | Sesiones seguras HttpOnly y autenticación de dos factores |
| **Motor de WhatsApp** | WAHA (NOWEB) y Meta Cloud API | Conexión multi-número con control de tasa y salvaguardas anti-bloqueo |
| **Colas y Tareas** | `event_log` + Workers dedicados | Ejecución asíncrona de eventos, IA y automatizaciones |
| **Capa de IA** | Vercel AI SDK | Integración flexible y agnóstica con modelos de lenguaje |
| **Observabilidad** | Sentry (opt-in configurable) | Monitoreo y diagnóstico con saneamiento previo de datos sensibles |

---

## 🖥️ Módulos de la Plataforma

- **Atención:** Bandeja de entrada multicanal en tiempo real, vista Radar para conversaciones que requieren atención y respuestas rápidas guardadas.
- **CRM:** Tablero Kanban de oportunidades, gestión de etapas del embudo, fichas completas de contactos e historial cronológico.
- **Agentes de IA:** Configuración de agentes autónomos, flujos de seguimiento, enrutamiento inteligente, base de conocimiento (RAG) y memoria operativa.
- **Canales e Integraciones:** Gestión de conexiones de WhatsApp, integraciones con plataformas de comercio electrónico y webhooks de captación de leads.
- **Gobernanza y Equipos:** Distribución por turnos rotativos, control de acceso basado en roles (RBAC), métricas operativas y registro de auditoría append-only.
- **Privacidad y Seguridad:** Panel de gobierno de datos y privacidad, flujos de anonimización y configuración de seguridad.

---

## 📚 Documentación Técnica

- [`VISION.md`](VISION.md) — Visión del producto y posicionamiento estratégico.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Arquitectura técnica y modelos de flujo de datos.
- [`CHANGELOG.md`](CHANGELOG.md) — Historial de versiones y notas de lanzamiento.
- [`docs/SETUP.md`](docs/SETUP.md) — Guía de configuración para entornos de desarrollo.
- [`docs/white-label.md`](docs/white-label.md) — Directrices de personalización de marca e identidad corporativa.
- [`legal/THIRD_PARTY_NOTICES.md`](legal/THIRD_PARTY_NOTICES.md) — Avisos legales sobre licencias y componentes de terceros.

---

## 🏢 KaelSolutions

**KS Atendimento IA** es una solución desarrollada y mantenida por **KaelSolutions**.

- **Sitio Web:** [https://kaelsolutions.com.br/](https://kaelsolutions.com.br/)
- **Instagram:** [@kaelsolutions](https://instagram.com/kaelsolutions)
