from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Callable
import asyncio
import threading
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from common.log import logger as _logger


class TextbookBaseAgent(ABC):
    def __init__(self, llm_model=None, on_event: Callable = None):
        self.llm_model = llm_model
        self.on_event = on_event
        self.name = self.__class__.__name__
        self.cancel_event = None

    def set_cancel_event(self, event: threading.Event):
        self.cancel_event = event

    @abstractmethod
    def get_system_prompt(self) -> str:
        pass

    @abstractmethod
    def get_agent_type(self) -> str:
        pass

    def emit_event(self, event_type: str, data: dict):
        if self.on_event:
            self.on_event({
                'type': event_type,
                'agent': self.name,
                'data': data,
            })

    async def run(self, input_data: dict, context: dict = None) -> dict:
        self.emit_event('agent_call', {'input_summary': str(input_data)[:200]})

        system_prompt = self.get_system_prompt()
        user_prompt = self._build_user_prompt(input_data, context)

        if self.cancel_event and self.cancel_event.is_set():
            return {'error': 'Cancelled', 'status': 'cancelled'}

        if self.llm_model:
            try:
                result = await self._call_llm(system_prompt, user_prompt)
                if result and isinstance(result, str) and result.startswith('[CANCELLED]'):
                    self.emit_event('agent_result', {'status': 'cancelled', 'error': 'LLM call cancelled'})
                    return {'error': 'Cancelled', 'status': 'cancelled'}
                output = self._parse_output(result, input_data)
                self.emit_event('agent_result', {'status': 'success', 'output_summary': str(output)[:200]})
                return output
            except Exception as e:
                self.emit_event('agent_result', {'status': 'error', 'error': str(e)})
                return {'error': str(e), 'status': 'failed'}
        else:
            return {'status': 'no_llm', 'message': 'LLM model not configured'}

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        _logger.info(f"[{self.name}] _call_llm called, has_llm={hasattr(self.llm_model, 'call')}")
        if hasattr(self.llm_model, 'call'):
            try:
                loop = asyncio.get_event_loop()
                _logger.info(f"[{self.name}] Calling LLM via run_in_executor...")
                result = await loop.run_in_executor(
                    None,
                    lambda: self.llm_model.call(
                        [{'role': 'system', 'content': system_prompt},
                         {'role': 'user', 'content': user_prompt}],
                        cancel_event=self.cancel_event
                    )
                )
                _logger.info(f"[{self.name}] LLM returned, result_len={len(result) if result else 0}, preview={str(result)[:100] if result else 'None'}")
                return result or ""
            except Exception as e:
                _logger.error(f"[{self.name}] LLM call exception: {e}", exc_info=True)
                self.emit_event('agent_result', {'status': 'error', 'error': str(e)})
                return ""
        _logger.warning(f"[{self.name}] No LLM model with 'call' method available")
        return ""

    def _build_user_prompt(self, input_data: dict, context: dict = None) -> str:
        return str(input_data)

    def _parse_output(self, llm_output: str, input_data: dict) -> dict:
        return {'raw_output': llm_output}

    def run_standalone(self, input_data: dict) -> dict:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.run(input_data))
