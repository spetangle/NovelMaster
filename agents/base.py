# -*- coding: utf-8 -*-
"""
通用 Agent 基类
通过职责文件配置，支持不同角色
"""

import json
import re
from typing import Dict, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime

from .loader import AgentRole, AgentLoader
from core.word_count_template import get_chapter_level, get_level_adaptation_guide, format_level_prompt
from core.llm_service import LLMError


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool = False
    content: str = ""
    data: Optional[Dict] = None
    error: str = ""
    agent_name: str = ""
    execution_time: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "content": self.content,
            "data": self.data,
            "error": self.error,
            "agent_name": self.agent_name,
            "execution_time": self.execution_time,
            "timestamp": self.timestamp
        }


class UniversalAgent:
    """通用 Agent - 通过职责文件配置"""

    def __init__(self, role: AgentRole, llm_manager=None):
        self.role = role
        self.llm = llm_manager
        self._prompt_builder: Optional[Callable] = None

    def set_llm(self, llm_manager):
        """设置 LLM 管理器"""
        self.llm = llm_manager

    def set_prompt_builder(self, builder: Callable):
        """设置自定义 Prompt 构建器"""
        self._prompt_builder = builder

    def execute(self, context: dict) -> AgentResult:
        """
        执行 Agent 任务

        Args:
            context: 上下文字典，包含任务所需的全部信息
                - prompt: 用户输入的 prompt
                - book: 书籍信息 (可选)
                - chapter_num: 章节号 (可选)
                - truth_files: 真相文件 (可选)
                - extra: 其他扩展信息 (可选)

        Returns:
            AgentResult: 执行结果
        """
        import time
        start_time = time.time()
        execution_time = 0.0

        result = AgentResult(
            agent_name=self.role.name,
            timestamp=datetime.now().isoformat()
        )

        if not self.llm:
            result.error = "LLM 管理器未设置"
            return result

        try:
            # 构建 prompt
            if self._prompt_builder:
                prompt = self._prompt_builder(context)
            else:
                prompt = self._build_prompt(context)

            # 获取替换后的系统提示词（注入书籍配置）
            system_prompt = self._inject_book_config(context)

            print(f"[Agent] {self.role.name} 开始执行...")

            # 调用 LLM
            if self.role.output_format == "json":
                response = self.llm.generate_json(prompt, system_prompt, self.role.name)
                if response:
                    result.content = json.dumps(response, ensure_ascii=False)
                    result.data = response
                    result.success = True
                    print(f"[Agent] {self.role.name} 执行完成 (JSON)")
                else:
                    result.error = "JSON 解析失败"
            else:
                try:
                    response = self.llm.generate(prompt, system_prompt, self.role.name)
                    result.content = response
                    result.success = True
                    print(f"[Agent] {self.role.name} 执行完成 ({len(response)} 字符)")
                except LLMError as e:
                    result.content = ""
                    result.success = False
                    result.error = str(e)
                    print(f"[Agent] {self.role.name} 执行失败: {str(e)[:100]}")

        except Exception as e:
            print(f"[Agent] {self.role.name} 执行异常: {str(e)} [{execution_time:.1f}s]")

        execution_time = time.time() - start_time
        result.execution_time = execution_time

        if result.success:
            if result.data:
                print(f"[Agent] {self.role.name} 执行完成 (JSON) [{execution_time:.1f}s]")
            else:
                print(f"[Agent] {self.role.name} 执行完成 ({len(result.content)} 字符) [{execution_time:.1f}s]")
        else:
            print(f"[Agent] {self.role.name} 执行失败: {result.error[:100] if result.error else 'unknown'} [{execution_time:.1f}s]")

        return result

    def _inject_book_config(self, context: dict) -> str:
        """将书籍配置注入到系统提示词的占位符中"""
        system_prompt = self.role.system_prompt

        # 获取书籍配置
        book = context.get("book", {})
        if isinstance(book, dict):
            words_per_chapter = book.get("words_per_chapter", 3000)
        else:
            words_per_chapter = 3000

        # 根据字数确定章节级别
        chapter_level = get_chapter_level(words_per_chapter)
        level_guide = get_level_adaptation_guide(chapter_level)
        level_config = format_level_prompt(chapter_level)

        # 获取字数宽容度
        from core.word_count_template import get_config_by_word_count
        config = get_config_by_word_count(words_per_chapter)
        tolerance = config.word_tolerance if config else 300

        # 替换占位符
        replacements = {
            "{words_per_chapter}": str(words_per_chapter),
            "{book_id}": book.get("id", ""),
            "{book_name}": book.get("name", ""),
            "{genre}": book.get("genre", ""),
            "{platform}": book.get("platform", ""),
            "{chapter_level}": chapter_level.value,
            "{level_adaptation_guide}": level_guide,
            "{level_config}": level_config,
            "{tolerance}": str(tolerance),
        }

        for placeholder, value in replacements.items():
            if placeholder in system_prompt:
                system_prompt = system_prompt.replace(placeholder, value)

        return system_prompt

    def _build_prompt(self, context: dict) -> str:
        """构建 prompt"""
        prompt_parts = []

        # 基础 prompt
        if "prompt" in context:
            prompt_parts.append(str(context["prompt"]))

        # 书籍信息
        if "book" in context:
            book = context["book"]
            prompt_parts.append(f"\n\n书籍信息：\n书名：{book.get('name', '')}\n题材：{book.get('genre', '')}\n")

        # 章节号
        if "chapter_num" in context:
            chapter_num = context["chapter_num"]
            chapter_title = "序章" if chapter_num == 0 else f"第{chapter_num}章"
            prompt_parts.append(f"\n\n当前章节：{chapter_title}")

        # 真相文件上下文
        if "truth_files" in context:
            truth_files = context["truth_files"]
            context_info = []
            if truth_files.get('current_state'):
                context_info.append(f"【世界状态】\n{truth_files['current_state'][:500]}")
            if truth_files.get('pending_hooks'):
                context_info.append(f"【待回收伏笔】\n{truth_files['pending_hooks'][:500]}")
            if truth_files.get('character_matrix'):
                context_info.append(f"【角色状态】\n{truth_files['character_matrix'][:500]}")
            if context_info:
                prompt_parts.append("\n\n" + "\n\n".join(context_info))

        # 章节内容
        if "chapter_content" in context:
            prompt_parts.append(f"\n\n章节正文：\n{context['chapter_content'][:3000]}")

        # 扩展信息
        if "extra" in context:
            extra = context["extra"]
            if isinstance(extra, dict):
                for key, value in extra.items():
                    if value:
                        prompt_parts.append(f"\n\n【{key}】\n{value}")

        return "\n".join(prompt_parts)

    def validate_output(self, response: str) -> tuple[bool, Optional[Dict]]:
        """验证输出格式"""
        if self.role.output_format != "json":
            return True, None

        try:
            # 尝试提取 JSON
            text = response.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            data = json.loads(text.strip())

            # 检查必需字段
            for field in self.role.required_fields:
                if field not in data:
                    return False, None

            return True, data
        except json.JSONDecodeError:
            return False, None