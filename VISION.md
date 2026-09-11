# 🧭 Visão do Produto — KS Atendimento IA

> **A plataforma de vendas, atendimento por WhatsApp e agentes de inteligência artificial da KaelSolutions.**

---

## O que é

**KS Atendimento IA** é a plataforma da **KaelSolutions** desenvolvida para centralizar CRM, atendimento por WhatsApp e agentes de inteligência artificial em uma operação comercial unificada.

Toda a operação de vendas de um negócio — atendimento, qualificação, funil, agendamentos e pós-venda — é gerenciada em um único ambiente onde profissionais humanos e agentes de IA colaboram de forma sinérgica e auditável.

A plataforma vai além de um CRM tradicional: é o sistema operacional onde a venda acontece diretamente no canal em que o cliente conversa.

---

## Posicionamento

**KS Atendimento IA** é uma plataforma corporativa e tecnológica para:

- **Atendimento por WhatsApp:** Gestão centralizada de conversas em tempo real.
- **CRM e Gestão de Leads:** Visão completa do cliente e histórico de interações.
- **Agentes de Inteligência Artificial:** Agentes operacionais autônomos integrados ao CRM.
- **Automações:** Regras configuráveis de processos e integrações.
- **RAG / Base de Conhecimento:** Indexação contextual de dados da empresa por organização.
- **Agenda:** Gestão integrada de compromissos e agendamentos.
- **Gestão de Contatos:** Cadastro inteligente e unificado com detecção de duplicidades.
- **Funil Comercial:** Visualização em Kanban com etapas customizáveis por nicho.
- **Colaboração entre IA e Atendimento Humano:** Transição fluida e auditada entre IA e equipe humana.
- **Operação Multiempresa:** Arquitetura multi-tenant com estrita segregação de dados.
- **Implantação Self-hosted:** Soberania total sobre dados e infraestrutura.

---

## Filosofia dos Agentes de IA

1. **Agente que opera, não chatbot que enfeita:**
   O agente lê o contexto real do contato (histórico, dados cadastrais, notas internas), consulta a base de conhecimento do tenant (RAG por organização), qualifica leads, movimenta oportunidades no funil e atua como operador no sistema sob as mesmas regras de governança de um atendente humano.

2. **Aprimoramento contínuo:**
   O ecossistema é projetado para evoluir: conversas enriquecem a base de conhecimento; handoffs para operadores humanos indicam oportunidades de melhoria de contexto; métricas de uso e limites operacionais garantem controle contínuo.

3. **Arquitetura aberta para extensões (MCP):**
   O CRM expõe suas capacidades operacionais para agentes e ferramentas externas via Model Context Protocol (MCP), permitindo orquestração fluida de tarefas (consulta a pedidos, agendamento, movimentação no funil).

4. **Supervisão humana e governança:**
   Handoff auditado com registro em log, controle de acesso baseado em papéis (RBAC), controle de fila em tempo real e limites orçamentários por organização. A autonomia do agente opera sempre sob parâmetros definidos pela empresa.

---

## Pilares da Plataforma

| Pilar | O que significa na prática |
|---|---|
| **Agentes de IA Nativos** | RAG isolado por tenant, análise de sentimento, handoff auditado, IA como operador responsável e limites de consumo por organização |
| **CRM com Automação Inteligente** | Movimentação automática de estágios no funil, aplicação de tags, acionamento de fluxos e webhooks |
| **Apoio Operacional ao Vendedor** | Inbox multicanal em tempo real, Kanban visual ágil, visão 360° do cliente e distribuição automática de conversas |
| **Conexão WhatsApp Resiliente** | Suporte a WAHA (NOWEB) e Meta Cloud API oficial, proteção anti-bloqueio, envio de mídias e tratamento de cancelamento |
| **Multi-nicho por Design** | Vocabulário configurável por funil (Lead = Cliente/Paciente/Comprador; Ganho = Fechado/Agendado/Pago), atendendo diversos segmentos de mercado |
| **Soberania e Self-hosted** | Dados hospedados na infraestrutura do próprio cliente ou servidor VPS dedicado, com rotinas seguras de backup e atualização |
| **Segurança e Conformidade** | Multi-tenancy com Row Level Security (RLS) verificado, governança de dados alinhada à LGPD e registros de auditoria append-only |

---

## Modelo de Distribuição

- **Infraestrutura Dedicada:** A plataforma é executada em servidores VPS ou infraestrutura em nuvem dedicada via contêineres Docker, conferindo total privacidade e controle operacional à empresa.
- **Portabilidade:** Scripts de automação facilitam a instalação, configuração de certificados HTTPS e aplicação idempotente de estruturas de banco de dados.

---

*KS Atendimento IA — KaelSolutions.*
