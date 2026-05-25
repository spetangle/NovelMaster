# -*- coding: utf-8 -*-
"""
NovelMaster CLI 入口
命令行接口
"""

import argparse
import sys
import re
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from core.state_manager import StateManager
from core.llm_service import LLMManager
from agents.engine import AgentEngine
from workflows.book_creation import BookCreationWorkflow
from workflows.chapter_writing import ChapterWritingWorkflow
from workflows.audit import AuditWorkflow


def setup_argparse() -> argparse.ArgumentParser:
    """设置命令行参数解析"""
    parser = argparse.ArgumentParser(
        description="NovelMaster - AI 小说创作引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # create 命令
    create_parser = subparsers.add_parser("create", help="创建新书")
    create_parser.add_argument("brief", help="创作简报", nargs="*")
    create_parser.add_argument("-m", "--mode", choices=["auto", "inspiration"],
                              default="auto", help="创建模式")

    # write 命令
    write_parser = subparsers.add_parser("write", help="创作章节")
    write_parser.add_argument("chapter", type=int, nargs="?", default=1, help="章节号")

    # status 命令
    subparsers.add_parser("status", help="查看状态")

    # audit 命令
    audit_parser = subparsers.add_parser("audit", help="审核章节")
    audit_parser.add_argument("chapter", type=int, nargs="?", default=1, help="章节号")
    audit_parser.add_argument("--golden", action="store_true", help="黄金三章审核")

    # list 命令
    subparsers.add_parser("list", help="列出所有书籍")

    # switch 命令
    switch_parser = subparsers.add_parser("switch", help="切换当前书籍")
    switch_parser.add_argument("book", help="书籍名称或ID")

    return parser


def cmd_create(args, sm: StateManager, engine: AgentEngine):
    """创建新书"""
    brief = " ".join(args.brief) if args.brief else ""

    if not brief:
        brief = input("请输入创作简报：\n")

    # 生成书籍ID
    import uuid
    book_id = f"book_{uuid.uuid4().hex[:8]}"

    # 执行工作流
    workflow = BookCreationWorkflow(sm, engine)
    result = workflow.execute(brief, book_id)

    if result.get("success"):
        print(f"\n✅ {result.get('message')}")
        print(f"书籍ID: {book_id}")
    else:
        print(f"\n❌ 创建失败: {result.get('message')}")
        sys.exit(1)


def cmd_write(args, sm: StateManager, engine: AgentEngine):
    """创作章节"""
    book = sm.get_current_book()
    if not book:
        print("❌ 请先创建或选择一本书")
        sys.exit(1)

    chapter_num = args.chapter

    workflow = ChapterWritingWorkflow(sm, engine)
    result = workflow.execute(book.id, chapter_num)

    if result.get("success"):
        print(f"\n✅ {result.get('message')}")
        print(f"评分: {result.get('score', 0)}")
        print(f"决策: {result.get('decision', '通过')}")
    else:
        print(f"\n❌ 创作失败: {result.get('message')}")
        sys.exit(1)


def cmd_status(args, sm: StateManager, engine: AgentEngine):
    """查看状态"""
    book = sm.get_current_book()

    if not book:
        print("📚 当前没有选中的书籍")
        books = sm.get_all_books()
        if books:
            print("\n可用书籍：")
            for b in books:
                print(f"  - {b.name} ({b.id})")
        return

    print(f"📖 当前书籍：{book.name}")
    print(f"   题材：{book.genre}")
    print(f"   平台：{book.platform}")
    print(f"   章节字数：{book.words_per_chapter}")
    print(f"   总章节数：{book.total_chapters}")

    # 列出已创作章节
    chapters_dir = sm.workspace / book.path / "chapters"
    if chapters_dir.exists():
        chapters = list(chapters_dir.glob("chapter_*.md"))
        print(f"   已创作：{len(chapters)} 章")


def cmd_audit(args, sm: StateManager, engine: AgentEngine):
    """审核章节"""
    book = sm.get_current_book()
    if not book:
        print("❌ 请先创建或选择一本书")
        sys.exit(1)

    workflow = AuditWorkflow(sm, engine)

    if args.golden:
        result = workflow.execute_golden_audit(book.id)
    else:
        result = workflow.execute_audit(book.id, args.chapter)

    if result.get("success"):
        print(f"\n✅ {result.get('message')}")
        print(f"评分: {result.get('score', 0)}")
        print(f"决策: {result.get('decision', '通过')}")
    else:
        print(f"\n❌ 审核失败: {result.get('message')}")


def cmd_list(args, sm: StateManager, engine: AgentEngine):
    """列出所有书籍"""
    books = sm.get_all_books()

    if not books:
        print("📚 还没有创建任何书籍")
        return

    print(f"📚 共 {len(books)} 本书籍：\n")
    for book in books:
        current = " ← 当前" if book.id == sm.book_index.get("current_novel") else ""
        print(f"  📖 {book.name}{current}")
        print(f"     ID: {book.id}")
        print(f"     题材: {book.genre}")
        print()


def cmd_switch(args, sm: StateManager, engine: AgentEngine):
    """切换书籍"""
    success, msg = sm.switch_book(args.book)

    if success:
        print(f"✅ {msg}")
    else:
        print(f"❌ {msg}")
        sys.exit(1)


def main():
    """主入口"""
    parser = setup_argparse()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 初始化组件
    workspace = Path(__file__).parent / "workspace"
    workspace.mkdir(exist_ok=True)

    sm = StateManager(str(workspace))
    llm = LLMManager()
    engine = AgentEngine(llm)

    # 执行命令
    commands = {
        "create": cmd_create,
        "write": cmd_write,
        "status": cmd_status,
        "audit": cmd_audit,
        "list": cmd_list,
        "switch": cmd_switch,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args, sm, engine)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()