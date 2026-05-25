# -*- coding: utf-8 -*-
"""
状态管理器
负责书籍索引和项目状态的管理
"""

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from .file_manager import FileManager
from .models import BookInfo, ChapterStatus


class StateManager:
    """状态管理核心"""

    MAX_RETRY_COUNT = 3  # 单章重写上限

    def __init__(self, workspace: str):
        self.fm = FileManager(workspace)
        self.workspace = Path(workspace)
        self.book_index = self._load_book_index()
        self._lock = threading.Lock()  # 线程锁，保护 book_index 的并发访问

    def _load_book_index(self) -> dict:
        """加载书籍索引"""
        data = self.fm.read_json(self.fm.book_index_path)
        if not data:
            data = {"books": [], "current_novel": "", "last_updated": ""}
        return data

    def _save_book_index(self) -> bool:
        """保存书籍索引"""
        return self.fm.write_json(self.fm.book_index_path, self.book_index)

    def get_current_book(self) -> Optional[BookInfo]:
        """获取当前小说"""
        current_id = self.book_index.get("current_novel", "")
        if not current_id:
            return None
        for book in self.book_index.get("books", []):
            if book.get("id") == current_id:
                return BookInfo.from_dict(book)
        return None

    def get_book_by_id(self, book_id: str) -> Optional[BookInfo]:
        """通过ID获取书籍"""
        with self._lock:
            for book in self.book_index.get("books", []):
                if book.get("id") == book_id:
                    return BookInfo.from_dict(book)
            return None

    def get_book_by_name(self, name: str) -> Optional[BookInfo]:
        """通过名称匹配书籍"""
        name_lower = name.lower()
        with self._lock:
            for book in self.book_index.get("books", []):
                book_name = book.get("name", "").lower()
                if name_lower == book_name or name_lower in book_name or book_name in name_lower:
                    return BookInfo.from_dict(book)
            return None

    def get_all_books(self) -> List[BookInfo]:
        """获取所有书籍"""
        return [BookInfo.from_dict(b) for b in self.book_index.get("books", [])]

    def switch_book(self, book_id_or_name: str) -> tuple[bool, str]:
        """切换当前小说"""
        book = self.get_book_by_id(book_id_or_name)
        if not book:
            book = self.get_book_by_name(book_id_or_name)
        if not book:
            return False, f"未找到书籍: {book_id_or_name}"

        self.book_index["current_novel"] = book.id
        self.book_index["last_updated"] = datetime.now().isoformat()
        if self._save_book_index():
            return True, f"已切换至《{book.name}》"
        return False, "状态文件保存失败"

    def create_book(self, book_info: BookInfo) -> tuple[bool, str]:
        """创建新书籍"""
        with self._lock:
            for book in self.book_index.get("books", []):
                if book["id"] == book_info.id:
                    return False, f"书籍ID {book_info.id} 已存在"

            book_dict = book_info.to_dict()
            self.book_index["books"].append(book_dict)
            self.book_index["current_novel"] = book_info.id
            self.book_index["last_updated"] = datetime.now().isoformat()

            # 创建目录结构
            book_path = self.workspace / book_info.path
            for d in ["chapters", "truth_files", "planning_files"]:
                (book_path / d).mkdir(parents=True, exist_ok=True)

            if self._save_book_index():
                return True, f"书籍《{book_info.name}》创建成功"
            return False, "状态文件保存失败"

    def delete_book(self, book_id: str) -> tuple[bool, str]:
        """删除书籍"""
        with self._lock:
            books = self.book_index.get("books", [])
            book_to_delete = None
            for book in books:
                if book.get("id") == book_id:
                    book_to_delete = book
                    break

            if not book_to_delete:
                return False, "书籍不存在"

            books = [b for b in books if b.get("id") != book_id]
            self.book_index["books"] = books

            if self.book_index.get("current_novel") == book_id:
                self.book_index["current_novel"] = books[0]["id"] if books else ""

            self.book_index["last_updated"] = datetime.now().isoformat()

            if self._save_book_index():
                return True, f"书籍已删除"
            return False, "状态文件保存失败"

    def load_project_state(self, book: BookInfo) -> dict:
        """加载项目状态"""
        path = self.workspace / book.path / "project_state.json"
        return self.fm.read_json(path)

    def save_project_state(self, book: BookInfo, state: dict) -> bool:
        """保存项目状态"""
        path = self.workspace / book.path / "project_state.json"
        return self.fm.write_json(path, state)

    def update_chapter_status(
        self,
        book: BookInfo,
        chapter_num: int,
        status: str,
        audit_score: int = 0,
        audit_passed: bool = False,
        finalized: bool = False,
        retry_count: int = None
    ) -> bool:
        """更新章节状态"""
        state = self.load_project_state(book)
        chapter_key = f"chapter_{chapter_num}"
        if chapter_key not in state.get("chapter_planning", {}):
            state.setdefault("chapter_planning", {})[chapter_key] = {}

        chapter = state["chapter_planning"][chapter_key]
        chapter["approval_status"] = status
        chapter["last_updated"] = datetime.now().isoformat()

        if audit_score > 0:
            chapter["audit_score"] = audit_score
            chapter["audit_passed"] = audit_passed
        if finalized:
            chapter["finalized"] = True
        if retry_count is not None:
            chapter["retry_count"] = retry_count

        return self.save_project_state(book, state)