export type ConversationControlState =
  | 'BOT_ACTIVE'
  | 'HUMAN_REQUESTED'
  | 'HUMAN_ACTIVE'
  | 'AI_ASSISTED_PENDING'
  | 'BOT_RESUMING'
  | 'CLOSED';

export interface ComponentHealth {
  status: 'healthy' | 'unhealthy' | 'degraded';
  latency_ms?: number;
  message?: string;
  details?: Record<string, any>;
}

export interface SystemHealthResponse {
  status: 'healthy' | 'unhealthy';
  service: string;
  version: string;
  environment: string;
  components: Record<string, ComponentHealth>;
}
