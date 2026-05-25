# -*- coding: utf-8 -*-
"""
章节创作工作流
"""

from typing import Dict, Any, Optional, Callable
from datetime import datetime
from pathlib import Path

from agents.engine import AgentEngine
from core.state_manager import StateManager
from core.models import BookInfo


class ChapterWritingWorkflow:
    """章节创作工作流"""

    # 工作流配置
    WORKFLOW_CONFIG = [
        {"role": "architect", "on_failure": "skip", "params": {"type": "outline"}},
        {"role": "writer", "on_failure": "abort"},
        {"role": "auditor", "on_failure": "abort", "retry": 3},
        {"role": "hook_manager", "on_failure": "skip"},
        {"role": "observer", "on_failure": "skip"},
    ]

    def __init__(self, state_manager: StateManager, agent_engine: AgentEngine):
        self.sm = state_manager
        self.engine = agent_engine

    def execute(
        self,
        book_id: str,
        chapter_num: int,
        progress_callback: Optional[Callable] = None,
        cancel_check: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        执行章节创作工作流

        Args:
            book_id: 书籍ID
            chapter_num: 章节号
            progress_callback: 进度回调
            cancel_check: 取消检查

        Returns:
            创作结果
        """
        def report(step: str, progress: int, message: str):
            print(f"[{progress}%] {step}: {message}")
            if progress_callback:
                progress_callback(step, progress, message)

        def is_cancelled():
            if cancel_check:
                return cancel_check()
            return False

        book = self.sm.get_book_by_id(book_id)
        if not book:
            return {"success": False, "message": "书籍不存在"}

        chapter_title = "序章" if chapter_num == 0 else f"第{chapter_num}章"
        chapter_path = self.sm.workspace / book.path / "chapters" / f"chapter_{chapter_num}.md"

        try:
            # Step 1: 加载真相文件
            report(f"加载{chapter_title}", 5, "正在加载上下文...")
            if is_cancelled():
                return {"success": False, "message": "任务被取消", "cancelled": True}

            truth_files = self._load_truth_files(book)
            context = {
                "book": book.to_dict(),
                "chapter_num": chapter_num,
                "truth_files": truth_files
            }

            # Step 2: 生成章节细纲
            report(f"生成{chapter_title}细纲", 15, "正在生成章节细纲...")
            if is_cancelled():
                return {"success": False, "message": "任务被取消", "cancelled": True}

            architect_result = self.engine.call_agent("architect", {
                **context,
                "prompt": f"请为{chapter_title}生成章节细纲"
            })
            outline = architect_result.content if architect_result.success else ""

            # 保存章节细纲
            if outline:
                outline_path = self.sm.workspace / book.path / "chapters" / f"outline_{chapter_num}.md"
                self.sm.fm.write_text(outline_path, outline)

            # Step 3: 创作正文
            report(f"创作{chapter_title}", 30, "正在创作章节正文...")
            if is_cancelled():
                return {"success": False, "message": "任务被取消", "cancelled": True}

            writer_result = self.engine.call_agent("writer", {
                **context,
                "prompt": f"请创作{chapter_title}",
                "extra": {"outline": outline}
            })

            if not writer_result.success:
                return {"success": False, "message": "章节创作失败"}

            chapter_content = writer_result.content

            # Step 4: 保存章节
            report(f"保存{chapter_title}", 50, "正在保存章节内容...")
            self.sm.fm.write_text(chapter_path, chapter_content)

            # Step 5: 审核
            report(f"审核{chapter_title}", 60, "正在审核章节...")
            if is_cancelled():
                return {"success": False, "message": "任务被取消", "cancelled": True}

            audit_result = self.engine.call_agent("auditor", {
                **context,
                "chapter_content": chapter_content
            })

            audit_data = audit_result.data if audit_result.success else {}
            score = audit_data.get("chapter_score", 0)
            decision = audit_data.get("decision", "通过")

            # Step 6: 更新状态
            self.sm.update_chapter_status(
                book, chapter_num,
                status="draft",
                audit_score=score,
                audit_passed=score >= 75,
                retry_count=0
            )

            # Step 7: 更新伏笔
            if is_cancelled():
                return {"success": False, "message": "任务被取消", "cancelled": True}

            self.engine.call_agent("hook_manager", {
                **context,
                "chapter_content": chapter_content
            })

            # Step 8: 更新真相文件
            self.engine.call_agent("observer", {
                **context,
                "chapter_content": chapter_content
            })

            report(f"完成{chapter_title}", 100, f"{chapter_title}创作完成，得分 {score}")

            return {
                "success": True,
                "chapter_num": chapter_num,
                "chapter_title": chapter_title,
                "outline": outline,
                "outline_path": str(outline_path) if outline else None,
                "content": chapter_content,
                "audit_result": audit_data,
                "score": score,
                "decision": decision,
                "message": f"{chapter_title}创作完成"
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"创作失败: {str(e)}"}

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