# -*- coding: utf-8 -*-
"""
NovelMaster 核心模块
提供独立可调用的核心功能
"""

from .novel_engine import NovelEngine
from .models import (
    BookInfo, ChapterInfo, ChapterStatus, ChapterStatusEnum,
    AuditResult, AuditDecision, HookInfo, GlobalConfig, WorkflowResult,
    BookSettings, ChapterAuditLog, AuditLogTable
)
from .file_manager import FileManager
from .state_manager import StateManager
from .llm_service import LLMService, LLMConfig, LLMClient, LLMManager

__all__ = [
    # 核心引擎
    'NovelEngine',
    # 数据模型
    'BookInfo',
    'ChapterInfo',
    'ChapterStatus',
    'ChapterStatusEnum',
    'AuditResult',
    'AuditDecision',
    'HookInfo',
    'GlobalConfig',
    'WorkflowResult',
    'BookSettings',
    'ChapterAuditLog',
    'AuditLogTable',
    # 管理器
    'FileManager',
    'StateManager',
    # LLM
    'LLMService',
    'LLMConfig',
    'LLMClient',
    'LLMManager',
]
