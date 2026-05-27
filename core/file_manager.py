# -*- coding: utf-8 -*-
"""
文件管理器
负责文件和目录的读写操作
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any


class FileManager:
    """文件读写管理"""

    def __init__(self, workspace: str):
        self.workspace = Path(workspace)
        self.book_index_path = self.workspace / "book_index.json"

    def read_json(self, path: Path, max_retries: int = 3) -> dict:
        """读取JSON文件（带重试机制，防止读取到不完整的写入）"""
        if not path.exists():
            return {}
        import time
        import os
        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    try:
                        with open(path, 'rb') as f:
                            f.flush()
                            os.fsync(f.fileno())
                    except:
                        pass
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                if attempt < max_retries - 1:
                    time.sleep(0.1)
                    continue
                raise
        return {}

    def write_json(self, path: Path, data: dict) -> bool:
        """写入JSON文件"""
        import os
        import traceback
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            return True
        except Exception as e:
            print(f"[write_json] 写入JSON失败: {e}")
            traceback.print_exc()
            return False

    def read_text(self, path: Path) -> str:
        """读取文本文件"""
        if not path.exists():
            return ""
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def write_text(self, path: Path, content: str, log_content: bool = False) -> bool:
        """写入文本文件

        Args:
            path: 文件路径
            content: 文件内容
            log_content: 是否记录内容到日志（默认False，仅记录操作）
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            # 记录文件写入操作
            content_len = len(content)
            if log_content and content_len <= 1000:
                print(f"[FileManager] ✓ Write: {path} ({content_len} chars)")
            else:
                print(f"[FileManager] ✓ Write: {path} ({content_len} chars)")
            return True
        except Exception as e:
            print(f"[FileManager] ✗ Write failed: {path} - {str(e)}")
            return False

    def get_chapter_path(self, book, chapter_num: int) -> Optional[Path]:
        """获取章节文件路径"""
        chapter_file = f"chapter_{chapter_num}.md"
        chapter_path = self.workspace / book.path / "chapters" / chapter_file
        return chapter_path if chapter_path.exists() else None

    def ensure_dir(self, path: Path) -> bool:
        """确保目录存在"""
        try:
            path.mkdir(parents=True, exist_ok=True)
            return True
        except Exception:
            return False