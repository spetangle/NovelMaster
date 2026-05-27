# -*- coding: utf-8 -*-
"""
API路由定义 (FastAPI)
"""

import os
import threading
import re
from pathlib import Path
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Query
from pydantic import BaseModel

# 尝试导入核心模块
try:
    from core.novel_engine import NovelEngine
    from core.llm_service import LLMConfig, LLMError
    from core.models import BookInfo
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from core.novel_engine import NovelEngine
    from core.llm_service import LLMConfig, LLMError
    from core.models import BookInfo

# 导入任务管理器
try:
    from api.task_manager import task_manager, TaskStatus, StepStatus
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from task_manager import task_manager, TaskStatus, StepStatus

# 初始化引擎
workspace = os.getenv('WORKSPACE', './workspace')
engine = NovelEngine(workspace)

# 创建路由
router = APIRouter(tags=["API"])

# ============== 健康检查 ==============

@router.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "NovelMaster API"}


# ============== 书籍管理 ==============

@router.get("/books")
async def list_books():
    """列出所有书籍"""
    books = engine.list_books()
    return {"success": True, "books": books}


class CreateBookRequest(BaseModel):
    brief: str = ""
    inspiration_mode: bool = False  # 是否使用灵感对话模式


@router.post("/books")
async def create_book(data: CreateBookRequest):
    """创建新书 - 根据模式选择执行流程"""
    if not data.brief:
        raise HTTPException(status_code=400, detail="请提供创作简报")
    
    # 提取书名
    temp_name = ""
    name_match = re.search(r'书名[：:]\s*([^\n]+)', data.brief)
    if name_match:
        temp_name = name_match.group(1).strip()
    
    book_name = temp_name if temp_name else "新书"
    book_id = engine._generate_book_id()
    
    if data.inspiration_mode:
        # 灵感对话模式：创建书籍记录，进入对话流程
        task = task_manager.create_task(f"灵感创作 {book_name}", book_id=book_id, task_type="inspiration_chat")
        
        def run_inspiration():
            import time
            import threading
            print(f"[灵感线程 {threading.current_thread().name}] 开始执行，book_id={book_id}")
            try:
                task_manager.update_task(task.id, status=TaskStatus.RUNNING, progress=0, 
                    message="初始化灵感模式...", step="灵感对话")
                
                # 进度回调 - 更新任务进度
                def progress_callback(progress, message, step):
                    task_manager.update_task(task.id, status=TaskStatus.RUNNING,
                        progress=progress, message=message, step=step)
                
                # 初始化灵感书籍，传入进度回调
                print(f"[灵感线程] 调用 init_inspiration_book...")
                result = engine.init_inspiration_book(book_id, book_name, data.brief,
                    progress_callback=progress_callback)
                print(f"[灵感线程] init_inspiration_book 返回: {result}")
                
                # 保存完成后等待，确保数据已完全写入磁盘
                # 由于是异步操作，需要给文件写入足够的时间
                time.sleep(1.0)
                
                if result.get('success'):
                    task_manager.update_task(task.id, status=TaskStatus.SUCCESS,
                        progress=100, message="灵感书籍已创建", result=result)
                    print(f"[灵感线程] 书籍创建成功!")
                else:
                    task_manager.update_task(task.id, status=TaskStatus.FAILED,
                        message=f"创建失败: {result.get('message', '')}")
                    print(f"[灵感线程] 书籍创建失败: {result.get('message', '')}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[灵感线程] 异常: {str(e)}")
                task_manager.update_task(task.id, status=TaskStatus.FAILED, message=f"错误: {str(e)}")
        
        import threading
        t = threading.Thread(target=run_inspiration, daemon=True)
        t.start()
        print(f"[主线程] 灵感线程已启动: {t.name}")
        
        return {
            "success": True,
            "task_id": task.id,
            "book_id": book_id,
            "book_name": book_name,
            "mode": "inspiration",
            "message": "进入灵感对话模式..."
        }
    else:
        # 自动模式：执行带进度回调的工作流
        task = task_manager.create_task(f"创建新书 {book_name}", book_id=book_id, task_type="create_book")
        
        def run():
            try:
                task_manager.update_task(task.id, status=TaskStatus.RUNNING, progress=0, message="开始创建...")

                def progress_callback(step, progress, message):
                    task_manager.update_task(
                        task.id,
                        step=step,
                        progress=progress,
                        message=message
                    )

                def cancel_check():
                    """检查任务是否被终止"""
                    if task_manager.is_all_terminated():
                        return True
                    if task_manager.is_cancelled(task.id):
                        return True
                    return False

                result = engine.create_book_workflow_with_progress(
                    data.brief, book_id, progress_callback, cancel_check
                )

                if result.get('success'):
                    task_manager.update_task(task.id, status=TaskStatus.SUCCESS,
                        progress=100, message="创建完成", result=result)
                else:
                    task_manager.update_task(task.id, status=TaskStatus.FAILED,
                        message=f"创建失败: {result.get('message', '')}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                task_manager.update_task(task.id, status=TaskStatus.FAILED, message=f"错误: {str(e)}")

        import threading
        threading.Thread(target=run, daemon=True).start()
        
        return {
            "success": True,
            "task_id": task.id,
            "book_id": book_id,
            "book_name": book_name,
            "mode": "auto",
            "message": "书籍创建中..."
        }


# ============== 灵感对话模式 API ==============

class InspirationMessageRequest(BaseModel):
    message: str = ""


@router.get("/books/{book_id}/inspiration-status")
async def get_inspiration_status(book_id: str):
    """获取灵感模式状态 - 检查是否可以进入灵感模式"""
    result = engine.get_inspiration_status(book_id)
    return result


@router.post("/books/{book_id}/inspiration/enter")
async def enter_inspiration(book_id: str):
    """重新进入灵感对话模式"""
    result = engine.enter_inspiration_mode(book_id)
    return result


@router.post("/books/{book_id}/inspiration/exit")
async def exit_inspiration(book_id: str):
    """退出灵感对话模式"""
    result = engine.exit_inspiration_mode(book_id)
    return result


@router.get("/books/{book_id}/inspiration")
async def get_inspiration_info(book_id: str):
    """获取灵感书籍的详细信息"""
    result = engine.get_inspiration_info(book_id)
    return result


@router.post("/books/{book_id}/inspiration/chat")
async def chat_inspiration(book_id: str, request: Request):
    """发送灵感对话消息"""
    try:
        data = await request.json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            raise HTTPException(status_code=400, detail="消息不能为空")
        
        result = engine.chat_inspiration(book_id, user_message)
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/books/{book_id}/inspiration/auto-complete")
async def auto_complete_inspiration(book_id: str):
    """自动补全灵感信息"""
    result = engine.auto_complete_inspiration(book_id)
    return result


@router.get("/books/{book_id}/inspiration/status")
async def get_inspiration_status(book_id: str):
    """获取灵感收集情况"""
    # 从 book_index 获取灵感数据
    with engine.sm._lock:
        book_dict = None
        for b in engine.sm.book_index.get("books", []):
            if b.get("id") == book_id:
                book_dict = b
                break

    if not book_dict:
        raise HTTPException(status_code=404, detail="书籍不存在")

    collected_info = book_dict.get("inspiration_collected_info", {})

    # 定义字段
    field_defs = [
        {"key": "book_name", "name": "书名", "required": True},
        {"key": "genre", "name": "题材", "required": True},
        {"key": "platform", "name": "平台", "required": True},
        {"key": "words_per_chapter", "name": "章节字数", "required": False},
        {"key": "total_chapters", "name": "总章节数", "required": False},
        {"key": "background", "name": "背景设定", "required": True},
        {"key": "protagonist", "name": "主角信息", "required": True},
        {"key": "main_conflict", "name": "核心冲突", "required": True},
        {"key": "power_system", "name": "力量体系", "required": False},
        {"key": "factions", "name": "势力设定", "required": False},
        {"key": "locations", "name": "地理环境", "required": False},
        {"key": "tone_style", "name": "文风基调", "required": False}
    ]

    # 统计
    filled_fields = []
    missing_fields = []
    required_filled = 0
    required_total = 0

    for f in field_defs:
        value = collected_info.get(f["key"], "")
        is_filled = bool(value and str(value).strip())
        field_info = {"key": f["key"], "name": f["name"], "value": value or "", "filled": is_filled}

        if is_filled:
            filled_fields.append(field_info)
            if f["required"]:
                required_filled += 1
        else:
            missing_fields.append(field_info)
            if f["required"]:
                required_total += 1

    return {
        "success": True,
        "collected_info": collected_info,
        "filled_fields": filled_fields,
        "missing_fields": missing_fields,
        "field_defs": field_defs,
        "stats": {
            "total": len(field_defs),
            "filled": len(filled_fields),
            "missing": len(missing_fields),
            "required_filled": required_filled,
            "required_total": required_total,
            "completion_rate": round(len(filled_fields) / len(field_defs) * 100),
            "required_rate": round(required_filled / required_total * 100) if required_total > 0 else 100,
            "can_generate": required_filled >= required_total
        }
    }


@router.post("/books/{book_id}/inspiration/save-report")
async def save_inspiration_report(book_id: str):
    """保存灵感收集情况报告到文件"""
    # 从 book_index 获取灵感数据
    with engine.sm._lock:
        book_dict = None
        for b in engine.sm.book_index.get("books", []):
            if b.get("id") == book_id:
                book_dict = b
                break

    if not book_dict:
        raise HTTPException(status_code=404, detail="书籍不存在")

    collected_info = book_dict.get("inspiration_collected_info", {})

    # 定义字段
    field_defs = [
        {"key": "book_name", "name": "书名", "required": True},
        {"key": "genre", "name": "题材", "required": True},
        {"key": "platform", "name": "平台", "required": True},
        {"key": "words_per_chapter", "name": "章节字数", "required": False},
        {"key": "total_chapters", "name": "总章节数", "required": False},
        {"key": "background", "name": "背景设定", "required": True},
        {"key": "protagonist", "name": "主角信息", "required": True},
        {"key": "main_conflict", "name": "核心冲突", "required": True},
        {"key": "power_system", "name": "力量体系", "required": False},
        {"key": "factions", "name": "势力设定", "required": False},
        {"key": "locations", "name": "地理环境", "required": False},
        {"key": "tone_style", "name": "文风基调", "required": False}
    ]

    # 生成报告内容
    lines = ["# 灵感收集情况报告\n"]
    lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 已填写内容
    lines.append("## 已填写内容\n")
    filled_count = 0
    book_name_fallback = book_dict.get("name", "")
    for f in field_defs:
        value = collected_info.get(f["key"], "")
        # 书名兜底：如果collected_info里没有书名，但book_dict有有效书名（不是纯数字ID），使用它
        if f["key"] == "book_name" and (not value or not str(value).strip()):
            if book_name_fallback and book_name_fallback != book_id:
                value = book_name_fallback
        if value and str(value).strip():
            filled_count += 1
            lines.append(f"### {f['name']}\n")
            lines.append(f"{value}\n")

    # 缺失内容
    lines.append("\n## 缺失内容\n")
    missing_count = 0
    for f in field_defs:
        value = collected_info.get(f["key"], "")
        # 同样应用书名兜底逻辑
        if f["key"] == "book_name" and (not value or not str(value).strip()):
            if book_name_fallback and book_name_fallback != book_id:
                value = book_name_fallback
        if not value or not str(value).strip():
            missing_count += 1
            marker = "⭐" if f["required"] else ""
            lines.append(f"- {f['name']} {marker}\n")

    # 统计
    lines.append("\n## 统计信息\n")
    lines.append(f"- 总字段数：{len(field_defs)}")
    lines.append(f"- 已填写：{filled_count} ({round(filled_count/len(field_defs)*100)}%)")
    lines.append(f"- 缺失：{missing_count}")
    lines.append(f"- 必填项：{len([f for f in field_defs if f['required']])}")
    lines.append(f"- 可生成文档：{'是' if filled_count >= len([f for f in field_defs if f['required']]) else '否'}")

    report_content = "\n".join(lines)

    # 保存到书籍目录
    book = engine.sm.get_book_by_id(book_id)
    book_path = engine.workspace / book.path
    report_file = book_path / "inspiration_report.md"

    try:
        report_file.write_text(report_content, encoding='utf-8')
        return {
            "success": True,
            "file_path": str(report_file),
            "content": report_content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存报告失败: {str(e)}")


@router.delete("/books/{book_id}/inspiration/report")
async def delete_inspiration_report(book_id: str):
    """删除灵感收集报告文件"""
    book = engine.sm.get_book_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    book_path = engine.workspace / book.path
    report_file = book_path / "inspiration_report.md"

    if report_file.exists():
        try:
            report_file.unlink()
            return {"success": True, "message": "报告已删除"}
        except Exception as e:
            return {"success": False, "message": f"删除失败: {str(e)}"}
    return {"success": True, "message": "文件不存在，无需删除"}


@router.post("/books/{book_id}/inspiration/generate-docs")
async def generate_inspiration_docs(book_id: str):
    """生成设定文档（灵感模式完成后）"""
    book = engine.sm.get_book_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    # 创建任务
    task = task_manager.create_task(f"生成设定文档 {book.name}", book_id=book_id, task_type="inspiration_generate")
    
    def run():
        try:
            task_manager.update_task(task.id, status=TaskStatus.RUNNING, progress=0, message="开始生成...")
            
            collected = getattr(book, 'inspiration_collected_info', {})
            
            # 构建规划数据
            planning = {
                'genre': collected.get('genre', '都市'),
                'platform': collected.get('platform', '番茄小说'),
                'words_per_chapter': collected.get('words_per_chapter', 3000),
                'estimated_chapters': collected.get('total_chapters', 80),
            }
            
            # 使用带进度回调的工作流，传入取消检查函数
            def progress_callback(step, progress, message):
                task_manager.update_task(task.id, step=step, progress=progress, message=message)
            
            def cancel_check():
                return task_manager.is_cancelled(task.id)
            
            # 执行创建流程
            result = engine.create_book_workflow_with_progress(
                f"书名：{collected.get('book_name', book.name)}\n" +
                f"题材：{planning['genre']}\n" +
                f"平台：{planning['platform']}\n" +
                f"章节字数：{planning['words_per_chapter']}\n" +
                f"总章节数：{planning['estimated_chapters']}\n" +
                f"背景设定：{collected.get('background', '')}\n" +
                f"主角信息：{collected.get('protagonist', '')}",
                book_id,
                progress_callback,
                cancel_check
            )
            
            # 检查是否被取消
            if task_manager.is_cancelled(task.id) or result.get('cancelled'):
                task_manager.update_task(task.id, status=TaskStatus.TERMINATED, message="任务已终止")
                return
            
            if result.get('success'):
                # 标记书籍不再是灵感模式
                book.is_inspiration = False
                engine.save_book_meta(book)
                
                task_manager.update_task(task.id, status=TaskStatus.SUCCESS,
                    progress=100, message="生成完成", result=result)
            else:
                task_manager.update_task(task.id, status=TaskStatus.FAILED,
                    message=f"生成失败: {result.get('message', '')}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            task_manager.update_task(task.id, status=TaskStatus.FAILED, message=f"错误: {str(e)}")
    
    import threading
    threading.Thread(target=run, daemon=True).start()
    
    return {
        "success": True,
        "task_id": task.id,
        "message": "正在生成设定文档..."
    }


class ConfirmPlanningRequest(BaseModel):
    """保留此接口用于可选的确认模式（暂未使用）"""
    class Config:
        arbitrary_types_allowed = True

    brief: str = ""
    planning: dict = {}
    confirmed: bool = True


@router.post("/books/confirm-planning")
async def confirm_planning(data: ConfirmPlanningRequest):
    """
    确认创作规划书并创建书籍（可选模式）
    """
    if not data.confirmed:
        return {
            "success": False,
            "message": "用户取消创建",
            "phase": "cancelled"
        }

    # 使用一站式创建流程
    result = engine.create_book_workflow(data.brief)
    return result


@router.delete("/books/{book_id}")
async def delete_book(book_id: str):
    """删除书籍"""
    result = engine.delete_book(book_id)
    if result.get('success'):
        return {"success": True, "message": f"书籍已删除"}
    else:
        raise HTTPException(status_code=400, detail=result.get('message', '删除失败'))


class RenameBookRequest(BaseModel):
    new_name: str


@router.put("/books/{book_id}/rename")
async def rename_book(book_id: str, data: RenameBookRequest):
    """重命名书籍"""
    if not data.new_name:
        raise HTTPException(status_code=400, detail="请提供新书名")
    
    result = engine.rename_book(book_id, data.new_name)
    if result.get('success'):
        return {"success": True, "message": result.get('message', '书籍已重命名'), "new_name": result.get('new_name')}
    else:
        raise HTTPException(status_code=400, detail=result.get('message', '重命名失败'))


@router.get("/books/current")
async def get_current_book():
    """获取当前书籍"""
    result = engine.get_book_status()
    return result


class SwitchBookRequest(BaseModel):
    book_id: str = ""


@router.post("/books/current")
async def switch_book(data: SwitchBookRequest):
    """切换当前书籍"""
    if not data.book_id:
        raise HTTPException(status_code=400, detail="请提供书籍ID")
    
    result = engine.switch_book(data.book_id)
    return result


@router.get("/books/{book_id}/status")
async def get_book_status(book_id: str):
    """获取书籍状态"""
    result = engine.get_book_status(book_id)
    return result


# ============== 书籍设定 ==============

@router.get("/books/{book_id}/settings")
async def get_book_settings(book_id: str):
    """获取书籍自定义设定"""
    result = engine.get_book_settings(book_id)
    return result


@router.get("/books/current/settings")
async def get_current_book_settings():
    """获取当前书籍自定义设定"""
    result = engine.get_book_settings()
    return result


class UpdateSettingsRequest(BaseModel):
    class Config:
        arbitrary_types_allowed = True


@router.put("/books/current/settings")
async def update_current_book_settings(data: dict = None):
    """更新当前书籍自定义设定"""
    result = engine.update_book_settings(**(data or {}))
    return result


# ============== 全局配置 ==============

@router.get("/global/config")
async def get_global_config():
    """获取全局配置"""
    result = engine.get_global_config()
    return result


class UpdateConfigRequest(BaseModel):
    class Config:
        arbitrary_types_allowed = True


@router.put("/global/config")
async def update_global_config(data: dict = None):
    """更新全局配置"""
    result = engine.update_global_config(**(data or {}))
    return result


# ============== 章节创作 ==============

class WriteChapterRequest(BaseModel):
    chapter_num: int = 1
    revise: bool = False       # 修订模式：基于上一次细纲和评审报告修改
    regenerate: bool = False    # 重写模式：从细纲开始重新生成


@router.post("/chapters/write")
async def write_chapter(data: WriteChapterRequest):
    """创作章节"""
    chapter_num = data.chapter_num

    if not isinstance(chapter_num, int) or chapter_num < 1:
        raise HTTPException(status_code=400, detail="章节号必须为正整数")
    
    # 序章功能已移除，章节号必须从1开始
    if chapter_num == 0:
        raise HTTPException(status_code=400, detail="序章功能已移除，章节号必须从1开始")

    result = engine.write_chapter(chapter_num, revise=data.revise, regenerate=data.regenerate)
    return result


@router.get("/chapters/locks")
async def get_chapter_locks(request: Request):
    """获取章节锁状态"""
    try:
        book_id = request.query_params.get("book_id", "")
        
        if not book_id or book_id in ("undefined", "null"):
            return {"success": True, "locked_chapters": []}
        
        locked_chapters = task_manager.get_locked_chapters(book_id)
        return {"success": True, "locked_chapters": locked_chapters}
    except Exception as e:
        return {"success": True, "locked_chapters": []}


@router.get("/chapters/{chapter_num_or_id}")
async def get_chapter(chapter_num_or_id: str):
    """获取章节内容（支持 chapter_X 格式或纯数字）"""
    # 支持纯数字章节号
    if chapter_num_or_id.isdigit():
        chapter_num = int(chapter_num_or_id)
    else:
        # 从 chapter_X 格式解析章节号
        try:
            chapter_num = int(chapter_num_or_id.split('_')[-1])
        except:
            raise HTTPException(status_code=400, detail="无效的章节格式")
    
    result = engine.get_chapter_content(None, chapter_num)
    return result


@router.get("/chapters/{chapter_num}/outline")
async def get_chapter_outline(chapter_num: int):
    """获取章节细纲"""
    book = engine.sm.get_current_book()
    if not book:
        raise HTTPException(status_code=400, detail="请先选择书籍")
    
    outline = engine._generate_chapter_outline(book, chapter_num)
    return {"success": True, "chapter_num": chapter_num, "outline": outline}


# ============== 真相文件 ==============

@router.get("/truth-files")
async def get_truth_files():
    """获取真相文件"""
    result = engine.get_truth_files()
    return result


class UpdateTruthFileRequest(BaseModel):
    content: str = ""


@router.put("/truth-files/{filename}")
async def update_truth_file(filename: str, data: UpdateTruthFileRequest):
    """更新真相文件"""
    result = engine.update_truth_file(None, filename, data.content)
    return result


@router.post("/truth-files/regenerate")
async def regenerate_truth_files():
    """重新生成所有真相文件"""
    result = engine.regenerate_truth_files()
    return result


@router.get("/story-bible")
async def get_story_bible():
    """获取世界观设定"""
    truth_files = engine.get_truth_files()
    if truth_files.get('success'):
        return {
            "success": True,
            "content": truth_files.get('files', {}).get('story_bible', '')
        }
    return truth_files


@router.get("/book-rules")
async def get_book_rules():
    """获取创作规则"""
    truth_files = engine.get_truth_files()
    if truth_files.get('success'):
        return {
            "success": True,
            "content": truth_files.get('files', {}).get('book_rules', '')
        }
    return truth_files


# ============== 作者意图与当前焦点 ==============

@router.get("/author-intent")
async def get_author_intent():
    """获取作者意图文档"""
    result = engine.get_author_intent()
    return result


@router.get("/current-focus")
async def get_current_focus():
    """获取当前焦点文档"""
    result = engine.get_current_focus()
    return result


class UpdateAuthorIntentRequest(BaseModel):
    content: str = ""


@router.put("/author-intent")
async def update_author_intent(data: UpdateAuthorIntentRequest):
    """更新作者意图文档"""
    result = engine.update_author_intent(content=data.content if data.content else None)
    return result


class UpdateCurrentFocusRequest(BaseModel):
    content: str = ""


@router.put("/current-focus")
async def update_current_focus(data: UpdateCurrentFocusRequest):
    """更新当前焦点文档"""
    result = engine.update_current_focus(content=data.content if data.content else None)
    return result


# ============== LLM配置 ==============

@router.get("/llm/config")
async def get_llm_config():
    """获取LLM配置"""
    result = engine.get_llm_config()
    return result


class UpdateLLMConfigRequest(BaseModel):
    class Config:
        arbitrary_types_allowed = True


@router.put("/llm/config")
async def update_llm_config(data: dict = None):
    """更新LLM配置"""
    result = engine.update_llm_config(**(data or {}))
    return result


@router.get("/llm/providers")
async def get_providers():
    """获取所有提供商"""
    result = engine.get_llm_config()
    return result


@router.delete("/llm/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """删除提供商"""
    result = engine.update_llm_config(delete_provider=provider_id)
    return result


@router.post("/llm/providers/{provider_id}/activate")
async def activate_provider(provider_id: str):
    """激活提供商"""
    result = engine.update_llm_config(set_active=provider_id)
    return result


class TestLLMRequest(BaseModel):
    provider_id: Optional[str] = None


@router.post("/llm/test")
async def test_llm(data: TestLLMRequest = None):
    """测试LLM连接"""
    result = engine.test_llm_connection(data.provider_id if data else None)
    return result


@router.get("/llm/status")
async def get_llm_status():
    """获取LLM配置状态"""
    config = engine.llm.config
    return {
        "success": True,
        "configured": config.is_configured(),
        "active_provider": config.get_active_provider().to_dict() if config.get_active_provider() else None,
        "provider_count": len(config.providers)
    }


@router.get("/llm/templates")
async def get_llm_templates():
    """获取提供商模板"""
    return {
        "success": True,
        "templates": LLMConfig.PROVIDER_TEMPLATES
    }


@router.get("/llm/logs")
async def get_llm_logs():
    """获取LLM日志列表"""
    log_dir = engine.workspace / "logs"
    if not log_dir.exists():
        return {"success": True, "logs": []}
    
    logs = []
    for f in sorted(log_dir.glob("*.log"), reverse=True)[:10]:
        logs.append({
            "name": f.name,
            "size": f.stat().st_size,
            "date": f.stat().st_mtime
        })
    return {"success": True, "logs": logs}


@router.get("/llm/logs/{filename}")
async def get_llm_log(filename: str):
    """获取指定日志内容"""
    log_file = engine.workspace / "logs" / filename
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="日志文件不存在")
    
    try:
        content = log_file.read_text(encoding='utf-8')
        return {"success": True, "content": content, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== 批量操作 ==============

class BatchWriteRequest(BaseModel):
    start_chapter: int = 1
    end_chapter: int = 5


@router.post("/chapters/batch-write")
async def batch_write_chapters(data: BatchWriteRequest):
    """批量创作章节"""
    start_chapter = data.start_chapter
    end_chapter = data.end_chapter

    if start_chapter < 1 or end_chapter < start_chapter:
        raise HTTPException(status_code=400, detail="参数错误")

    results = []
    for i in range(start_chapter, end_chapter + 1):
        # 每个章节最多重试3次
        max_retries = 3
        llm_retry_count = 0
        last_error = ""
        chapter_success = False

        while llm_retry_count < max_retries:
            try:
                result = engine.write_chapter(i)
                results.append({
                    "chapter_num": i,
                    "success": result.get('success', False),
                    "message": result.get('message', ''),
                    "score": result.get('audit_result', {}).get('chapter_score', 0)
                })
                chapter_success = result.get('success', False)
                break  # 成功，跳出重试循环
            except LLMError as e:
                llm_retry_count += 1
                last_error = str(e)
                if llm_retry_count < max_retries:
                    import time
                    retry_msg = f"第{i}章 LLM错误（第{llm_retry_count}/{max_retries}次），等待30秒后自动重试..."
                    print(f"[batch_write] {retry_msg}")
                    time.sleep(30)
                else:
                    results.append({
                        "chapter_num": i,
                        "success": False,
                        "message": f"LLM错误已达最大重试次数: {e}",
                        "score": 0
                    })
        if not chapter_success and llm_retry_count >= max_retries:
            break  # 章节失败后停止批量创作

    return {
        "success": True,
        "results": results,
        "summary": {
            "total": len(results),
            "passed": len([r for r in results if r['success']]),
            "failed": len([r for r in results if not r['success']])
        }
    }


# ============== 新UI专用API ==============

@router.get("/books/{book_id}")
async def get_book_detail(book_id: str):
    """获取书籍详情（包含文档状态和主角信息）"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 检查各文档是否存在
    book_path = engine.workspace / book.path
    docs_status = {
        'planning_exists': (book_path / "planning.md").exists(),
        'story_bible_exists': (book_path / "story_bible.md").exists(),
        'book_rules_exists': (book_path / "book_rules.md").exists(),
        'chapter_outline_exists': (book_path / "chapter_outline.md").exists(),
        'author_intent_exists': (book_path / "author_intent.md").exists(),
        'current_focus_exists': (book_path / "current_focus.md").exists(),
        'characters_exists': (book_path / "characters.md").exists()
    }

    # 读取主角信息
    protagonist_info = ""
    characters_path = book_path / "characters.md"
    if characters_path.exists():
        content = characters_path.read_text(encoding='utf-8')
        import re
        # 提取主角名和性别
        name_match = re.search(r'## 主角[：:]?\s*(\S+)', content)
        gender_match = re.search(r'性别[：:]?\s*(\S+)', content)
        name = name_match.group(1) if name_match else ""
        gender = gender_match.group(1) if gender_match else ""
        if name:
            protagonist_info = f"{name} {gender}" if gender else name

    book_data = book.to_dict() if hasattr(book, 'to_dict') else book
    return {
        "success": True,
        "book": {**book_data, **docs_status, "protagonist_info": protagonist_info}
    }


@router.get("/books/{book_id}/docs/{doc_key}")
async def get_book_doc(book_id: str, doc_key: str):
    """获取书籍文档内容"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    doc_files = {
        'planning': 'planning.md',
        'story_bible': 'story_bible.md',
        'book_rules': 'book_rules.md',
        'chapter_outline': 'chapter_outline.md',
        'author_intent': 'author_intent.md',
        'current_focus': 'current_focus.md'
    }

    doc_file = doc_files.get(doc_key)
    if not doc_file:
        raise HTTPException(status_code=400, detail="未知文档类型")

    doc_path = engine.workspace / book.path / doc_file
    if not doc_path.exists():
        return {"success": True, "content": "", "message": "文档不存在"}

    try:
        content = doc_path.read_text(encoding='utf-8')
        return {"success": True, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/books/{book_id}/chapters")
async def get_book_chapters(book_id: str):
    """获取书籍章节列表"""
    chapters = engine.get_chapters(book_id)
    return {"success": True, "chapters": chapters or []}


@router.get("/chapters/{chapter_id}")
async def get_chapter_by_id(chapter_id: str):
    """通过ID获取章节（支持 chapter_1 格式或纯数字）"""
    # 支持纯数字章节号
    if chapter_id.isdigit():
        chapter = engine.get_chapter_by_number(int(chapter_id))
    else:
        chapter = engine.get_chapter_by_id(chapter_id)
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"success": True, "chapter": chapter}


class StartWorkflowRequest(BaseModel):
    book_id: str = ""
    brief: str = ""


def _run_workflow_task(task_id: str, book_id: str, brief: str):
    """后台执行工作流（分步进度）"""
    def progress_callback(step: str, progress: int, message: str):
        task_manager.update_task(task_id, status=TaskStatus.RUNNING, 
                                progress=progress, message=message, step=step)
    
    try:
        task_manager.update_task(task_id, status=TaskStatus.RUNNING, progress=5,
                                message="正在启动创作流程...", step="启动")
        result = engine.create_book_workflow_with_progress(brief, book_id, progress_callback)
        
        if result.get('success'):
            task_manager.update_task(task_id, progress=100, message="创建完成", 
                                    result=result, status=TaskStatus.SUCCESS)
        else:
            task_manager.update_task(task_id, status=TaskStatus.FAILED, 
                                    message="工作流失败", error=result.get('message'))
    except Exception as e:
        import traceback
        traceback.print_exc()
        task_manager.update_task(task_id, status=TaskStatus.FAILED, 
                                message="执行出错", error=str(e))


@router.post("/books/workflow/start")
async def start_book_workflow(data: StartWorkflowRequest):
    """启动新书创建工作流"""
    if not data.book_id:
        raise HTTPException(status_code=400, detail="缺少书籍ID")
    
    # 创建异步任务
    task = task_manager.create_task(f"创建新书 {data.book_id}")
    
    # 启动后台执行
    import threading
    thread = threading.Thread(target=_run_workflow_task, args=(task.id, data.book_id, data.brief), daemon=True)
    thread.start()
    
    return {"success": True, "task_id": task.id, "message": "工作流已启动"}


class ExecuteWriteRequest(BaseModel):
    book_id: str = ""
    action: str = "continue"
    chapter_id: Optional[str] = None
    chapter_num: Optional[int] = None
    auto_review: bool = True  # 创作完成后自动评审
    auto_revise: bool = True  # 评审不通过时自动修订
    max_retry: int = 3  # 最大修订次数


@router.post("/write/execute")
async def execute_write(data: ExecuteWriteRequest, background_tasks: BackgroundTasks):
    """执行撰写操作"""
    if not data.book_id:
        raise HTTPException(status_code=400, detail="缺少书籍ID")

    # 设置当前书籍
    book = engine.sm.get_book_by_id(data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    engine.sm.switch_book(book.name)

    # 获取当前章节信息
    chapters = engine.get_chapters(data.book_id)
    current_chapter = max([c['number'] for c in chapters], default=0)

    # 优先使用用户指定的章节号（支持0代表序章）
    if data.chapter_num is not None:
        chapter_num = data.chapter_num
    elif data.chapter_id:
        # 从 chapter_id 解析章节号（格式: chapter_X）
        try:
            chapter_num = int(data.chapter_id.split('_')[-1])
        except:
            chapter_num = current_chapter if current_chapter > 0 else 1
    else:
        # 默认逻辑
        if data.action == "continue":
            chapter_num = current_chapter + 1
        elif data.action == "review":
            chapter_num = current_chapter if current_chapter > 0 else 1
        elif data.action in ("revise", "regenerate"):
            chapter_num = current_chapter if current_chapter > 0 else 1
        else:
            chapter_num = current_chapter if current_chapter > 0 else 1

    # 根据操作决定动作名称
    if data.action == "continue":
        action_name = "续写"
    elif data.action == "review":
        action_name = "评审"
    elif data.action == "revise":
        action_name = "修订"
    elif data.action == "regenerate":
        action_name = "重写"
    else:
        action_name = data.action
    
    # 检查章节是否已被锁定
    is_locked, locked_task_id = task_manager.is_chapter_locked(data.book_id, chapter_num)
    if is_locked:
        locked_task = task_manager.get_task(locked_task_id)
        task_name = locked_task.name if locked_task else "未知任务"
        raise HTTPException(
            status_code=409, 
            detail=f"第{chapter_num}章正在被 [{task_name}] 操作，请稍后再试"
        )
    
    # 创建后台任务
    task = task_manager.create_task(f"{action_name}第{chapter_num}章", book_id=data.book_id, task_type="write_chapter")

    # 初始化任务步骤
    task_manager.init_task_steps(task.id, [
        "生成细纲",      # 步骤0
        "编译上下文",    # 步骤1
        "生成正文",      # 步骤2
        "调整字数",      # 步骤3（字数偏差>15%时执行，否则跳过）
        "质量评审"       # 步骤4
    ])

    # 锁定章节
    task_manager.lock_chapter(data.book_id, chapter_num, task.id)
    
    def run():
        try:
            chapter_title = f"第{chapter_num}章"

            # 检查是否已取消
            if task_manager.is_cancelled(task.id):
                task_manager.update_task(task.id, status=TaskStatus.TERMINATED, message="任务已取消")
                task_manager.unlock_chapter(data.book_id, chapter_num)
                return

            if data.action == "continue":
                task_manager.update_task(task.id, status=TaskStatus.RUNNING, progress=5,
                                        message=f"正在准备生成{chapter_title}...", step="准备生成")

                # 检查是否已取消
                if task_manager.is_cancelled(task.id):
                    task_manager.update_task(task.id, status=TaskStatus.TERMINATED, message="任务已取消")
                    task_manager.unlock_chapter(data.book_id, chapter_num)
                    return

                # 检查是否需要生成细纲
                task_manager.update_task(task.id, progress=15,
                                        message=f"正在生成{chapter_title}细纲...", step="生成细纲")

                # LLM错误重试机制（最多3次，每次等待30秒）
                max_llm_retries = 3
                llm_retry_count = 0
                last_llm_error = ""

                while llm_retry_count < max_llm_retries:
                    # 检查全局终止事件
                    if task_manager.is_all_terminated():
                        task_manager.update_task(task.id, status=TaskStatus.TERMINATED, message="任务已被终止")
                        task_manager.unlock_chapter(data.book_id, chapter_num)
                        return
                    try:
                        result = engine.write_chapter(chapter_num, task_id=task.id)
                        break  # 成功，跳出重试循环
                    except LLMError as e:
                        llm_retry_count += 1
                        last_llm_error = str(e)
                        if llm_retry_count < max_llm_retries:
                            # 未达到最大重试次数，等待30秒后重试
                            retry_msg = f"LLM错误（第{llm_retry_count}/{max_llm_retries}次），等待30秒后自动重试... ({e})"
                            print(f"[{task.id}] {retry_msg}")
                            task_manager.update_task(task.id, progress=5,
                                message=retry_msg, step="LLM重试")
                            task_manager.mark_retry_pending(task.id, str(e))
                            import time
                            time.sleep(30)
                            # 重置任务状态继续执行
                            task_manager.retry_task(task.id)
                            task_manager.update_task(task.id, status=TaskStatus.RUNNING, progress=15,
                                message=f"正在重试生成{chapter_title}（第{llm_retry_count+1}次）...", step="重试")
                        else:
                            # 达到最大重试次数，终止任务
                            error_msg = f"LLM错误已达最大重试次数（{max_llm_retries}次），任务终止: {e}"
                            print(f"[{task.id}] ✗ {error_msg}")
                            task_manager.update_task(task.id, status=TaskStatus.FAILED,
                                message=error_msg, error=str(e), step="LLM重试失败")
                            task_manager.unlock_chapter(data.book_id, chapter_num)
                            return

                # 检查是否需要异步调整字数
                if result.get('pending_adjust'):
                    task_manager.update_task(task.id, progress=70,
                                            message=f"正在调整{chapter_title}字数...", step="调整字数")

                    # 启动后台调整任务（不等待，避免卡死）
                    adjust_task = task_manager.create_task(
                        f"调整第{chapter_num}章字数",
                        book_id=data.book_id,
                        task_type="word_adjust"
                    )
                    # 初始化字数调整步骤
                    task_manager.init_task_steps(adjust_task.id, ["调整字数"])
                    engine.adjust_chapter_word_count_async(book.id, chapter_num, adjust_task.id)

                    # 不再等待，前端通过轮询 adjust_task 状态获知进度
                    # 原：while 循环等待 -> 已移除，避免卡死进程

                    task_manager.update_task(task.id, progress=75,
                                            message=f"{chapter_title}字数调整已启动，请在任务列表查看进度...", step="等待字数调整")

                # 创作完成后自动评审
                chapter_info = engine.get_chapter_content(data.book_id, chapter_num)
                content = chapter_info.get('chapter', {}).get('content', '') if chapter_info.get('success') else ''
                truth_files = engine._load_truth_files(book)

                retry_count = 0
                final_audit_result = None
                revision_history = []

                if data.auto_review and result.get('success'):
                    # 自动修订循环
                    while True:
                        # 检查是否已取消
                        if task_manager.is_cancelled(task.id):
                            task_manager.update_task(task.id, status=TaskStatus.TERMINATED, message="任务已取消")
                            task_manager.unlock_chapter(data.book_id, chapter_num)
                            return

                        retry_count += 1
                        task_manager.update_task(task.id, progress=75,
                                                message=f"正在评审{chapter_title}（第{retry_count}次）...", step=f"评审({retry_count})")

                        audit_result = engine._audit_chapter(book, chapter_num, content, truth_files)
                        final_audit_result = audit_result.to_dict()
                        score = audit_result.chapter_score

                        # 记录评审历史
                        revision_history.append({
                            "attempt": retry_count,
                            "score": score,
                            "passed": score >= 75
                        })

                        # 保存评审结果到章节状态
                        engine.sm.update_chapter_status(
                            book, chapter_num,
                            status='draft',
                            audit_score=score,
                            audit_passed=score >= 75,
                            retry_count=retry_count
                        )

                        # 评分达标，结束循环
                        if score >= 75:
                            result['audit_result'] = final_audit_result
                            result['revision_history'] = revision_history
                            result['final_score'] = score
                            result['passed'] = True
                            # 生成章节简报
                            chapter_brief = engine.generate_chapter_brief(book, chapter_num)
                            result['chapter_brief'] = chapter_brief

                            break

                        # 评分不达标，检查是否需要修订
                        if not data.auto_revise or retry_count >= data.max_retry:
                            # 不自动修订或已达最大次数
                            result['audit_result'] = final_audit_result
                            result['revision_history'] = revision_history
                            result['final_score'] = score
                            result['passed'] = False
                            result['suggest_revise'] = True
                            result['suggest_message'] = f"评分较低({score}分)，已修订{retry_count - 1}次"
                            break

                        # 需要自动修订
                        task_manager.update_task(task.id, progress=80,
                                                message=f"评分较低({score}分)，正在修订{chapter_title}...", step=f"修订({retry_count})")

                        # 修订前检查是否已取消
                        if task_manager.is_cancelled(task.id):
                            task_manager.update_task(task.id, status=TaskStatus.TERMINATED, message="任务已取消")
                            task_manager.unlock_chapter(data.book_id, chapter_num)
                            return

                        # 修订章节
                        revise_result = engine.write_chapter(chapter_num, revise=True)
                        if not revise_result.get('success'):
                            result['audit_result'] = final_audit_result
                            result['revision_history'] = revision_history
                            result['final_score'] = score
                            result['passed'] = False
                            result['suggest_revise'] = True
                            result['suggest_message'] = f"修订失败，当前评分{score}分"
                            break

                        # 获取修订后的内容
                        chapter_info = engine.get_chapter_content(data.book_id, chapter_num)
                        content = chapter_info.get('chapter', {}).get('content', '') if chapter_info.get('success') else ''

                task_manager.update_task(task.id, progress=85,
                                        message=f"正在保存{chapter_title}内容...", step="保存内容")

                # 记录章节审计日志
                final_audit = final_audit_result if final_audit_result else {}
                engine.add_audit_log(
                    book=book,
                    chapter_num=chapter_num,
                    action="write",
                    audit_result=type('AuditResult', (), final_audit)() if final_audit else None,
                    chapter_status="final" if result.get('passed') else "draft",
                    message=result.get('message', ''),
                    revision_reasons=revision_history
                )
                
            elif data.action == "review":
                task_manager.update_task(task.id, status=TaskStatus.RUNNING, progress=10,
                                        message=f"正在获取{chapter_title}内容...", step="获取内容")

                # 检查是否已取消
                if task_manager.is_cancelled(task.id):
                    task_manager.update_task(task.id, status=TaskStatus.TERMINATED, message="任务已取消")
                    task_manager.unlock_chapter(data.book_id, chapter_num)
                    return

                # 评审：获取章节内容并审核
                chapter_info = engine.get_chapter_content(data.book_id, chapter_num)
                content = chapter_info.get('chapter', {}).get('content', '') if chapter_info.get('success') else ''

                task_manager.update_task(task.id, progress=40,
                                        message=f"正在分析{chapter_title}内容...", step="分析内容")

                truth_files = engine._load_truth_files(book)

                task_manager.update_task(task.id, progress=70,
                                        message=f"正在对{chapter_title}进行评分...", step="质量评分")

                audit_result = engine._audit_chapter(book, chapter_num, content, truth_files)

                # 保存评审报告
                audit_report_path = ""
                audit_report_content = ""
                try:
                    audit_report_path = engine.save_audit_report(book, chapter_num, content, audit_result)
                    audit_report_content = engine._generate_audit_report(book, chapter_num, content, audit_result)
                except Exception as e:
                    print(f"保存评审报告失败: {e}")

                result = {
                    "success": True,
                    "message": f"{chapter_title}评审完成",
                    "audit_result": audit_result.to_dict(),
                    "audit_report": audit_report_content,  # 用于前端展示
                    "audit_report_path": audit_report_path
                }

                # 记录评审日志
                engine.add_audit_log(
                    book=book,
                    chapter_num=chapter_num,
                    action="review",
                    audit_result=audit_result,
                    chapter_status="draft",
                    message="单独评审"
                )

                # 生成章节简报
                chapter_brief = engine.generate_chapter_brief(book, chapter_num)
                result['chapter_brief'] = chapter_brief
                
            elif data.action in ("revise", "regenerate"):
                task_manager.update_task(task.id, status=TaskStatus.RUNNING, progress=10, 
                                        message=f"正在重新生成{chapter_title}...", step="重新生成")

                # 检查是否已取消
                if task_manager.is_cancelled(task.id):
                    task_manager.update_task(task.id, status=TaskStatus.TERMINATED, message="任务已取消")
                    task_manager.unlock_chapter(data.book_id, chapter_num)
                    return
                
                # 修订/重新生成：将旧内容移动到trash文件夹，再重新创作
                chapter_path = Path(workspace) / book.path / "chapters" / f"chapter_{chapter_num}.md"
                trash_path = Path(workspace) / book.path / "chapters" / "trash"
                
                if chapter_path.exists():
                    # 创建trash文件夹（如果不存在）
                    trash_path.mkdir(parents=True, exist_ok=True)
                    
                    # 读取旧内容
                    old_content = chapter_path.read_text(encoding='utf-8')
                    
                    # 生成带时间戳的文件名
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_name = f"chapter_{chapter_num}_{timestamp}.md"
                    backup_path = trash_path / backup_name
                    
                    # 写入trash文件夹
                    backup_path.write_text(old_content, encoding='utf-8')
                    
                    # 删除原文件
                    chapter_path.unlink()
                    
                    task_manager.update_task(task.id, progress=15,
                                            message=f"已将旧版本保存到trash: {backup_name}", step="备份旧版本")

                # LLM错误重试机制（最多3次）
                max_retries = 3
                llm_retry_count = 0
                last_error = ""
                write_success = False

                while llm_retry_count < max_retries:
                    try:
                        result = engine.write_chapter(chapter_num)
                        write_success = True
                        break
                    except LLMError as e:
                        llm_retry_count += 1
                        last_error = str(e)
                        if llm_retry_count < max_retries:
                            import time
                            retry_msg = f"LLM错误（第{llm_retry_count}/{max_retries}次），等待30秒后自动重试..."
                            print(f"[{task.id}] {retry_msg}")
                            task_manager.update_task(task.id, progress=15, message=retry_msg, step="LLM重试")
                            task_manager.mark_retry_pending(task.id, str(e))
                            time.sleep(30)
                            task_manager.retry_task(task.id)
                        else:
                            task_manager.update_task(task.id, status=TaskStatus.FAILED,
                                message=f"LLM错误已达最大重试次数: {e}", error=str(e), step="LLM重试失败")
                            task_manager.unlock_chapter(data.book_id, chapter_num)
                            return

                if not write_success:
                    return

                # 记录修订日志（如果结果包含审核信息）
                if result.get('audit_result'):
                    engine.add_audit_log(
                        book=book,
                        chapter_num=chapter_num,
                        action="revise",
                        audit_result=type('AuditResult', (), result['audit_result'])(),
                        chapter_status="final" if result.get('success') else "draft",
                        message=result.get('message', ''),
                        revision_reasons=result.get('revision_reasons', [])
                    )
            
            # 第3章创作/修订完成后，触发黄金三章审查
            if chapter_num == 3 and data.action in ("continue", "revise", "regenerate"):
                task_manager.update_task(task.id, progress=95,
                                        message="正在进行黄金三章评审...", step="黄金三章")
                golden_result = engine.audit_golden_chapters(book)
                result['golden_audit'] = golden_result

                # 记录黄金三章审查日志
                engine.add_golden_audit_log(book, golden_result)

                # 根据黄金三章结果给出建议
                if golden_result.get('decision_type') == 'rewrite':
                    result['suggest_revise'] = True
                    result['suggest_message'] = "黄金三章审查：建议重新修订前3章"
                elif golden_result.get('decision_type') == 'revision':
                    result['suggest_revise'] = True
                    result['suggest_message'] = "黄金三章审查：建议优化前3章"

            # 每5章触发连贯性检查（长线/纵向检查）
            if chapter_num % 5 == 0 and data.action in ("continue", "revise", "regenerate"):
                task_manager.update_task(task.id, progress=97,
                                        message="正在进行长线连贯性检查...", step="连贯性检查")
                continuity_result = engine.check_continuity(book, chapter_num)
                result['continuity_audit'] = continuity_result

                # 记录连贯性检查日志
                if continuity_result.get('success'):
                    engine.add_audit_log(
                        book=book,
                        chapter_num=chapter_num,
                        action="continuity_check",
                        audit_result=None,
                        chapter_status="draft",
                        message=f"连贯性检查完成，综合评分: {continuity_result.get('overall_score', 0)}"
                    )

            task_manager.update_task(task.id, progress=100, message=f"{chapter_title}{action_name}完成！",
                                    result=result, status=TaskStatus.SUCCESS)
        except Exception as e:
            task_manager.update_task(task.id, status=TaskStatus.FAILED, 
                                    message=f"执行失败: {str(e)}", error=str(e))
        finally:
            # 任务完成后解锁章节
            task_manager.unlock_chapter(data.book_id, chapter_num)
    
    threading.Thread(target=run, daemon=True).start()
    
    return {"success": True, "task_id": task.id, "message": f"{action_name}任务已启动", "chapter_num": chapter_num}


class AutoWriteRequest(BaseModel):
    book_id: str = ""
    chapter_count: int = 5  # 要生成的章节数量
    auto_review: bool = True
    auto_revise: bool = True
    review_score: int = 75


@router.post("/write/auto")
async def auto_write(data: AutoWriteRequest):
    """自动续写"""
    if not data.book_id:
        raise HTTPException(status_code=400, detail="缺少书籍ID")
    
    # 计算起始章节（当前已完成的最后一章+1）
    book = engine.get_book(data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    # 获取当前已完成的章节数
    chapters_dir = engine.workspace / book.path / "chapters"
    existing_chapters = []
    if chapters_dir.exists():
        # 只匹配真正的章节文件 chapter_*.md，排除 outline_*、reflection_* 等辅助文件
        existing_chapters = [
            int(f.stem.split('_')[1]) for f in chapters_dir.glob("chapter_*.md")
            if len(f.stem.split('_')) > 1 and f.stem.split('_')[1].isdigit()
        ]
    start_chapter = max(existing_chapters) + 1 if existing_chapters else 1
    end_chapter = start_chapter + data.chapter_count - 1
    
    # 创建任务
    task = task_manager.create_task(f"自动续写 {data.book_id} 第{start_chapter}-{end_chapter}章", book_id=data.book_id, task_type="auto_write")
    
    # 后台运行
    def run():
        try:
            results = []
            total = data.chapter_count
            for idx, i in enumerate(range(start_chapter, end_chapter + 1)):
                # 检查是否已取消
                if task_manager.is_cancelled(task.id):
                    task_manager.update_task(task.id, status=TaskStatus.TERMINATED,
                                           message=f"任务已取消，已完成{idx}章", result=results)
                    return

                task_manager.update_task(task.id, progress=int((idx / total) * 80),
                                        message=f"正在创作第{i}章...", step=f"创作第{i}章")

                # LLM错误重试机制（最多3次）
                max_retries = 3
                llm_retry_count = 0
                chapter_success = False

                while llm_retry_count < max_retries:
                    try:
                        result = engine.write_chapter(i)
                        results.append({
                            "chapter_num": i,
                            "success": result.get('success', False)
                        })
                        chapter_success = True
                        break
                    except LLMError as e:
                        llm_retry_count += 1
                        if llm_retry_count < max_retries:
                            import time
                            print(f"[auto_write] 第{i}章 LLM错误（第{llm_retry_count}/{max_retries}次），等待30秒...")
                            time.sleep(30)
                        else:
                            results.append({
                                "chapter_num": i,
                                "success": False,
                                "message": f"LLM错误达最大重试次数: {e}"
                            })

                if not chapter_success:
                    # 某个章节失败，停止后续章节创作
                    break
            
            task_manager.update_task(task.id, progress=100, message="完成", result=results, 
                                    status=TaskStatus.SUCCESS)
        except Exception as e:
            task_manager.update_task(task.id, status=TaskStatus.FAILED,
                                   message=f"执行失败: {str(e)}", error=str(e))
    
    import threading
    threading.Thread(target=run, daemon=True).start()
    
    return {"success": True, "task_id": task.id, "message": "任务已启动"}


# ============== 任务管理 ==============

@router.get("/tasks")
async def list_tasks():
    """列出所有任务"""
    tasks = task_manager.list_tasks()
    return {"success": True, "tasks": tasks}


@router.get("/tasks/running")
async def get_running_tasks():
    """获取所有运行中的任务"""
    tasks = task_manager.get_running_tasks()
    return {"success": True, "tasks": tasks, "count": len(tasks)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务状态"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "task": task.to_dict()}


@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """取消任务"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_manager.cancel_task(task_id)
    return {"success": True, "message": "任务已取消"}


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    """手动重试失败的任务（LLM错误后）"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != TaskStatus.FAILED:
        raise HTTPException(status_code=400, detail="只能重试失败的任务")

    success = task_manager.retry_task(task_id)
    if not success:
        return {"success": False, "message": "重试失败"}

    return {
        "success": True,
        "message": "任务已重置，请调用原任务接口继续执行",
        "task_id": task_id,
        "retry_count": task.retry_count
    }


@router.get("/tasks/{task_id}/checklist")
async def get_task_checklist(task_id: str):
    """获取任务步骤 checklist"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "success": True,
        "task_id": task_id,
        "task_status": task.status.value,
        "current_step_index": task.current_step_index,
        "checklist": task_manager.get_task_checklist(task_id)
    }


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    """从断点恢复任务，自动从第一个未完成步骤继续"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    next_step_index = task_manager.resume_task(task_id)
    if next_step_index < 0:
        return {"success": True, "message": "任务已完成，无须恢复", "task_id": task_id}

    next_step_name = task.steps[next_step_index].name if next_step_index < len(task.steps) else ""
    return {
        "success": True,
        "message": f"任务已恢复，将从步骤「{next_step_name}」（第{next_step_index + 1}步）继续",
        "task_id": task_id,
        "next_step_index": next_step_index,
        "next_step_name": next_step_name
    }


@router.post("/tasks/{task_id}/steps/{step_index}/skip")
async def skip_step(task_id: str, step_index: int, reason: str = ""):
    """手动跳过指定步骤"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    success = task_manager.skip_step(task_id, step_index, reason)
    if not success:
        raise HTTPException(status_code=400, detail="跳过步骤失败")

    step_name = task.steps[step_index].name if step_index < len(task.steps) else ""
    return {
        "success": True,
        "message": f"步骤「{step_name}」已跳过",
        "task_id": task_id,
        "step_index": step_index
    }


@router.post("/tasks/terminate-all")
async def terminate_all_tasks():
    """终止所有运行中的任务"""
    terminated_count = task_manager.terminate_all_tasks()
    return {
        "success": True,
        "message": f"已终止 {terminated_count} 个任务",
        "terminated_count": terminated_count
    }


# ============== 文档管理 ==============

class RegenerateDocRequest(BaseModel):
    book_id: str = ""
    doc_key: str = ""


@router.post("/docs/regenerate")
async def regenerate_doc(data: RegenerateDocRequest):
    """重新生成文档"""
    if not data.book_id:
        raise HTTPException(status_code=400, detail="缺少书籍ID")
    if not data.doc_key:
        raise HTTPException(status_code=400, detail="缺少文档类型")

    # 检查文档类型是否有效
    valid_docs = ['planning', 'story_bible', 'book_rules', 'chapter_outline']
    if data.doc_key not in valid_docs:
        raise HTTPException(status_code=400, detail="无效的文档类型")

    # 获取书籍
    book = engine.get_book(data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 创作简报需要用户输入，返回提示
    if data.doc_key == 'planning':
        return {
            "success": False,
            "need_input": True,
            "message": "创作简报需要用户输入"
        }

    # 根据文档类型调用对应的生成方法
    doc_names = {
        'planning': '创作简报',
        'story_bible': '世界观设定',
        'book_rules': '书籍规则',
        'chapter_outline': '章节大纲'
    }

    doc_name = doc_names.get(data.doc_key, data.doc_key)
    
    # 创建后台任务
    task = task_manager.create_task(f"重新生成{doc_name}", book_id=data.book_id, task_type="doc_regenerate")
    
    def run_regenerate_task():
        """后台执行设定文档重新生成"""
        try:
            task_manager.update_task(task.id, status=TaskStatus.RUNNING, progress=10, 
                                    message=f"开始重新生成{doc_name}...", step="准备中")
            
            result = None
            if data.doc_key == 'story_bible':
                result = engine.create_story_bible(book_id=data.book_id)
            elif data.doc_key == 'book_rules':
                result = engine.create_book_rules(book_id=data.book_id)
            elif data.doc_key == 'chapter_outline':
                result = engine.create_chapter_outline(book_id=data.book_id)
            
            if result and result.get('success'):
                task_manager.update_task(task.id, status=TaskStatus.SUCCESS, progress=100,
                                        message=result.get('message', f'{doc_name}生成成功'),
                                        result=result)
            else:
                task_manager.update_task(task.id, status=TaskStatus.FAILED,
                                        message=result.get('message', '生成失败') if result else '生成失败')
        except Exception as e:
            task_manager.update_task(task.id, status=TaskStatus.FAILED, 
                                    message=f"生成失败: {str(e)}", error=str(e))
    
    # 启动后台线程
    thread = threading.Thread(target=run_regenerate_task, daemon=True)
    thread.start()
    
    return {"success": True, "task_id": task.id, "message": f"正在重新生成{doc_name}..."}


class SavePlanningRequest(BaseModel):
    book_id: str = ""
    content: str = ""


@router.post("/docs/planning/save")
async def save_planning(data: SavePlanningRequest):
    """保存创作简报 - 用AI解析简报并生成规范规划书"""
    if not data.book_id:
        raise HTTPException(status_code=400, detail="缺少书籍ID")

    book = engine.get_book(data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    try:
        # 用AI解析简报生成规范规划书
        planning = engine._parse_brief(data.content)
        
        # 生成规划书文档
        yaml_content = engine._generate_planning_doc(planning)
        
        # 保存规划书
        book_path = engine.workspace / book.path
        engine.sm.fm.write_text(book_path / "planning.md", yaml_content)
        
        # 更新书籍信息
        if planning.get('genre'):
            book.genre = planning['genre']
        if planning.get('platform'):
            book.platform = planning['platform']
        if planning.get('words_per_chapter'):
            book.words_per_chapter = planning['words_per_chapter']
        if planning.get('estimated_chapters'):
            book.total_chapters = planning['estimated_chapters']
        
        # 保存书籍元数据
        engine.sm.save_book_meta(book)
        
        return {
            "success": True, 
            "message": "创作简报已生成并保存",
            "planning": planning
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        # 如果AI解析失败，至少保存原始内容
        book_path = engine.workspace / book.path
        engine.sm.fm.write_text(book_path / "planning.md", data.content)
        return {
            "success": True, 
            "message": "已保存（AI解析失败）",
            "error": str(e)
        }


# ============== 文档评审报告 ==============

class DocAuditRequest(BaseModel):
    book_id: str
    doc_key: str


@router.get("/docs/{book_id}/{doc_key}/audit")
async def get_doc_audit_report(book_id: str, doc_key: str):
    """获取文档的最新评审报告"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 文档名称映射
    doc_names = {
        'story_bible': '世界观设定',
        'book_rules': '书籍规则',
        'chapter_outline': '章节大纲'
    }

    doc_name = doc_names.get(doc_key)
    if not doc_name:
        return {"found": False, "message": "不支持评审此文档"}

    result = engine.get_latest_doc_audit_report(book, doc_name)
    return result


# ============== Trash 文件夹管理 ==============

@router.get("/books/{book_id}/trash")
async def get_trash_items(book_id: str):
    """获取 trash 文件夹中的内容"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    trash_path = Path(workspace) / book.path / "chapters" / "trash"
    if not trash_path.exists():
        return {"success": True, "items": []}
    
    items = []
    for f in sorted(trash_path.glob("chapter_*.md"), reverse=True):
        # 从文件名解析章节号和时间戳
        # 格式: chapter_{num}_{timestamp}.md
        name_parts = f.stem.split('_')
        if len(name_parts) >= 3:
            chapter_num = name_parts[1]
            timestamp = name_parts[2]
            # 格式化时间戳
            try:
                from datetime import datetime
                dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                time_str = timestamp
            
            # 获取文件大小
            size = f.stat().st_size
            
            items.append({
                "filename": f.name,
                "chapter_num": int(chapter_num),
                "time": time_str,
                "size": size
            })
    
    return {"success": True, "items": items}


@router.get("/books/{book_id}/trash/{filename}")
async def get_trash_item(book_id: str, filename: str):
    """获取 trash 中指定文件的内容"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    # 安全检查：只允许 .md 文件
    if not filename.endswith('.md') or '..' in filename:
        raise HTTPException(status_code=400, detail="无效的文件名")
    
    trash_path = Path(workspace) / book.path / "chapters" / "trash" / filename
    if not trash_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    try:
        content = trash_path.read_text(encoding='utf-8')
        return {"success": True, "content": content, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RestoreChapterRequest(BaseModel):
    book_id: str = ""
    filename: str = ""


@router.post("/books/{book_id}/trash/restore")
async def restore_chapter(data: RestoreChapterRequest):
    """从 trash 恢复章节"""
    book = engine.get_book(data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    # 安全检查
    if not data.filename.endswith('.md') or '..' in data.filename:
        raise HTTPException(status_code=400, detail="无效的文件名")
    
    trash_path = Path(workspace) / book.path / "chapters" / "trash" / data.filename
    if not trash_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # 解析文件名获取章节号
    name_parts = data.filename.stem.split('_')
    if len(name_parts) >= 3:
        chapter_num = int(name_parts[1])
    else:
        raise HTTPException(status_code=400, detail="无法解析章节号")
    
    # 检查当前章节是否存在，如果存在则先备份
    current_path = Path(workspace) / book.path / "chapters" / f"chapter_{chapter_num}.md"
    if current_path.exists():
        # 将当前版本也移到 trash
        trash_dir = Path(workspace) / book.path / "chapters" / "trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        current_backup = trash_dir / f"chapter_{chapter_num}_{timestamp}.md"
        current_path.rename(current_backup)
    
    # 恢复文件
    content = trash_path.read_text(encoding='utf-8')
    current_path.write_text(content, encoding='utf-8')
    
    # 从 trash 删除
    trash_path.unlink()
    
    chapter_name = f"第{chapter_num}章"
    return {"success": True, "message": f"{chapter_name}已从trash恢复", "chapter_num": chapter_num}


class DeleteTrashItemRequest(BaseModel):
    book_id: str = ""
    filename: str = ""


@router.delete("/books/{book_id}/trash/{filename}")
async def delete_trash_item(book_id: str, filename: str):
    """永久删除 trash 中的文件"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 安全检查
    if not filename.endswith('.md') or '..' in filename:
        raise HTTPException(status_code=400, detail="无效的文件名")

    trash_path = Path(workspace) / book.path / "chapters" / "trash" / filename
    if not trash_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    trash_path.unlink()
    return {"success": True, "message": "文件已永久删除"}


class ChatQueryRequest(BaseModel):
    book_id: str = ""
    query: str = ""


@router.post("/chat/handle")
async def handle_chat_query(data: ChatQueryRequest):
    """处理用户对话查询（非预设任务）"""
    if not data.book_id:
        raise HTTPException(status_code=400, detail="缺少书籍ID")
    if not data.query:
        raise HTTPException(status_code=400, detail="缺少查询内容")
    
    query = data.query.strip().lower()
    
    # 检查书籍是否存在
    book = engine.sm.get_book_by_id(data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    # 识别任务类型
    task_name = "处理查询"
    doc_key = None
    
    if "大纲" in data.query:
        task_name = "创建章节大纲"
        doc_key = "chapter_outline"
    elif "世界观" in data.query or "设定" in data.query:
        task_name = "创建世界观设定"
        doc_key = "story_bible"
    elif "规则" in data.query:
        task_name = "创建书籍规则"
        doc_key = "book_rules"
    elif "简报" in data.query or "创作构想" in data.query:
        task_name = "创建创作简报"
        doc_key = "planning"
    else:
        task_name = f"处理: {data.query[:20]}..."
    
    # 创建任务
    task = task_manager.create_task(task_name)
    
    def run_query_task():
        try:
            task_manager.update_task(task.id, status=TaskStatus.RUNNING, progress=10,
                                    message=f"正在开始{task_name}...", step="准备中")
            
            if doc_key == "chapter_outline":
                task_manager.update_task(task.id, progress=30,
                                        message=f"正在分析创作简报...", step="分析简报")
                task_manager.update_task(task.id, progress=50,
                                        message=f"正在生成章节大纲...", step="生成大纲")
                result = engine.create_chapter_outline(book_id=data.book_id)
                
            elif doc_key == "story_bible":
                task_manager.update_task(task.id, progress=30,
                                        message=f"正在分析创作简报...", step="分析简报")
                task_manager.update_task(task.id, progress=50,
                                        message=f"正在生成世界观设定...", step="生成世界观")
                result = engine.create_story_bible(book_id=data.book_id)
                
            elif doc_key == "book_rules":
                task_manager.update_task(task.id, progress=30,
                                        message=f"正在分析世界观...", step="分析世界观")
                task_manager.update_task(task.id, progress=50,
                                        message=f"正在生成创作规则...", step="生成规则")
                result = engine.create_book_rules(book_id=data.book_id)
                
            elif doc_key == "planning":
                task_manager.update_task(task.id, progress=30,
                                        message=f"正在分析创作构想...", step="分析构想")
                task_manager.update_task(task.id, progress=50,
                                        message=f"正在生成创作简报...", step="生成简报")
                result = {"success": False, "message": "创作简报需要用户提供内容"}
            else:
                # 其他通用查询
                task_manager.update_task(task.id, progress=50,
                                        message=f"正在处理: {data.query[:30]}...", step="处理中")
                result = {"success": False, "message": f"无法识别任务: {data.query}"}
            
            task_manager.update_task(task.id, progress=100,
                                    message=f"{task_name}完成", result=result,
                                    status=TaskStatus.SUCCESS if result.get('success') else TaskStatus.FAILED)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            task_manager.update_task(task.id, status=TaskStatus.FAILED,
                                    message=f"执行失败: {str(e)}", error=str(e))
    
    import threading
    threading.Thread(target=run_query_task, daemon=True).start()
    
    return {"success": True, "task_id": task.id, "message": f"{task_name}任务已启动"}


# ============== 删除章节 ==============

@router.delete("/books/{book_id}/chapters/{chapter_num}")
async def delete_chapter(book_id: str, chapter_num: int):
    """删除章节（移动到trash）"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 获取章节文件路径
    chapter_path = Path(workspace) / book.path / "chapters" / f"chapter_{chapter_num}.md"

    if not chapter_path.exists():
        raise HTTPException(status_code=404, detail="章节不存在")

    # 读取内容
    content = chapter_path.read_text(encoding='utf-8')

    # 创建trash文件夹
    trash_path = Path(workspace) / book.path / "chapters" / "trash"
    trash_path.mkdir(parents=True, exist_ok=True)

    # 生成带时间戳的文件名
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"chapter_{chapter_num}_{timestamp}.md"
    backup_path = trash_path / backup_name

    # 写入trash文件夹
    backup_path.write_text(content, encoding='utf-8')

    # 删除原文件
    chapter_path.unlink()

    chapter_name = f"第{chapter_num}章"
    return {"success": True, "message": f"{chapter_name}已移至回收站"}


# ============== 对话日志 ==============

@router.post("/books/{book_id}/chat-logs")
async def save_chat_log(book_id: str, request: Request):
    """保存对话日志到书籍目录"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    try:
        data = await request.json()
        filename = data.get('filename')
        content = data.get('content')

        if not filename or not content:
            raise HTTPException(status_code=400, detail="缺少文件名或内容")

        # 安全检查
        if '..' in filename or not filename.endswith('.json'):
            raise HTTPException(status_code=400, detail="无效的文件名")

        # 创建 chat_logs 目录
        chat_logs_dir = Path(workspace) / book.path / "chat_logs"
        chat_logs_dir.mkdir(parents=True, exist_ok=True)

        # 保存文件
        file_path = chat_logs_dir / filename
        file_path.write_text(content, encoding='utf-8')

        return {"success": True, "message": f"对话已保存到 {filename}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/books/{book_id}/chat-logs")
async def get_chat_logs(book_id: str):
    """获取书籍的对话日志列表"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    chat_logs_dir = Path(workspace) / book.path / "chat_logs"
    if not chat_logs_dir.exists():
        return {"success": True, "logs": []}

    logs = []
    for f in sorted(chat_logs_dir.glob("*.json"), reverse=True):
        logs.append({
            "filename": f.name,
            "size": f.stat().st_size,
            "created": f.stat().st_ctime
        })

    return {"success": True, "logs": logs}


@router.get("/books/{book_id}/chat-logs/{filename}")
async def get_chat_log_content(book_id: str, filename: str):
    """获取对话日志内容"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 安全检查
    if '..' in filename or not filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="无效的文件名")

    chat_logs_dir = Path(workspace) / book.path / "chat_logs"
    file_path = chat_logs_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    content = file_path.read_text(encoding='utf-8')
    return {"success": True, "content": content, "filename": filename}


@router.delete("/books/{book_id}/chat-logs/{filename}")
async def delete_chat_log(book_id: str, filename: str):
    """删除对话日志"""
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    # 安全检查
    if '..' in filename or not filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="无效的文件名")

    chat_logs_dir = Path(workspace) / book.path / "chat_logs"
    file_path = chat_logs_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    file_path.unlink()
    return {"success": True, "message": "对话日志已删除"}
