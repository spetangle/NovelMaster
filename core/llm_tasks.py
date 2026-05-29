# -*- coding: utf-8 -*-
"""
标准化 LLM 任务模块
所有 LLM 任务都通过此类实现，确保格式控制和输出过滤的一致性
"""

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict
import threading


class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"
    STOPPED = "stopped"
    CANCELLED = "cancelled"


class StepStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


class FilterRule:
    LOG_BLOCK = "log_block"           # ━━━━━...━━━ 包围的块
    THINK_TAGS = "think_tags"         #<think>...</think> 标签
    LOG_BRACKETS = "log_brackets"     # [LOG]... 括号块
    GUIDE_QUOTES = "guide_quotes"     # "以下是..."、"输出规范：" 等引导语
    CODE_BLOCK = "code_block"         # ```...``` 代码块


class OutputFilter:
    """输出过滤器"""

    PATTERNS = {
        FilterRule.LOG_BLOCK: re.compile(r'━{3,}\s*\n(?:.*?\n)*?.*?━{3,}', re.DOTALL),
        FilterRule.THINK_TAGS: re.compile(r'<think>[\s\S]*?</think>', re.DOTALL),
        FilterRule.LOG_BRACKETS: re.compile(r'\[LOG\][^\[]*?(?=\[LOG\]|$)', re.DOTALL),
        FilterRule.GUIDE_QUOTES: re.compile(r'^以下(是|为).*?[:：]\s*', re.MULTILINE),
        FilterRule.CODE_BLOCK: re.compile(r'```[\s\S]*?```'),
    }

    # 行首标签：(pattern, replacement) 元组列表
    LINE_PREFIX_PATTERNS = [
        (re.compile(r'^\s*\[LOG\].*$', '', re.MULTILINE), ''),
        (re.compile(r'^\s*任务名称:.*$', '', re.MULTILINE), ''),
        (re.compile(r'^\s*当前 Agent:.*$', '', re.MULTILINE), ''),
        (re.compile(r'^\s*当前阶段:.*$', '', re.MULTILINE), ''),
        (re.compile(r'^\s*预计产出:.*$', '', re.MULTILINE), ''),
        (re.compile(r'^\s*字数要求:.*$', '', re.MULTILINE), ''),
        (re.compile(r'^\s*输出规范:.*$', '', re.MULTILINE), ''),
        (re.compile(r'^\s*调用规范:.*$', '', re.MULTILINE), ''),
    ]

    # 段落级过滤：(pattern, replacement) 元组列表
    PARAGRAPH_PATTERNS = [
        (re.compile(r'^缩[^。]*原则.*$', '', re.MULTILINE), ''),
        (re.compile(r'^扩[^。]*原则.*$', '', re.MULTILINE), ''),
    ]

    @classmethod
    def apply(cls, content: str, rules: List[str] = None) -> str:
        """应用过滤规则"""
        if not content:
            return content

        rules = rules or [FilterRule.LOG_BLOCK, FilterRule.THINK_TAGS, FilterRule.LOG_BRACKETS]

        for rule in rules:
            pattern = cls.PATTERNS.get(rule)
            if pattern:
                content = pattern.sub('', content)

        # 行首标签
        for pattern, repl in cls.LINE_PREFIX_PATTERNS:
            content = pattern.sub(repl, content)

        # 段落过滤
        for pattern, repl in cls.PARAGRAPH_PATTERNS:
            content = pattern.sub(repl, content)

        # 清理多余空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        # 移除首尾空白
        content = content.strip()

        return content


@dataclass
class LLMResult:
    """LLM 调用结果"""
    success: bool
    content: str = ""
    data: Any = None
    error: str = ""
    duration: float = 0.0
    tokens_used: int = 0


