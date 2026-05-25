# -*- coding: utf-8 -*-
"""
书籍创建工作流
"""

from typing import Dict, Any, Optional, Callable
from datetime import datetime
from pathlib import Path

from agents.engine import AgentEngine, WorkflowResult
from core.state_manager import StateManager
from core.models import BookInfo


class BookCreationWorkflow:
    """书籍创建工作流"""

    # 工作流配置：各 Agent 及其失败处理策略
    WORKFLOW_CONFIG = [
        {"role": "radar", "on_failure": "skip"},
        {"role": "planner", "on_failure": "abort"},
        {"role": "architect", "on_failure": "abort"},
        {"role": "hook_manager", "on_failure": "skip"},
    ]

    def __init__(self, state_manager: StateManager, agent_engine: AgentEngine):
        self.sm = state_manager
        self.engine = agent_engine

    def execute(
        self,
        brief: str,
        book_id: str,
        progress_callback: Optional[Callable] = None,
        cancel_check: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        执行书籍创建工作流

        Args:
            brief: 创作简报
            book_id: 书籍ID
            progress_callback: 进度回调函数
            cancel_check: 取消检查函数

        Returns:
            创建结果
        """
        def report(step: str, progress: int, message: str):
            print(f"[{progress}%] {step}: {message}")
            if progress_callback:
                progress_callback(step, progress, message)

        def is_cancelled():
            if cancel_check:
                return cancel_check()
            return False

        try:
            # Step 1: 解析简报
            report("解析简报", 5, "正在解析创作简报...")
            if is_cancelled():
                return {"success": False, "message": "任务被取消", "cancelled": True}

            # 调用 Planner Agent
            planner_result = self.engine.call_agent("planner", {"prompt": brief})
            if not planner_result.success:
                return {"success": False, "message": "简报解析失败"}

            planning_data = planner_result.data or {}
            book_name = planning_data.get("book_name", book_id)

            # Step 2: 创建书籍记录
            report("创建书籍", 15, f"正在创建书籍《{book_name}》...")
            if is_cancelled():
                return {"success": False, "message": "任务被取消", "cancelled": True}

            book = BookInfo(
                id=book_id,
                name=book_name,
                path=f"books/{book_id}",
                genre=planning_data.get("genre", "都市"),
                platform=planning_data.get("platform", "番茄小说"),
                words_per_chapter=planning_data.get("words_per_chapter", 3000),
                total_chapters=planning_data.get("estimated_chapters", 80),
                created_at=datetime.now().isoformat()
            )
            success, msg = self.sm.create_book(book)
            if not success:
                return {"success": False, "message": msg}

            # Step 3: 生成世界观
            report("生成世界观", 30, "正在创建世界观设定...")
            if is_cancelled():
                return {"success": False, "message": "任务被取消", "cancelled": True}

            architect_result = self.engine.call_agent("architect", {
                "prompt": "请生成世界观设定",
                "book": book.to_dict(),
                "extra": {"planning": planning_data}
            })

            story_bible = architect_result.content if architect_result.success else ""

            # Step 4: 生成创作规则
            report("生成规则", 50, "正在创建创作规则...")
            if is_cancelled():
                return {"success": False, "message": "任务被取消", "cancelled": True}

            # 可以再次调用 architect 生成规则，或使用其他 Agent
            book_rules = story_bible  # 简化处理

            # Step 5: 保存文件
            report("保存文件", 70, "正在保存设定文件...")
            book_path = self.sm.workspace / book.path
            self.sm.fm.write_text(book_path / "story_bible.md", story_bible)
            self.sm.fm.write_text(book_path / "book_rules.md", book_rules)
            self.sm.fm.write_text(book_path / "planning.md", planner_result.content)

            # Step 6: 初始化项目状态
            report("初始化状态", 85, "正在初始化项目状态...")
            self._init_project_state(book)

            # Step 7: 初始化真相文件
            report("初始化真相文件", 95, "正在初始化真相文件...")
            self._init_truth_files(book)

            report("完成", 100, f"《{book.name}》创建成功！")

            return {
                "success": True,
                "book": book.to_dict(),
                "planning": planning_data,
                "message": f"《{book.name}》创建成功"
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"创建失败: {str(e)}"}

    def _init_project_state(self, book: BookInfo):
        """初始化项目状态"""
        state = {
            "book_id": book.id,
            "book_name": book.name,
            "genre": book.genre,
            "platform": book.platform,
            "words_per_chapter": book.words_per_chapter,
            "total_chapters": book.total_chapters,
            "chapter_planning": {},
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        self.sm.save_project_state(book, state)

    def _init_truth_files(self, book: BookInfo):
        """初始化真相文件"""
        truth_dir = self.sm.workspace / book.path / "truth_files"

        # 当前世界状态
        current_state = f"""# {book.name} 当前世界状态

## 最后更新时间
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 世界设定
[待填充]

## 当前时间线
[待填充]

## 重要地点
[待填充]
"""
        self.sm.fm.write_text(truth_dir / "current_state.md", current_state)

        # 伏笔总表
        pending_hooks = f"""# {book.name} 伏笔总表

## 最后更新时间
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 待回收伏笔
| 伏笔ID | 类型 | 内容摘要 | 预期回收章节 |
|--------|------|----------|--------------|

## 已回收伏笔
| 伏笔ID | 回收章节 | 回收说明 |
|--------|----------|----------|
"""
        self.sm.fm.write_text(truth_dir / "pending_hooks.md", pending_hooks)

        # 角色矩阵
        character_matrix = f"""# {book.name} 角色矩阵

## 最后更新时间
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 主角
[待填充]

## 主要配角
[待填充]

## 势力/组织
[待填充]
"""
        self.sm.fm.write_text(truth_dir / "character_matrix.md", character_matrix)

        # 章节摘要
        chapter_summaries = f"""# {book.name} 章节摘要

## 最后更新时间
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

"""
        self.sm.fm.write_text(truth_dir / "chapter_summaries.md", chapter_summaries)