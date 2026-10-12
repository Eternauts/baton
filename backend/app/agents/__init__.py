# The original GeminiAgentService lives in legacy.py; re-exported so existing imports keep working.
from app.agents.legacy import GeminiAgentService, RegexDocumentService

__all__ = ["GeminiAgentService", "RegexDocumentService"]
