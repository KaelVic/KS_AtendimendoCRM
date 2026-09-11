<div align="center">

[🇧🇷 Português](README.md) · 🇺🇸 English · [🇪🇸 Español](README.es.md)

# KS Atendimento IA

**CRM, WhatsApp communication, and artificial intelligence to centralize conversations, leads, sales processes, and AI agents.**

Developed and maintained by **[KaelSolutions](https://kaelsolutions.com.br/)**.

[**Official Website**](https://kaelsolutions.com.br/) · [**Instagram**](https://instagram.com/kaelsolutions) · [**⚡ Deployment**](#-deployment) · [**🔄 Updates**](#-updates) · [**🧭 Vision**](VISION.md) · [**🏗️ Architecture**](ARCHITECTURE.md)

</div>

---

## 🌟 About the Platform

**KS Atendimento IA** is an enterprise platform by **KaelSolutions** designed to centralize and scale sales operations and customer relationships.

The platform unifies within a single interface:

- **WhatsApp Communication:** Resilient connections via QR Code or official Meta Cloud API, with anti-ban throttling, conversation distribution, and real-time queuing.
- **CRM & Lead Management:** 360° customer view, comprehensive message history, internal notes, tags, and customizable pipelines.
- **Artificial Intelligence Agents:** Autonomous native agents that operate the CRM, qualify leads, perform actions, and answer questions using business context.
- **Automations:** Ingestion endpoints and configurable rules (WHEN / IF / THEN) for commercial workflows and external webhooks.
- **RAG / Knowledge Base:** Vector indexing (`pgvector`) isolated per tenant for precise and contextual AI responses.
- **Scheduling / Calendar:** Appointment management integrated into conversations and client timelines.
- **Contact Management:** Unified directory with duplicate detection and chronological activity streams.
- **Sales Funnel:** Visual Kanban board with customizable stages and business terminology adaptable to any industry.
- **AI & Human Collaboration:** Monitored and audited handoff, with smart AI pauses when human agents join the conversation.
- **Multi-tenant Operations:** Structural data isolation enforced by PostgreSQL Row Level Security (RLS).
- **Self-hosted Deployment:** Runs on your own cloud infrastructure or VPS, ensuring full data sovereignty and operational control.

---

## ⚡ Deployment

KS Atendimento IA is packaged for direct deployment to your own cloud infrastructure or VPS via Docker.

### Recommended Requirements

| Resource | Recommendation |
|---|---|
| **Server / VPS** | 2 vCPUs, 4 GB RAM (Ubuntu 22.04+ with Docker) |
| **Domain** | DNS A record pointing to your server's IP address |
| **Database** | Supabase Postgres (with `vector`, `citext`, `pg_trgm` extensions) |
| **AI Provider** | API key of choice (OpenRouter, Anthropic, OpenAI, or Google) |
| **WhatsApp** | Active line for QR Code or Meta Cloud API connection |

### Server Installation

Connect to your server via SSH terminal and execute:

```bash
git clone https://github.com/KaelVic/KS_AtendimendoCRM.git
cd KS_AtendimendoCRM
bash hostgator-setup-kit/install.sh
```

The interactive installer validates configuration parameters, provisions automatic HTTPS certificates, sets up database schemas, and starts all application containers.

---

## 🔄 Updates

The platform includes built-in automated update routines with pre-update backups:

### Through the UI
When a new release is available, the admin dashboard displays a notification under **Settings → Updates**. One-click upgrades perform automated database backups and container migrations.

### Through the Terminal
```bash
cd /path/to/KS_AtendimendoCRM
bash hostgator-setup-kit/update.sh
```

The script creates a security backup, applies schema migrations idempotently, and pulls updated production images.

---

## 🧱 Technical Architecture

| Layer | Technology | Purpose |
|---|---|---|
| **Application** | Next.js 16 (App Router / Turbopack) + React 19 + TypeScript | Enterprise web application and REST API (169 endpoints) |
| **UI & Styling** | Tailwind CSS 4 + KaelSolutions Design System | Design tokens and high-contrast accessible interface (WCAG) |
| **Database** | Supabase Postgres + RLS + pgvector | Native multi-tenancy and semantic vector search for RAG |
| **Authentication** | Supabase Auth + MFA | Secure HttpOnly sessions and two-factor authentication |
| **WhatsApp Engine** | WAHA (NOWEB) & Meta Cloud API | Multi-number connectivity with rate-limiting and anti-ban safeguards |
| **Queues & Background** | `event_log` + Background Workers | Asynchronous job execution for events, AI, and automations |
| **AI Layer** | Vercel AI SDK | Provider-agnostic LLM routing and tool-calling |
| **Observability** | Sentry (configurable opt-in) | Crash analytics with sensitive data scrubbing |

---

## 🖥️ Platform Modules

- **Customer Support:** Real-time multi-channel inbox, Radar view for unhandled conversations, and structured canned responses.
- **Sales & CRM:** Opportunity Kanban board, pipeline stage management, comprehensive customer profiles, and timeline history.
- **AI Agents:** Agent configurations, follow-up automations, routing rules, tenant knowledge base (RAG), and operational memory.
- **Channels & Integrations:** WhatsApp connection management, e-commerce integrations, and incoming lead webhooks.
- **Governance & Teams:** Round-robin lead routing, role-based access controls (RBAC), operational metrics, and append-only audit logs.
- **Privacy & Security:** Privacy governance, data anonymization workflows, and two-factor authentication settings.

---

## 📚 Technical Documentation

- [`VISION.md`](VISION.md) — Product vision and strategic positioning.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Architectural overview and data flow models.
- [`CHANGELOG.md`](CHANGELOG.md) — Version history and release notes.
- [`docs/SETUP.md`](docs/SETUP.md) — Development environment configuration guide.
- [`docs/white-label.md`](docs/white-label.md) — Branding and organizational identity guidelines.
- [`legal/THIRD_PARTY_NOTICES.md`](legal/THIRD_PARTY_NOTICES.md) — Legal notices and third-party software licenses.

---

## 🏢 KaelSolutions

**KS Atendimento IA** is engineered and maintained by **KaelSolutions**.

- **Website:** [https://kaelsolutions.com.br/](https://kaelsolutions.com.br/)
- **Instagram:** [@kaelsolutions](https://instagram.com/kaelsolutions)