class LLMCallable(ABC):
    """LLM 任务的基类"""

    name: str = ""           # 任务名称，如 "expander", "auditor"
    agent_name: str = ""       # 对应的 agent 名称
    system_prompt: str = ""   # 系统提示词
    output_format: str = "text"  # 输出格式：text 或 json
    filter_rules: List[str] = None  # 过滤规则列表

    def __post_init__(self):
        if self.filter_rules is None:
            self.filter_rules = [FilterRule.LOG_BLOCK, FilterRule.THINK_TAGS, FilterRule.LOG_BRACKETS]

    @abstractmethod
    def build_user_prompt(self, context: dict) -> str:
        """构建用户提示词"""
        pass

    def filter_output(self, raw_output: str) -> str:
        """过滤原始输出"""
        return OutputFilter.apply(raw_output, self.filter_rules)

    def execute(self, context: dict, llm_client=None) -> LLMResult:
        """执行任务"""
        start_time = time.time()

        # 构建提示词
        user_prompt = self.build_user_prompt(context)

        if llm_client is None:
            from core.llm_service import LLMService
            llm_client = LLMService()

        try:
            if self.output_format == "json":
                result_obj = llm_client.generate_json(user_prompt, self.system_prompt, self.agent_name)
                if result_obj:
                    return LLMResult(
                        success=True,
                        content=str(result_obj),
                        data=result_obj,
                        duration=time.time() - start_time
                    )
                else:
                    return LLMResult(
                        success=False,
                        error="JSON 解析失败",
                        duration=time.time() - start_time
                    )
            else:
                content = llm_client.generate(user_prompt, self.system_prompt, self.agent_name)
                if content and not content.startswith("[生成失败"):
                    filtered = self.filter_output(content)
                    return LLMResult(
                        success=True,
                        content=filtered,
                        duration=time.time() - start_time
                    )
                else:
                    return LLMResult(
                        success=False,
                        content=content,
                        error=f"生成失败: {content}",
                        duration=time.time() - start_time
                    )
        except Exception as e:
            return LLMResult(
                success=False,
                error=str(e),
                duration=time.time() - start_time
            )


# ============ 具体任务实现 ============

class ExpanderTask(LLMCallable):
    """扩写任务"""

    name = "expander"
    agent_name = "expander"
    output_format = "text"
    system_prompt = """你是专业的小说扩写专家，擅长在保持原文风格和情节完整性的基础上合理扩展内容。

## 扩写原则
1. 保持一致性：扩写内容必须与原文风格、人物性格、情节逻辑完全一致
2. 深化细节：通过增加心理描写、环境描写、对话细节来丰富内容
3. 推动情节：扩写内容必须服务于主线情节，不能注水
4. 控制节奏：扩写应使节奏更舒缓有度，而非拖沓
5. 自然过渡：扩写段落与原文衔接自然，无突兀感

## 输出规范
- 直接输出扩写后的完整章节内容
- 不要添加任何说明文字、思考过程、LOG块
- 不要改变原文结构
- 不要输出任何引导语"""

    def build_user_prompt(self, context: dict) -> str:
        target = context.get('target_words', 3000)
        current = context.get('current_words', 0)
        content = context.get('chapter_content', '')
        return f"""请将以下章节扩写至约 {target} 字。

当前字数：{current} 字
目标字数：{target} 字

## 原文内容
{content}

## 输出要求
直接输出扩写后的完整正文，不要包含任何说明。"""


class CondenserTask(LLMCallable):
    """缩写任务"""

    name = "condenser"
    agent_name = "condenser"
    output_format = "text"
    system_prompt = """你是专业的小说缩写专家，擅长在保持核心情节和人物性格的基础上精简内容。

## 缩写原则
1. 保持核心：缩写不能改变原文的核心情节和人物性格
2. 删除冗余：移除重复描写，过度的心理独白、不必要的场景描写
3. 压缩对话：精简对话，保留信息量
4. 保持节奏：缩写后仍要保持合理的叙事节奏
5. 过渡自然：确保缩写后的内容衔接流畅

## 输出规范
- 直接输出缩写后的完整章节内容
- 不要添加任何说明文字、思考过程、LOG块
- 不要输出任何引导语"""

    def build_user_prompt(self, context: dict) -> str:
        target = context.get('target_words', 3000)
        current = context.get('current_words', 0)
        content = context.get('chapter_content', '')
        return f"""请将以下章节缩写至约 {target} 字。

当前字数：{current} 字
目标字数：{target} 字

## 原文内容
{content}

## 输出要求
直接输出缩写后的完整正文，不要包含任何说明。"""


