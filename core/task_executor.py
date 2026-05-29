# -*- coding: utf-8 -*-
"""
任务包执行器
负责执行任务包中的子任务流
"""

import threading
import time
from typing import Optional

from core.llm_tasks import (
    TaskPackage, SubTask, TaskStatus, StepStatus,
    LLMCallable, LLMResult, GeneratorTask, WordCountAdjustTask,
    ReviewTask, RevisionTask, ExpanderTask, CondenserTask
)
from api.task_manager import task_manager


# Agent名称到任务类的映射
AGENT_TASK_MAP = {
    "generator": GeneratorTask,
    "writer": GeneratorTask,
    "expander": ExpanderTask,
    "condenser": CondenserTask,
    "auditor": ReviewTask,
    "reviewer": ReviewTask,
    "reviser": RevisionTask,
    "revision": RevisionTask,
    "word_count_adjuster": WordCountAdjustTask,
}


def get_task_class(agent_name: str) -> Optional[type]:
    """根据agent名称获取对应的任务类"""
    return AGENT_TASK_MAP.get(agent_name.lower())


def execute_subtask(subtask: SubTask, context: dict = None) -> LLMResult:
    """执行单个子任务"""
    task_class = get_task_class(subtask.agent)
    if not task_class:
        return LLMResult(
            success=False,
            error=f"未知的agent类型: {subtask.agent}"
        )

    task_instance = task_class()

    if context is None:
        context = {"input_text": subtask.input_text}
    elif "input_text" not in context:
        context["input_text"] = subtask.input_text

    return task_instance.execute(context)


class TaskExecutor:
    """任务包执行器"""

    def __init__(self):
        self._executors: dict = {}  # 正在执行的任务包ID -> 线程

    def execute_package(self, package_id: str, context: dict = None) -> None:
        """在线程中执行任务包

        Args:
            package_id: 任务包ID
            context: 额外的执行上下文
        """
        pkg = task_manager.get_package(package_id)
        if not pkg:
            return

        # 获取书籍锁
        if not task_manager.acquire_book_lock(pkg.book_id, package_id):
            pkg.status = TaskStatus.FAILED
            return

        try:
            pkg.status = TaskStatus.RUNNING

            for i, subtask in enumerate(pkg.subtasks):
                # 检查暂停事件
                if pkg.pause_event.wait(timeout=0.1):
                    pkg.status = TaskStatus.PAUSED
                    pkg.paused_subtask = i
                    return

                # 检查停止事件
                if pkg.stop_event.is_set():
                    pkg.status = TaskStatus.STOPPED
                    return

                # 更新当前子任务索引
                pkg.current_subtask_index = i
                subtask.status = StepStatus.RUNNING
                subtask.started_at = time.time()

                # 执行子任务
                result = execute_subtask(subtask, context)
                subtask.result = result
                subtask.completed_at = time.time()

                if result.success:
                    subtask.status = StepStatus.SUCCESS
                else:
                    subtask.status = StepStatus.FAILED
                    subtask.error = result.error
                    pkg.status = TaskStatus.FAILED
                    break

            # 所有子任务完成
            if pkg.status == TaskStatus.RUNNING:
                pkg.status = TaskStatus.SUCCESS
                print(f"[TaskExecutor] 任务包全部完成: {pkg.name} (id={package_id})")

        finally:
            # 释放书籍锁
            task_manager.release_book_lock(pkg.book_id, package_id)

    def start_package(self, package_id: str, context: dict = None) -> bool:
        """启动任务包执行（异步）

        Returns:
            是否成功启动
        """
        pkg = task_manager.get_package(package_id)
        if not pkg:
            return False

        if package_id in self._executors:
            return False  # 已在执行中

        thread = threading.Thread(
            target=self._run_package,
            args=(package_id, context),
            daemon=True,
            name=f"pkg-{package_id}"
        )
        self._executors[package_id] = thread
        thread.start()
        return True

    def _run_package(self, package_id: str, context: dict = None):
        """内部方法：运行任务包"""
        try:
            self.execute_package(package_id, context)
        finally:
            self._executors.pop(package_id, None)

    def is_running(self, package_id: str) -> bool:
        """检查任务包是否正在执行"""
        return package_id in self._executors

    def get_status(self, package_id: str) -> Optional[dict]:
        """获取任务包执行状态"""
        pkg = task_manager.get_package(package_id)
        if not pkg:
            return None
        return {
            "id": pkg.id,
            "name": pkg.name,
            "status": pkg.status,
            "is_running": self.is_running(package_id),
            "current_subtask_index": pkg.current_subtask_index,
            "total_subtasks": len(pkg.subtasks)
        }


# 全局执行器实例
task_executor = TaskExecutor()