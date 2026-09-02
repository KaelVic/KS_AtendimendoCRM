from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    status: str = Field(..., description="'healthy', 'unhealthy' ou 'degraded'")
    latency_ms: Optional[float] = Field(None, description="Latência de verificação em milissegundos")
    message: Optional[str] = Field(None, description="Detalhes adicionais ou causa de falha")
    details: Optional[Dict[str, Any]] = None


class SystemHealthResponse(BaseModel):
    status: str = Field(..., description="Status geral da stack ('healthy' ou 'unhealthy')")
    service: str = "ks-atendimento-api"
    version: str = "0.1.0"
    environment: str
    components: Dict[str, ComponentHealth]