class AuditorTask(LLMCallable):
    """评审任务"""

    name = "auditor"
    agent_name = "auditor"
    output_format = "json"
    system_prompt = """你是一位章节审计师，负责审查细纲质量。

## 审计维度（各维度满分20分）
1. 情节结构完整性 (25%)：起承转合是否齐全、逻辑通顺
2. 字数分配合理性 (30%)：各情节点字数分配是否匹配目标字数
3. 伏笔埋设质量 (20%)：伏笔是否合理、可回收
4. 钩子有效性 (15%)：结尾钩子是否制造悬念
5. 字数预估准确性 (10%)：预估字数是否在目标范围±500字内

通过标准：总分≥75 且 字数分配维度≥12分。

## 输出格式
返回 JSON：
{
    "plot_structure_score": 情节结构完整性得分(0-20),
    "word_allocation_score": 字数分配合理性得分(0-20),
    "foreshadowing_score": 伏笔埋设质量得分(0-20),
    "hook_score": 钩子有效性得分(0-20),
    "word_estimate_score": 字数预估准确性得分(0-20),
    "issues": [{"dimension": "维度名", "description": "问题描述", "severity": "高/中/低"}],
    "strengths": ["亮点1", "亮点2"],
    "overall_assessment": "综合评语"
}"""

    def build_user_prompt(self, context: dict) -> str:
        target = context.get('target_words', 3000)
        genre = context.get('genre', '都市')
        outline = context.get('outline', '')
        return f"""请审查以下细纲的质量。

【创作背景】
- 题材：{genre}
- 目标字数：约 {target} 字

【章节细纲】
{outline}

返回 JSON 格式的审查结果。"""


class GeneratorTask(LLMCallable):
    """生成性任务"""

    name = "generator"
    agent_name = "writer"
    output_format = "text"
    system_prompt = """你是一位专业的小说作者，擅长创作高质量的章节内容。

## 创作原则
1. 保持故事风格一致，符合书籍整体基调
2. 情节推进自然，节奏合理
3. 人物刻画鲜明，对话自然
4. 伏笔埋设和回收得当
5. 结尾留有悬念或钩子

## 输出格式要求
1. 只输出最终正文内容，不包含任何思考过程
2. 不输出 ``` 代码块标记
3. 不输出 [LOG]、[思考] 等标记
4. 直接返回正文内容，不要添加任何说明"""

    def build_user_prompt(self, context: dict) -> str:
        outline = context.get('outline', '')
        genre = context.get('genre', '都市')
        target_words = context.get('target_words', 3000)
        previous_content = context.get('previous_content', '')
        chapter_title = context.get('chapter_title', '')

        prompt = f"""请根据以下细纲创作章节内容。

【创作背景】
- 题材：{genre}
- 目标字数：约 {target_words} 字

"""
        if chapter_title:
            prompt += f"【章节标题】\n{chapter_title}\n\n"
        if previous_content:
            prompt += f"【前文概要】\n{previous_content}\n\n"
        prompt += f"【章节细纲】\n{outline}\n\n"
        prompt += "直接输出章节正文，不要包含任何说明。"
        return prompt


class WordCountAdjustTask(LLMCallable):
    """字数调整任务（扩写/缩写）"""

    name = "word_count_adjuster"
    agent_name = "expander" if context.get('expand', True) else "condenser"
    output_format = "text"
    system_prompt = """你是一位专业的小说编辑，擅长调整章节字数至目标范围。

## 调整原则
1. 扩写时：通过增加心理描写、环境描写、对话细节来丰富内容，不改变原文结构
2. 缩写时：删除冗余描写，保留核心情节和人物性格
3. 保持原文风格一致
4. 扩写内容必须服务于主线情节，不能注水

## 输出格式要求
1. 只输出调整后的正文内容，不包含任何思考过程
2. 不输出 ``` 代码块标记
3. 不输出 [LOG]、[思考] 等标记
4. 直接返回正文内容，不要添加任何说明"""

    def build_user_prompt(self, context: dict) -> str:
        target = context.get('target_words', 3000)
        current = context.get('current_words', 0)
        content = context.get('chapter_content', '')
        expand = context.get('expand', True)

        action = "扩写" if expand else "缩写"
        return f"""请将以下章节{action}至约 {target} 字。

当前字数：{current} 字
目标字数：{target} 字

## 原文内容
{content}

直接输出{action}后的完整正文，不要包含任何说明。"""


