<div align="center">

🇧🇷 Português · [🇺🇸 English](README.en.md) · [🇪🇸 Español](README.es.md)

# KS Atendimento IA

**CRM, atendimento WhatsApp e inteligência artificial para centralizar conversas, leads, processos comerciais e agentes de IA.**

Produto desenvolvido e mantido pela **[KaelSolutions](https://kaelsolutions.com.br/)**.

[**Site Oficial**](https://kaelsolutions.com.br/) · [**Instagram**](https://instagram.com/kaelsolutions) · [**⚡ Implantação**](#-implantação) · [**🔄 Atualização**](#-atualização) · [**🧭 Visão**](VISION.md) · [**🏗️ Arquitetura**](ARCHITECTURE.md)

</div>

---

## 🌟 Sobre a Plataforma

**KS Atendimento IA** é uma plataforma da **KaelSolutions** desenvolvida para centralizar e potencializar a operação de vendas e relacionamento com clientes.

A plataforma unifica em uma única interface:

- **Atendimento por WhatsApp:** Conexões resilientes via QR Code ou canal oficial Meta Cloud API, com proteção anti-banimento, distribuição de conversas e fila em tempo real.
- **CRM e Gestão de Leads:** Visão 360° do cliente, histórico completo de mensagens, notas internas, tags e funis personalizáveis.
- **Agentes de Inteligência Artificial:** Agentes autônomos nativos que operam o CRM, qualificam contatos, executam tarefas e respondem dúvidas com contexto real.
- **Automações:** Fontes de captação e regras configuráveis (QUANDO / SE / ENTÃO) para automação de processos comerciais e acionamento de sistemas externos.
- **RAG / Base de Conhecimento:** Indexação vetorial (`pgvector`) isolada por tenant para respostas contextualizadas e precisas da IA.
- **Agenda:** Gestão de compromissos e agendamentos integrada à conversa e ao histórico do cliente.
- **Gestão de Contatos:** Cadastro unificado de clientes com linha do tempo de interações e detecção de duplicidades.
- **Funil Comercial:** Kanban visual ágil com estágios customizáveis e vocabulário adaptável para qualquer nicho de mercado.
- **Colaboração entre IA e Atendimento Humano:** Handoff assistido e auditado, com pausas inteligentes da IA quando um atendente assume a conversa.
- **Operação Multiempresa (Multi-tenant):** Isolamento estrutural de dados com Row Level Security (RLS) no banco de dados.
- **Implantação Self-hosted:** Execução em infraestrutura própria ou VPS dedicada, garantindo soberania completa sobre dados e regras operacionais.

---

## ⚡ Implantação

O KS Atendimento IA foi concebido para ser implantado diretamente em sua própria infraestrutura de nuvem ou servidor VPS via Docker.

### Requisitos recomendados

| Recurso | Recomendação |
|---|---|
| **Servidor / VPS** | 2 vCPUs, 4 GB de RAM (Ubuntu 22.04+ com Docker) |
| **Domínio** | Registro DNS tipo A apontando para o IP do servidor |
| **Banco de Dados** | Supabase Postgres (com extensões `vector`, `citext`, `pg_trgm`) |
| **Provedor de IA** | Chave de API de sua escolha (OpenRouter, Anthropic, OpenAI ou Google) |
| **WhatsApp** | Linha ativa para conexão via QR Code ou Meta Cloud API |

### Instalação no Servidor

Conecte-se ao seu servidor via terminal SSH e execute:

```bash
git clone https://github.com/KaelVic/KS_AtendimendoCRM.git
cd KS_AtendimendoCRM
bash hostgator-setup-kit/install.sh
```

O assistente de instalação valida os parâmetros técnicos, provisiona certificados HTTPS automáticos, aplica a estrutura de banco de dados e inicializa os contêineres do sistema.

---

## 🔄 Atualização

O sistema possui mecanismos integrados de atualização segura com backup prévio:

### Pela Interface
Quando uma nova versão é publicada, o painel exibe um aviso em **Configurações → Atualização**. O processo realiza backup automático do banco e atualiza a aplicação sem necessidade de intervenção por terminal.

### Pelo Terminal
```bash
cd /caminho/do/KS_AtendimendoCRM
bash hostgator-setup-kit/update.sh
```

O script efetua backup de segurança, aplica eventuais atualizações de schema de forma idempotente e atualiza os contêineres de produção.

---

## 🧱 Arquitetura Tecnológica

| Camada | Tecnologia | Finalidade |
|---|---|---|
| **Aplicação** | Next.js 16 (App Router / Turbopack) + React 19 + TypeScript | Aplicação web e API REST corporativa (169 endpoints) |
| **Design & UI** | Tailwind CSS 4 + Design System KaelSolutions | Interface com tokens consistentes e alto contraste (WCAG) |
| **Banco de Dados** | Supabase Postgres + RLS + pgvector | Multi-tenancy nativo e busca semântica para RAG |
| **Autenticação** | Supabase Auth + MFA | Controle de acesso seguro com cookies HttpOnly e dois fatores |
| **WhatsApp Engine** | WAHA (NOWEB) & Meta Cloud API | Conexão multi-número com controle de taxa e proteção anti-ban |
| **Filas & Background** | `event_log` + Workers dedicados | Execução assíncrona de rotinas, IA e automações |
| **Camada de IA** | Vercel AI SDK | Integração flexível com provedores de modelos de linguagem |
| **Observabilidade** | Sentry (opt-in configurável) | Monitoramento com higienização prévia de dados sensíveis |

---

## 🖥️ Módulos da Plataforma

- **Atendimento:** Inbox multicanal em tempo real, Radar de conversas que demandam atenção, respostas rápidas pré-cadastradas.
- **CRM:** Quadro Kanban de oportunidades, gestão de etapas do funil, cadastro completo de contatos e histórico de interações.
- **Agentes de IA:** Configuração de agentes autônomos, fluxos de follow-up, roteadores de atendimento, base de conhecimento (RAG), skills e memória operacional.
- **Canais & Integrações:** Gerenciamento de conexões WhatsApp, integração com plataformas de e-commerce e webhooks de captação de leads.
- **Governança & Equipe:** Fila de distribuição com rodízio inteligente, controle de papéis (RBAC), métricas operacionais e log de auditoria append-only.
- **Privacidade:** Painel de conformidade LGPD, anonimização de dados e gestão de credenciais e segurança.

---

## 📚 Documentação Técnica

- [`VISION.md`](VISION.md) — Visão do produto e posicionamento estratégico.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Arquitetura técnica e fluxos de dados.
- [`CHANGELOG.md`](CHANGELOG.md) — Registro de versões e notas de lançamento.
- [`docs/SETUP.md`](docs/SETUP.md) — Guia de configuração para ambiente de desenvolvimento.
- [`docs/white-label.md`](docs/white-label.md) — Diretrizes de personalização de marca e identidade visual.
- [`legal/THIRD_PARTY_NOTICES.md`](legal/THIRD_PARTY_NOTICES.md) — Avisos legais sobre licenças e componentes de terceiros.

---

## 🏢 KaelSolutions

O **KS Atendimento IA** é uma solução desenvolvida e mantida pela **KaelSolutions**.

- **Site:** [https://kaelsolutions.com.br/](https://kaelsolutions.com.br/)
- **Instagram:** [@kaelsolutions](https://instagram.com/kaelsolutions)
