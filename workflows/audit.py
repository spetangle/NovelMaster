# -*- coding: utf-8 -*-
"""
审核工作流
"""

from typing import Dict, Any, Optional, Callable
from datetime import datetime
from pathlib import Path

from agents.engine import AgentEngine
from core.state_manager import StateManager
from core.models import BookInfo


class AuditWorkflow:
    """审核工作流"""

    # 工作流配置
    WORKFLOW_CONFIG = [
        {"role": "auditor", "on_failure": "abort"},
        {"role": "continuity_auditor", "on_failure": "skip"},
    ]

    def __init__(self, state_manager: StateManager, agent_engine: AgentEngine):
        self.sm = state_manager
        self.engine = agent_engine

    def execute_audit(
        self,
        book_id: str,
        chapter_num: int,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        审核章节

        Args:
            book_id: 书籍ID
            chapter_num: 章节号
            progress_callback: 进度回调

        Returns:
            审核结果
        """
        def report(step: str, progress: int, message: str):
            if progress_callback:
                progress_callback(step, progress, message)

        book = self.sm.get_book_by_id(book_id)
        if not book:
            return {"success": False, "message": "书籍不存在"}

        chapter_title = "序章" if chapter_num == 0 else f"第{chapter_num}章"
        chapter_path = self.sm.workspace / book.path / "chapters" / f"chapter_{chapter_num}.md"

        if not chapter_path.exists():
            return {"success": False, "message": f"{chapter_title}不存在"}

        try:
            # 读取章节内容
            chapter_content = self.sm.fm.read_text(chapter_path)

            # 加载真相文件
            truth_files = self._load_truth_files(book)

            context = {
                "book": book.to_dict(),
                "chapter_num": chapter_num,
                "chapter_content": chapter_content,
                "truth_files": truth_files
            }

            # 执行审核
            report("审核中", 30, f"正在审核{chapter_title}...")
            audit_result = self.engine.call_agent("auditor", context)
            audit_data = audit_result.data if audit_result.success else {}

            # 执行连贯性审计
            report("连贯性检查", 60, f"正在检查{chapter_title}连贯性...")
            continuity_result = self.engine.call_agent("continuity_auditor", context)
            continuity_data = continuity_result.data if continuity_result.success else {}

            # 生成报告
            score = audit_data.get("chapter_score", 0)
            decision = self._make_decision(score)

            report("完成", 100, f"审核完成，得分 {score}")

            return {
                "success": True,
                "chapter_num": chapter_num,
                "chapter_title": chapter_title,
                "audit_result": audit_data,
                "continuity_result": continuity_data,
                "score": score,
                "decision": decision,
                "message": f"{chapter_title}审核完成"
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"审核失败: {str(e)}"}

    def execute_golden_audit(
        self,
        book_id: str,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        黄金三章专项审核

        Args:
            book_id: 书籍ID
            progress_callback: 进度回调

        Returns:
            审核结果
        """
        def report(step: str, progress: int, message: str):
            if progress_callback:
                progress_callback(step, progress, message)

        book = self.sm.get_book_by_id(book_id)
        if not book:
            return {"success": False, "message": "书籍不存在"}

        try:
            # 读取前三章内容
            chapters = []
            for i in range(1, 4):
                chapter_path = self.sm.workspace / book.path / "chapters" / f"chapter_{i}.md"
                if chapter_path.exists():
                    content = self.sm.fm.read_text(chapter_path)
                    chapters.append({"chapter": i, "content": content})

            if len(chapters) < 3:
                missing = [i for i in range(1, 4) if i not in [c["chapter"] for c in chapters]]
                return {
                    "success": False,
                    "message": f"第{missing}章内容缺失",
                    "decision": "missing"
                }

            # 组合内容
            combined_content = "\n\n".join([
                f"【第{c['chapter']}章】\n{c['content'][:3000]}"
                for c in chapters
            ])

            context = {
                "book": book.to_dict(),
                "chapter_content": combined_content,
                "extra": {"audit_type": "golden"}
            }

            # 执行连贯性审计（黄金三章）
            report("黄金三章审核", 50, "正在审核前三章...")
            result = self.engine.call_agent("continuity_auditor", context)
            data = result.data if result.success else {}

            golden_score = data.get("overall_score", 0) * 10
            decision = self._make_decision(golden_score, threshold=80)

            report("完成", 100, f"黄金三章审核完成，得分 {golden_score}")

            return {
                "success": True,
                "chapters": [c["chapter"] for c in chapters],
                "score": golden_score,
                "decision": decision,
                "details": data,
                "message": f"黄金三章审核完成"
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"审核失败: {str(e)}"}

    def _load_truth_files(self, book: BookInfo) -> Dict[str, str]:
        """加载真相文件"""
        truth_dir = self.sm.workspace / book.path / "truth_files"
        files = {}

        for filename in ["current_state.md", "pending_hooks.md",
                        "character_matrix.md", "chapter_summaries.md"]:
            path = truth_dir / filename
            if path.exists():
                files[filename.replace(".md", "")] = self.sm.fm.read_text(path)

        return files

    def _make_decision(self, score: int, threshold: int = 75) -> str:
        """根据评分做出决策"""
        if score >= threshold:
            return "通过"
        elif score >= 60:
            return "修订建议"
        else:
            return "不通过"