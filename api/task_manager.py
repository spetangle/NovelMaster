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
    steps: list = field(default_factory=list)
    
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
            "steps": self.steps
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
    
    def create_task(self, name: str) -> Task:
        """创建新任务"""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = Task(id=task_id, name=name)
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

    def terminate_all_tasks(self) -> int:
        """终止所有运行中的任务，返回终止的任务数量"""
        count = 0
        with self._lock:
            # 设置全局终止事件
            self._all_tasks_event.set()
            # 重置以便下次使用
            self._all_tasks_event = Event()
            # 终止所有正在运行的任务
            for task_id, event in self._cancel_events.items():
                task = self._tasks.get(task_id)
                if task and task.status == TaskStatus.RUNNING:
                    event.set()
                    self.update_task(task_id, status=TaskStatus.TERMINATED,
                                   message="任务已被终止")
                    count += 1
        return count

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
