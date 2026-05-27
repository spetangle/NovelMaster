# -*- coding: utf-8 -*-
"""
异步任务管理器
"""

import uuid
import time
import threading
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass, field
from enum import Enum
from threading import Event


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TERMINATED = "terminated"


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class TaskStep:
    """任务步骤"""
    name: str
    status: StepStatus = StepStatus.PENDING
    result_file: str = ""
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "result_file": self.result_file,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


@dataclass
class Task:
    """任务对象"""
    id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0  # 0-100
    message: str = ""
    result: Any = None
    error: str = ""
    step: str = ""  # 当前步骤名称
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    steps: list = field(default_factory=list)  # 步骤列表
    book_id: str = ""  # 关联的书籍ID
    task_type: str = ""  # 任务类型：create_book, write, auto_write 等
    retry_count: int = 0  # 当前重试次数
    max_retries: int = 3  # 最大重试次数
    llm_error: str = ""  # 最近一次LLM错误信息
    pending_retry: bool = False  # 是否在等待重试
    current_step_index: int = 0  # 当前步骤索引

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "step": self.step,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "steps": [s.to_dict() if isinstance(s, TaskStep) else s for s in self.steps],
            "book_id": self.book_id,
            "type": self.task_type,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "llm_error": self.llm_error,
            "pending_retry": self.pending_retry,
            "current_step_index": self.current_step_index
        }