class ReviewTask(LLMCallable):
    """评审任务 - 审查章节内容"""

    name = "reviewer"
    agent_name = "auditor"
    output_format = "json"
    system_prompt = """你是一位章节审计师，负责审查章节质量。

## 审计维度
1. 情节连贯性 (25%)：与前文衔接是否自然，逻辑是否通顺
2. 字数达标度 (25%)：字数是否在目标范围±500字内
3. 伏笔处理 (20%)：伏笔是否合理埋设和回收
4. 钩子设置 (15%)：结尾是否制造悬念
5. 整体质量 (15%)：语句通顺度、人物刻画等

通过标准：总分≥75分 且 字数达标

## 输出格式
返回 JSON：
{
    "plot_continuity_score": 情节连贯性得分(0-100),
    "word_count_score": 字数达标度得分(0-100),
    "foreshadowing_score": 伏笔处理得分(0-100),
    "hook_score": 钩子设置得分(0-100),
    "overall_quality_score": 整体质量得分(0-100),
    "total_score": 总分(0-100),
    "passed": 是否通过,
    "issues": [{"dimension": "维度", "description": "问题描述", "severity": "高/中/低"}],
    "suggestions": ["改进建议1", "改进建议2"],
    "summary": "综合评语"
}"""

    def build_user_prompt(self, context: dict) -> str:
        target = context.get('target_words', 3000)
        genre = context.get('genre', '都市')
        content = context.get('content', '')
        previous_summary = context.get('previous_summary', '')
        outline = context.get('outline', '')

        prompt = f"""请审查以下章节的质量。

【创作背景】
- 题材：{genre}
- 目标字数：约 {target} 字

"""
        if previous_summary:
            prompt += f"【前文概要】\n{previous_summary}\n\n"
        if outline:
            prompt += f"【章节细纲】\n{outline}\n\n"
        prompt += f"【待审查章节】\n{content}\n\n"
        prompt += "返回 JSON 格式的审查结果。"
        return prompt


class RevisionTask(LLMCallable):
    """修订任务 - 基于评审意见修订章节"""

    name = "reviser"
    agent_name = "writer"
    output_format = "text"
    system_prompt = """你是一位专业的小说编辑，负责根据评审意见修订章节内容。

## 修订原则
1. 严格按照评审意见进行修订
2. 保持原文的核心情节和人物性格不变
3. 修订后内容要自然流畅，不生硬
4. 兼顾字数要求（目标字数±500字）

## 输出格式要求
1. 只输出修订后的正文内容，不包含任何思考过程
2. 不输出 ``` 代码块标记
3. 不输出 [LOG]、[思考] 等标记
4. 直接返回正文内容，不要添加任何说明"""

    def build_user_prompt(self, context: dict) -> str:
        target = context.get('target_words', 3000)
        content = context.get('content', '')
        review_result = context.get('review_result', {})

        issues = review_result.get('issues', [])
        suggestions = review_result.get('suggestions', [])

        prompt = f"""请根据以下评审意见修订章节内容。

【目标字数】
约 {target} 字

"""
        if issues:
            prompt += "【发现问题】\n"
            for issue in issues:
                prompt += f"- [{issue.get('severity', '中')}] {issue.get('dimension', '未知维度')}：{issue.get('description', '')}\n"
            prompt += "\n"

        if suggestions:
            prompt += "【改进建议】\n"
            for i, sug in enumerate(suggestions, 1):
                prompt += f"{i}. {sug}\n"
            prompt += "\n"

        prompt += f"【当前章节内容】\n{content}\n\n"
        prompt += "直接输出修订后的完整正文，不要包含任何说明。"
        return prompt


# ============ 任务包与任务池 ============

@dataclass
class SubTask:
    """子任务"""
    id: str = ""             # st_{uuid8} 格式
    name: str = ""           # 步骤名称，如"生成细纲"、"字数调整"
    agent: str = ""          # agent 名称，如 expander, condenser
    input_text: str = ""    # 输入文本
    input_files: List[str] = field(default_factory=list)   # 输入文件路径
    output_file: str = ""   # 输出文件路径
    status: str = StepStatus.PENDING
    result: Any = None      # LLMResult
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "agent": self.agent,
            "input_text": self.input_text[:200] + "..." if len(self.input_text) > 200 else self.input_text,
            "input_files": self.input_files,
            "output_file": self.output_file,
            "status": self.status,
            "result_content": self.result.content[:200] if self.result and self.result.content else None,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


@dataclass
class TaskPackage:
    """任务包：包含多个子任务，按顺序执行"""
    id: str = ""                              # pkg_{uuid8} 格式
    name: str = ""                            # 包名称，如"生成第3章"、"生成世界观设定"
    book_id: str = ""
    subtasks: List[SubTask] = field(default_factory=list)
    status: str = TaskStatus.PENDING
    current_subtask_index: int = 0
    created_at: float = field(default_factory=time.time)
    pause_event: threading.Event = field(default_factory=threading.Event)
    stop_event: threading.Event = field(default_factory=threading.Event)
    paused_subtask: int = -1     # 暂停的子任务索引，-1 表示未暂停

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "book_id": self.book_id,
            "status": self.status,
            "current_subtask_index": self.current_subtask_index,
            "total_subtasks": len(self.subtasks),
            "created_at": self.created_at,
            "paused_subtask": self.paused_subtask,
            "subtasks": [s.to_dict() for s in self.subtasks],
        }


