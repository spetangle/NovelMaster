# -*- coding: utf-8 -*-
"""
章节创作工作流
"""

import re
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
        {"role": "reflector", "on_failure": "skip"},
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

            # 加载上一章的反思报告（Reflector 输出），为本章提供策略指导
            if chapter_num > 1:
                reflection_path = self.sm.workspace / book.path / "chapters" / f"reflection_{chapter_num - 1}.md"
                if reflection_path.exists():
                    previous_reflection = self.sm.fm.read_text(reflection_path)
                    if previous_reflection:
                        context["previous_reflection"] = previous_reflection

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

            chapter_content = self._filter_llm_output(writer_result.content)

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
            observer_result = self.engine.call_agent("observer", {
                **context,
                "chapter_content": chapter_content
            })

            # Step 9: 反思与策略调整（Observer → Reflector 链路）
            try:
                reflector_result = self.engine.call_agent("reflector", {
                    **context,
                    "chapter_content": chapter_content,
                    "chapter_outline": outline,
                    "observer_result": observer_result.data if (observer_result.success and observer_result.data) else {}
                })
                if reflector_result.success and reflector_result.content:
                    reflection_path = self.sm.workspace / book.path / "chapters" / f"reflection_{chapter_num}.md"
                    self.sm.fm.write_text(reflection_path, reflector_result.content)
            except Exception as e:
                print(f"[Reflector] 反思失败: {e}")

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

    def _filter_llm_output(self, content: str) -> str:
        """过滤LLM输出的说明性内容，只保留章节正文"""
        # 移除 LOG 块（多个短横线包围的内容，多行）
        content = re.sub(r'━{3,}\s*\n(?:.*?\n)*?.*?━{3,}', '', content, flags=re.DOTALL)

        # 移除 [LOG] 块（标准格式）
        content = re.sub(r'\[LOG\][^\[]*?(?=\[LOG\]|$)', '', content, flags=re.DOTALL)

        # 移除 "以下是..." 类引导语
        content = re.sub(r'^以下(是|为).*?[:：]\s*', '', content, flags=re.MULTILINE)

        # 移除行首的任务说明标签
        content = re.sub(r'^\[LOG\].*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^任务名称:.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^当前 Agent:.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^当前阶段:.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^预计产出:.*$', '', content, flags=re.MULTILINE)

        # 移除 "缩写原则"、"扩写原则" 等说明段落
        content = re.sub(r'^(缩|扩)写原则.*$(?:\n(?![①②③④⑤⑥⑦⑧⑨⑩]|\d+\.).*$)', '', content, flags=re.MULTILINE)

        # 移除 "字数要求"、"输出规范"、"调用规范" 等说明段落
        content = re.sub(r'^(字数要求|输出规范|调用规范).*$(?:\n(?![①②③④⑤⑥⑦⑧⑨⑩]|\d+\.).*$)', '', content, flags=re.MULTILINE)

        # 移除 AI 思考过程标签
        content = re.sub(r'<think>[\s\S]*?', '', content, flags=re.DOTALL)

        # 移除 markdown 代码块
        content = re.sub(r'```[\s\S]*?```', '', content)

        # 清理多余的空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        # 移除行首和行尾空白
        lines = content.split('\n')
        lines = [line.strip() for line in lines]
        content = '\n'.join(line for line in lines if line)

        return content

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