class TaskManager:
    """任务管理器（线程安全）"""

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()
        self._chapter_locks: Dict[str, str] = {}  # {chapter_key: task_id}
        self._chapter_lock = threading.Lock()
        self._cancel_events: Dict[str, Event] = {}  # {task_id: Event}
        self._all_tasks_event = Event()  # 全局终止事件
    
    def get_chapter_lock(self, book_id: str, chapter_num: int) -> Optional[str]:
        """获取章节锁状态，返回被锁定的任务ID"""
        key = f"{book_id}:{chapter_num}"
        with self._chapter_lock:
            return self._chapter_locks.get(key)
    
    def lock_chapter(self, book_id: str, chapter_num: int, task_id: str) -> bool:
        """锁定章节，返回是否成功"""
        key = f"{book_id}:{chapter_num}"
        with self._chapter_lock:
            if key in self._chapter_locks:
                return False  # 已被锁定
            self._chapter_locks[key] = task_id
            return True
    
    def unlock_chapter(self, book_id: str, chapter_num: int):
        """解锁章节"""
        key = f"{book_id}:{chapter_num}"
        with self._chapter_lock:
            self._chapter_locks.pop(key, None)
    
    def is_chapter_locked(self, book_id: str, chapter_num: int) -> tuple[bool, Optional[str]]:
        """检查章节是否被锁定，返回(是否锁定, 锁定任务ID)"""
        key = f"{book_id}:{chapter_num}"
        with self._chapter_lock:
            task_id = self._chapter_locks.get(key)
            return (task_id is not None, task_id)
    
    def get_locked_chapters(self, book_id: str) -> list:
        """获取书籍的所有被锁定章节"""
        with self._chapter_lock:
            return [
                {"chapter_num": int(key.split(":")[1]), "task_id": task_id}
                for key, task_id in self._chapter_locks.items()
                if key.startswith(f"{book_id}:")
            ]
    
    def create_task(self, name: str, book_id: str = "", task_type: str = "") -> Task:
        """创建新任务"""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = Task(id=task_id, name=name, book_id=book_id, task_type=task_type)
        with self._lock:
            self._tasks[task_id] = task
            self._cancel_events[task_id] = Event()
        return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def list_tasks(self, limit: int = 20) -> list:
        """列出最近的任务"""
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
            return [t.to_dict() for t in tasks[:limit]]
    
    def update_task(self, task_id: str, status: TaskStatus = None, 
                    progress: int = None, message: str = None,
                    result: Any = None, error: str = None,
                    step: str = None):
        """更新任务状态"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
        
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress = max(0, min(100, progress))
        if message is not None:
            task.message = message
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        if step is not None:
            task.step = step
            task.steps.append({"name": step, "time": time.time()})
        
        if status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = time.time()
    
    def remove_task(self, task_id: str):
        """删除任务"""
        with self._lock:
            self._tasks.pop(task_id, None)
            self._cancel_events.pop(task_id, None)
    
    def run_task(self, task_id: str, func: Callable, *args, **kwargs):
        """在线程中运行任务"""
        task = self.get_task(task_id)
        if not task:
            return
        
        def _run():
            try:
                self.update_task(task_id, status=TaskStatus.RUNNING, progress=0, message="开始执行...")
                result = func(*args, **kwargs)
                self.update_task(task_id, status=TaskStatus.SUCCESS, progress=100, 
                                message="完成", result=result)
            except Exception as e:
                self.update_task(task_id, status=TaskStatus.FAILED, 
                                message="执行失败", error=str(e))
        
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return task_id

    def get_cancel_event(self, task_id: str) -> Optional[Event]:
        """获取任务的取消事件"""
        with self._lock:
            return self._cancel_events.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """取消指定任务"""
        cancel_event = self.get_cancel_event(task_id)
        if cancel_event:
            cancel_event.set()
            task = self.get_task(task_id)
            if task and task.status == TaskStatus.RUNNING:
                self.update_task(task_id, status=TaskStatus.TERMINATED,
                               message="任务已被终止")
            return True
        return False

    def retry_task(self, task_id: str) -> bool:
        """重置任务状态，允许重新执行（用于手动重试）"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            # 只允许对失败的任务进行重试
            if task.status != TaskStatus.FAILED:
                return False
            task.status = TaskStatus.PENDING
            task.progress = 0
            task.pending_retry = False
            task.llm_error = ""
            # 重置取消事件
            if task_id in self._cancel_events:
                self._cancel_events[task_id].clear()
            else:
                self._cancel_events[task_id] = Event()
            return True

    def mark_retry_pending(self, task_id: str, error_msg: str) -> bool:
        """标记任务进入LLM错误重试等待状态"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.retry_count += 1
            task.llm_error = error_msg
            task.pending_retry = True
            task.status = TaskStatus.FAILED
            task.message = f"LLM错误（第{task.retry_count}/{task.max_retries}次），等待重试..."
            return True

    def init_task_steps(self, task_id: str, steps_config: list) -> bool:
        """初始化任务步骤列表

        Args:
            task_id: 任务ID
            steps_config: 步骤配置列表，如 ["生成细纲", "生成正文", "调整字数", "质量评审"]

        Returns:
            是否成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.steps = [TaskStep(name=name) for name in steps_config]
            task.current_step_index = 0
            return True

    def update_step_status(self, task_id: str, step_index: int, status: StepStatus,
                           result_file: str = "", error: str = "") -> bool:
        """更新步骤状态

        Args:
            task_id: 任务ID
            step_index: 步骤索引
            status: 新状态
            result_file: 成果文件路径（可选）
            error: 错误信息（可选）

        Returns:
            是否成功
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if step_index < 0 or step_index >= len(task.steps):
                return False

            step = task.steps[step_index]
            step.status = status
            step.result_file = result_file
            step.error = error

            now = time.time()
            if status == StepStatus.RUNNING:
                step.started_at = now
            elif status in (StepStatus.SUCCESS, StepStatus.SKIPPED, StepStatus.FAILED):
                step.completed_at = now

            if status == StepStatus.RUNNING:
                task.current_step_index = step_index
                task.step = step.name
                task.status = TaskStatus.RUNNING

            return True

    def get_task_checklist(self, task_id: str) -> Optional[list]:
        """获取任务步骤 checklist

        Returns:
            步骤列表（每个元素是 dict），如果任务不存在则返回 None
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return task.to_dict().get("steps", [])

    def get_next_pending_step(self, task_id: str) -> int:
        """获取下一个未完成的步骤索引，用于断点恢复

        Returns:
            下一个步骤索引，如果全部完成则返回 -1
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return -1
            for i, step in enumerate(task.steps):
                if step.status in (StepStatus.PENDING, StepStatus.FAILED):
                    return i
            return -1

    def skip_step(self, task_id: str, step_index: int, reason: str = "") -> bool:
        """跳过指定步骤

        Args:
            task_id: 任务ID
            step_index: 步骤索引
            reason: 跳过原因

        Returns:
            是否成功
        """
        return self.update_step_status(task_id, step_index, StepStatus.SKIPPED, error=reason)

    def resume_task(self, task_id: str) -> int:
        """恢复任务，从第一个未完成步骤继续

        Returns:
            开始执行的步骤索引，如果全部完成则返回 -1
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return -1
            next_step = self.get_next_pending_step(task_id)
            if next_step >= 0:
                task.status = TaskStatus.RUNNING
                task.pending_retry = False
                task.llm_error = ""
                # 重置取消事件
                if task_id in self._cancel_events:
                    self._cancel_events[task_id].clear()
                else:
                    self._cancel_events[task_id] = Event()
            return next_step

    def terminate_all_tasks(self) -> int:
        """终止所有运行中的任务，返回终止的任务数量"""
        count = 0
        with self._lock:
            # 设置全局终止事件
            self._all_tasks_event.set()
            # 终止所有正在运行的任务
            for task_id, event in self._cancel_events.items():
                task = self._tasks.get(task_id)
                if task and task.status == TaskStatus.RUNNING:
                    event.set()
                    self.update_task(task_id, status=TaskStatus.TERMINATED,
                                   message="任务已被终止")
                    count += 1
        return count

    def reset_terminate_all_event(self):
        """重置全局终止事件（在所有任务处理完毕后调用）"""
        with self._lock:
            self._all_tasks_event = Event()

    def is_cancelled(self, task_id: str) -> bool:
        """检查任务是否被取消"""
        cancel_event = self.get_cancel_event(task_id)
        if cancel_event:
            return cancel_event.is_set()
        return False

    def is_all_terminated(self) -> bool:
        """检查全局终止事件是否被设置"""
        return self._all_tasks_event.is_set()

    def get_running_tasks(self) -> list:
        """获取所有运行中的任务"""
        with self._lock:
            return [
                t.to_dict() for t in self._tasks.values()
                if t.status == TaskStatus.RUNNING
            ]


# 全局任务管理器
task_manager = TaskManager()
