# -*- coding: utf-8 -*-
"""
NovelMaster Agent 系统
提供通用 Agent 引擎和职责驱动机制
"""

from .base import UniversalAgent, AgentResult
from .engine import AgentEngine
from .loader import AgentLoader

__all__ = [
    'UniversalAgent',
    'AgentResult',
    'AgentEngine',
    'AgentLoader',
]