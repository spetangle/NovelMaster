# -*- coding: utf-8 -*-
"""
NovelMaster API 测试脚本
用于验证重构后的 API 功能
"""

import os
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

BASE_URL = "http://localhost:13567"
API_BASE = f"{BASE_URL}/api"


def test_health():
    """测试健康检查"""
    print("\n[1] Testing /api/health...")
    r = requests.get(f"{API_BASE}/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    print(f"    PASS: {data}")


def test_llm_config():
    """测试 LLM 配置接口"""
    print("\n[2] Testing LLM config...")

    # 获取 LLM 状态
    r = requests.get(f"{API_BASE}/llm/status")
    assert r.status_code == 200
    data = r.json()
    print(f"    LLM Status: configured={data.get('configured')}")

    # 获取提供商模板
    r = requests.get(f"{API_BASE}/llm/templates")
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    providers = list(data.get("templates", {}).keys())
    print(f"    Providers: {providers}")

    return data


def test_books_crud():
    """测试书籍 CRUD 操作"""
    print("\n[3] Testing Books CRUD...")

    # 列出书籍
    r = requests.get(f"{API_BASE}/books")
    assert r.status_code == 200
    data = r.json()
    print(f"    List books: {len(data.get('books', []))} books found")

    return data.get("books", [])


def test_create_book_workflow():
    """测试创建书籍工作流"""
    print("\n[4] Testing Create Book Workflow...")

    brief = "书名：测试书籍\n题材：都市异能\n平台：番茄小说\n章节字数：3000"

    r = requests.post(f"{API_BASE}/books", json={"brief": brief})
    assert r.status_code == 200
    data = r.json()
    print(f"    Create result: success={data.get('success')}")

    if data.get("success"):
        book_id = data.get("book_id")
        print(f"    Book ID: {book_id}")

        # 获取书籍状态
        r = requests.get(f"{API_BASE}/books/{book_id}/status")
        if r.status_code == 200:
            print(f"    Book status retrieved")

        return book_id

    return None


def test_get_book_detail(book_id):
    """测试获取书籍详情"""
    if not book_id:
        print("\n[5] Skipping get book detail (no book_id)")
        return

    print(f"\n[5] Testing Get Book Detail: {book_id}...")

    r = requests.get(f"{API_BASE}/books/{book_id}")
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    book = data.get("book", {})
    print(f"    Book: {book.get('name')} ({book.get('genre')})")


def test_truth_files():
    """测试真相文件接口"""
    print("\n[6] Testing Truth Files...")

    r = requests.get(f"{API_BASE}/truth-files")
    print(f"    Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"    Success: {data.get('success')}")


def test_write_chapter(book_id):
    """测试章节创作"""
    if not book_id:
        print("\n[7] Skipping write chapter (no book_id)")
        return

    print(f"\n[7] Testing Write Chapter on {book_id}...")

    # 切换当前书籍
    r = requests.post(f"{API_BASE}/books/current", json={"book_id": book_id})
    print(f"    Switch book: {r.json().get('success')}")

    # 执行写作
    r = requests.post(f"{API_BASE}/write/execute", json={
        "book_id": book_id,
        "action": "continue",
        "chapter_num": 1,
        "auto_review": True,
        "auto_revise": False
    })

    if r.status_code == 200:
        data = r.json()
        task_id = data.get("task_id")
        print(f"    Write task created: {task_id}")

        # 轮询任务状态
        for i in range(30):
            r = requests.get(f"{API_BASE}/tasks/{task_id}")
            if r.status_code == 200:
                task = r.json().get("task", {})
                status = task.get("status")
                progress = task.get("progress")
                print(f"    Task status: {status} ({progress}%)")

                if status in ("success", "failed", "cancelled", "terminated"):
                    break
            time.sleep(2)

        return task_id

    return None


def test_tasks_api():
    """测试任务管理 API"""
    print("\n[8] Testing Tasks API...")

    r = requests.get(f"{API_BASE}/tasks")
    assert r.status_code == 200
    data = r.json()
    print(f"    Tasks list: {len(data.get('tasks', []))} tasks")

    r = requests.get(f"{API_BASE}/tasks/running")
    print(f"    Running tasks: {len(r.json().get('tasks', []))}")


def test_llm_test():
    """测试 LLM 连接测试"""
    print("\n[9] Testing LLM Connection...")

    r = requests.post(f"{API_BASE}/llm/test")
    print(f"    Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"    Success: {data.get('success')}, Configured: {data.get('configured')}")


def cleanup_test_book(book_id):
    """清理测试书籍"""
    if book_id:
        print(f"\n[Cleanup] Deleting test book: {book_id}...")
        r = requests.delete(f"{API_BASE}/books/{book_id}")
        print(f"    Delete result: {r.json()}")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("NovelMaster API Test Suite")
    print("=" * 60)

    # 先测试健康检查
    try:
        test_health()
    except Exception as e:
        print(f"    ERROR: Cannot connect to server: {e}")
        print("    Please start the server first: python app.py")
        return

    # 测试 LLM 配置
    test_llm_config()

    # 测试书籍列表
    test_books_crud()

    # 创建测试书籍
    test_book_id = None
    try:
        test_book_id = test_create_book_workflow()
    except Exception as e:
        print(f"    WARNING: Create book failed: {e}")

    # 获取书籍详情
    test_get_book_detail(test_book_id)

    # 测试真相文件
    test_truth_files()

    # 测试章节创作（如果 LLM 已配置）
    task_id = None
    try:
        task_id = test_write_chapter(test_book_id)
    except Exception as e:
        print(f"    WARNING: Write chapter failed: {e}")

    # 测试任务管理
    test_tasks_api()

    # 测试 LLM 连接
    test_llm_test()

    # 清理
    cleanup_test_book(test_book_id)

    print("\n" + "=" * 60)
    print("Test Suite Completed")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()