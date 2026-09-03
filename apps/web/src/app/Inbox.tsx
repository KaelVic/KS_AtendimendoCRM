"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import HealthPanel from "./HealthPanel";

type ControlState = "BOT_ACTIVE" | "HUMAN_REQUESTED" | "HUMAN_ACTIVE" | "AI_ASSISTED_PENDING" | "BOT_RESUMING" | "CLOSED";
type Conversation = { id: string; contact_id: string; channel: string; status: string; control_state: ControlState; control_version?: number; updated_at: string };
type Message = { id: string; conversation_id: string; direction: "INBOUND" | "OUTBOUND"; message_type: string; content: string | null; created_at: string };
type PendingItem = { id: string; conversation_id: string; kind: string; status: "OPEN" | "RESOLVED"; due_at: string; created_at: string; resolved_at: string | null; last_notification: { status: string; attempts: number; sent_at: string | null; next_attempt_at: string | null } | null };
type ApiError = { message?: string };

const tenantId = process.env.NEXT_PUBLIC_TENANT_ID || "00000000-0000-0000-0000-000000000001";
const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Inbox() {
  const [token, setToken] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pendingItems, setPendingItems] = useState<PendingItem[]>([]);
  const [draft, setDraft] = useState("");
  const [attachmentName, setAttachmentName] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState<"connected" | "reconnecting">("reconnecting");

  const headers = useCallback(() => ({ Authorization: `Bearer ${token}`, "Content-Type": "application/json" }), [token]);

  const readError = async (response: Response): Promise<never> => {
    const body = (await response.json().catch(() => ({}))) as ApiError;
    throw new Error(body.message || `Erro HTTP ${response.status}`);
  };

  const loadConversations = useCallback(async () => {
    if (!authenticated) return;
    const response = await fetch(`${apiUrl}/inbox/conversations?tenant_id=${tenantId}`, { headers: headers(), cache: "no-store" });
    if (!response.ok) await readError(response);
    const data = await response.json() as { items: Conversation[] };
    setConversations(data.items);
    setSelected((current) => data.items.find((item) => item.id === current?.id) || current || data.items[0] || null);
    setConnection("connected");
  }, [authenticated, headers]);

  const loadMessages = useCallback(async () => {
    if (!selected || !authenticated) return;
    const response = await fetch(`${apiUrl}/inbox/conversations/${selected.id}/messages?tenant_id=${tenantId}`, { headers: headers(), cache: "no-store" });
    if (!response.ok) await readError(response);
    const data = await response.json() as { items: Message[] };
    setMessages(data.items);
  }, [authenticated, headers, selected]);

  const loadPendingItems = useCallback(async () => {
    if (!authenticated) return;
    const response = await fetch(`${apiUrl}/inbox/pending-items?tenant_id=${tenantId}&status=OPEN`, { headers: headers(), cache: "no-store" });
    if (!response.ok) await readError(response);
    const data = await response.json() as { items: PendingItem[] };
    setPendingItems(data.items);
  }, [authenticated, headers]);

  const refresh = useCallback(async () => {
    try {
      setError("");
      await loadConversations();
      await loadMessages();
      await loadPendingItems();
    } catch (cause) {
      setConnection("reconnecting");
      setError(cause instanceof Error ? cause.message : "Não foi possível atualizar a inbox");
    }
  }, [loadConversations, loadMessages, loadPendingItems]);

  useEffect(() => {
    const saved = window.localStorage.getItem("ks_owner_token");
    if (saved) { setToken(saved); setAuthenticated(true); }
  }, []);

  useEffect(() => {
    if (!authenticated) return;
    setLoading(true);
    void refresh().finally(() => setLoading(false));
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [authenticated, refresh]);

  useEffect(() => { void loadMessages(); }, [loadMessages]);

  async function login(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const response = await fetch(`${apiUrl}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "kaelvictor.devsolution@gmail.com", token }) });
      if (!response.ok) await readError(response);
      window.localStorage.setItem("ks_owner_token", token);
      setAuthenticated(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha de autenticação"); }
  }

  async function control(action: "ASSUME" | "RETURN") {
    if (!selected || controlling) return;
    setControlling(true); setError("");
    try {
      const response = await fetch(`${apiUrl}/inbox/conversations/${selected.id}/control?tenant_id=${tenantId}`, { method: "POST", headers: headers(), body: JSON.stringify({ action, ...(selected.control_version ? { expected_version: selected.control_version } : {}) }) });
      if (!response.ok) await readError(response);
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Ação não confirmada pelo servidor"); }
    finally { setControlling(false); }
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!selected || !draft.trim() || sending) return;
    setSending(true); setError("");
    try {
      const pending = pendingItems.find((item) => item.conversation_id === selected.id && item.status === "OPEN");
      const response = await fetch(pending ? `${apiUrl}/inbox/pending-items/${pending.id}/respond?tenant_id=${tenantId}` : `${apiUrl}/inbox/conversations/${selected.id}/messages?tenant_id=${tenantId}`, { method: "POST", headers: headers(), body: JSON.stringify({ idempotency_key: crypto.randomUUID(), content: draft.trim() }) });
      if (!response.ok) await readError(response);
      setDraft(""); setAttachmentName(""); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Mensagem não enviada"); }
    finally { setSending(false); }
  }

  async function resolvePending(pending: PendingItem) {
    if (controlling) return;
    setControlling(true); setError("");
    try {
      const response = await fetch(`${apiUrl}/inbox/pending-items/${pending.id}/resolve?tenant_id=${tenantId}`, { method: "POST", headers: headers(), body: JSON.stringify({ reason: "Resolvida pelo proprietário no CRM" }) });
      if (!response.ok) await readError(response);
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Resolução não confirmada pelo servidor"); }
    finally { setControlling(false); }
  }

  if (!authenticated) return <main className="auth-shell"><form className="auth-card" onSubmit={login}><span className="eyebrow">KS Atendimento IA</span><h1>Entrar na inbox</h1><p>Use o token do proprietário configurado no ambiente local.</p><label htmlFor="owner-token">Token do proprietário</label><input id="owner-token" type="password" value={token} onChange={(event) => setToken(event.target.value)} required autoComplete="off" /><button className="primary-button" type="submit">Entrar</button>{error && <p className="error" role="alert">{error}</p>}</form></main>;

 return <main className="inbox-shell"><header className="inbox-header"><div><span className="eyebrow">KS Atendimento IA</span><h1>Inbox</h1></div><div className="connection" aria-live="polite"><span className={`status-dot ${connection === "connected" ? "healthy" : "inactive"}`} />{connection === "connected" ? "Conectado" : "Reconectando..."}<button className="ghost-button" onClick={() => void refresh()} disabled={loading} type="button">Atualizar</button></div></header><HealthPanel apiUrl={apiUrl} token={token} />
    {error && <div className="error-banner" role="alert">{error}</div>}
    <section className="inbox-grid" aria-label="Caixa de entrada"><aside className="conversation-list"><div className="section-heading"><h2>Conversas</h2><span>{conversations.length}</span></div>{loading && <p className="muted">Carregando conversas...</p>}{!loading && !conversations.length && <p className="empty-state">Nenhuma conversa ainda.</p>}{conversations.map((conversation) => <button key={conversation.id} className={`conversation-row ${selected?.id === conversation.id ? "selected" : ""}`} onClick={() => setSelected(conversation)} type="button"><span className={`control-pill ${conversation.control_state === "HUMAN_ACTIVE" ? "human" : "bot"}`}>{conversation.control_state === "HUMAN_ACTIVE" ? "HUMAN" : "BOT"}</span><strong>{conversation.contact_id.slice(0, 8)}</strong><small>{conversation.channel} · {new Date(conversation.updated_at).toLocaleTimeString("pt-BR")}</small></button>)}</aside>
      <section className="message-panel" aria-label="Painel de mensagens">{!selected ? <div className="empty-panel"><h2>Selecione uma conversa</h2><p>As mensagens recebidas aparecerão aqui.</p></div> : <><div className="panel-header"><div><span className="eyebrow">{selected.channel}</span><h2>Contato {selected.contact_id.slice(0, 8)}</h2></div><div className="control-actions"><span className={`control-pill ${selected.control_state === "HUMAN_ACTIVE" ? "human" : "bot"}`}>{selected.control_state === "HUMAN_ACTIVE" ? "HUMAN" : "BOT"}</span>{selected.control_state === "HUMAN_ACTIVE" ? <button className="ghost-button" onClick={() => void control("RETURN")} disabled={controlling} type="button">{controlling ? "Devolvendo..." : "Devolver ao robô"}</button> : <button className="primary-button compact" onClick={() => void control("ASSUME")} disabled={controlling} type="button">{controlling ? "Assumindo..." : "Assumir conversa"}</button>}</div></div>{pendingItems.filter((item) => item.conversation_id === selected.id).map((pending) => <div className="pending-banner" key={pending.id} role="status"><div><strong>Pendência: {pending.kind}</strong><small>Prazo: {new Date(pending.due_at).toLocaleString("pt-BR")} · Último alerta: {pending.last_notification?.sent_at ? new Date(pending.last_notification.sent_at).toLocaleString("pt-BR") : "ainda não enviado"}</small></div><button className="ghost-button compact" onClick={() => void resolvePending(pending)} disabled={controlling} type="button">Resolver</button></div>)}<div className="messages" aria-live="polite">{!messages.length && <p className="empty-state">Nenhuma mensagem nesta conversa.</p>}{messages.map((message) => <article key={message.id} className={`message-bubble ${message.direction === "OUTBOUND" ? "outbound" : "inbound"}`}><p>{message.content || `[${message.message_type}]`}</p><time>{new Date(message.created_at).toLocaleString("pt-BR")}</time></article>)}</div><form className="composer" onSubmit={send}><label htmlFor="message-draft">Mensagem</label><textarea id="message-draft" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={selected.control_state === "HUMAN_ACTIVE" ? "Escreva uma resposta..." : "Assuma a conversa para responder"} disabled={selected.control_state !== "HUMAN_ACTIVE" || sending} rows={3} /><div className="composer-footer"><label className="attachment-button" htmlFor="attachment">Anexar arquivo<input id="attachment" type="file" onChange={(event) => setAttachmentName(event.target.files?.[0]?.name || "")} disabled={selected.control_state !== "HUMAN_ACTIVE"} /></label>{attachmentName && <span className="attachment-name">{attachmentName} · upload pendente</span>}<button className="primary-button" type="submit" disabled={selected.control_state !== "HUMAN_ACTIVE" || sending || !draft.trim()}>{sending ? "Enviando..." : "Enviar"}</button></div></form></>}</section></section>
  </main>;
}