class TaskPool:
    """任务池管理器"""

    def __init__(self):
        self._lock = threading.Lock()
        self.packages: Dict[str, TaskPackage] = {}
        self.package_queue: List[str] = []
        self._chapter_locks: Dict[str, str] = {}        # f"{book_id}:{chapter}" -> package_id
        self._book_locks: Dict[str, str] = {}           # book_id -> package_id

    def create_package(self, name: str, book_id: str, subtasks: List[SubTask] = None) -> TaskPackage:
        """创建任务包"""
        import uuid
        pkg_id = f"pkg_{uuid.uuid4().hex[:8]}"
        if subtasks is None:
            subtasks = []
        # 为子任务分配ID
        for i, st in enumerate(subtasks):
            if not st.id:
                st.id = f"st_{uuid.uuid4().hex[:8]}"
        pkg = TaskPackage(
            id=pkg_id,
            name=name,
            book_id=book_id,
            subtasks=subtasks
        )
        with self._lock:
            self.packages[pkg_id] = pkg
            self.package_queue.append(pkg_id)
        return pkg

    def get_package(self, package_id: str) -> Optional[TaskPackage]:
        with self._lock:
            return self.packages.get(package_id)

    def pause_package(self, package_id: str) -> bool:
        """暂停任务包（当前子任务完成后暂停）"""
        pkg = self.get_package(package_id)
        if not pkg:
            return False
        pkg.pause_event.set()
        pkg.status = TaskStatus.PAUSED
        pkg.paused_subtask = pkg.current_subtask_index
        return True

    def resume_package(self, package_id: str) -> bool:
        """继续被暂停的任务包"""
        pkg = self.get_package(package_id)
        if not pkg or pkg.status != TaskStatus.PAUSED:
            return False
        pkg.pause_event.clear()
        pkg.status = TaskStatus.RUNNING
        pkg.paused_subtask = -1
        return True

    def stop_package(self, package_id: str) -> bool:
        """停止任务包（立即停止）"""
        pkg = self.get_package(package_id)
        if not pkg:
            return False
        pkg.stop_event.set()
        pkg.status = TaskStatus.STOPPED
        return True

    def cancel_package(self, package_id: str) -> bool:
        """取消任务包（移除，保留已完成文件）"""
        pkg = self.get_package(package_id)
        if not pkg:
            return False
        pkg.status = TaskStatus.CANCELLED
        # 释放章节锁
        keys_to_remove = [k for k, v in self._chapter_locks.items() if v == package_id]
        for k in keys_to_remove:
            del self._chapter_locks[k]
        # 释放书籍锁
        bids_to_remove = [b for b, v in self._book_locks.items() if v == package_id]
        for b in bids_to_remove:
            del self._book_locks[b]
        with self._lock:
            if package_id in self.packages:
                del self.packages[package_id]
            if package_id in self.package_queue:
                self.package_queue.remove(package_id)
        return True

    def acquire_chapter_lock(self, book_id: str, chapter_num: int, package_id: str) -> bool:
        """尝试获取章节锁"""
        key = f"{book_id}:{chapter_num}"
        with self._lock:
            if key in self._chapter_locks:
                return self._chapter_locks[key] == package_id
            self._chapter_locks[key] = package_id
            return True

    def release_chapter_lock(self, book_id: str, chapter_num: int, package_id: str):
        """释放章节锁"""
        key = f"{book_id}:{chapter_num}"
        with self._lock:
            if self._chapter_locks.get(key) == package_id:
                del self._chapter_locks[key]

    def acquire_book_lock(self, book_id: str, package_id: str) -> bool:
        """尝试获取书籍锁"""
        with self._lock:
            if book_id in self._book_locks:
                return self._book_locks[book_id] == package_id
            self._book_locks[book_id] = package_id
            return True

    def release_book_lock(self, book_id: str, package_id: str):
        """释放书籍锁"""
        with self._lock:
            if self._book_locks.get(book_id) == package_id:
                del self._book_locks[book_id]

    def get_status(self) -> dict:
        """获取任务池整体状态"""
        with self._lock:
            running = [p.to_dict() for p in self.packages.values() if p.status == TaskStatus.RUNNING]
            paused = [p.to_dict() for p in self.packages.values() if p.status == TaskStatus.PAUSED]
            pending = [p.to_dict() for p in self.packages.values() if p.status == TaskStatus.PENDING]
            return {
                "running": running,
                "paused": paused,
                "pending": pending,
                "queue_size": len(self.package_queue),
                "chapter_locks": list(self._chapter_locks.keys()),
                "book_locks": list(self._book_locks.keys()),
            }


# 全局任务池实例
task_pool = TaskPool()
