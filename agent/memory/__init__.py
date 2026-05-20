"""
Memory module for AgentMesh

Provides both long-term memory (vector/keyword search) and short-term
conversation history persistence (SQLite).
"""

from agent.memory.manager import MemoryManager
from agent.memory.config import MemoryConfig, get_default_memory_config, set_global_memory_config
from agent.memory.embedding import create_embedding_provider
from agent.memory.conversation_store import ConversationStore, get_conversation_store
from agent.memory.summarizer import ensure_daily_memory_file
from agent.memory.work_state import WorkStateManager
from agent.memory.realtime import RealtimeMemoryRecorder
from agent.memory.query_service import MemoryQueryService
from agent.memory.bootstrap import MemoryBootstrap
from agent.memory.error_memory import ErrorMemoryRecorder
from agent.memory.error_capture import (
    build_error_memory_context,
    is_user_correction,
    record_agent_error,
    record_tool_error,
    record_user_correction_if_needed,
)

__all__ = [
    'MemoryManager',
    'MemoryConfig',
    'get_default_memory_config',
    'set_global_memory_config',
    'create_embedding_provider',
    'ConversationStore',
    'get_conversation_store',
    'ensure_daily_memory_file',
    'WorkStateManager',
    'RealtimeMemoryRecorder',
    'MemoryQueryService',
    'MemoryBootstrap',
    'ErrorMemoryRecorder',
    'build_error_memory_context',
    'is_user_correction',
    'record_agent_error',
    'record_tool_error',
    'record_user_correction_if_needed',
]
