# -*- coding: utf-8 -*-
"""
数据模型定义
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional
from datetime import datetime


class ChapterStatus(Enum):
    """章节状态枚举"""
    DRAFT = "draft"           # 草稿完成，等待审核
    REVIEWING = "reviewing"   # 审核中
    APPROVED = "approved"     # 审核通过，待终审
    FINAL = "final"          # 已定稿，标记完成

    @classmethod
    def from_string(cls, value: str) -> 'ChapterStatus':
        try:
            return cls(value)
        except ValueError:
            return cls.DRAFT


class AuditDecision(Enum):
    """审核决策"""
    PASS = "通过"
    NEEDS_REVISION = "修订后通过"
    FAIL = "不通过"


class ChapterStatusEnum(Enum):
    """章节状态"""
    DRAFT = "draft"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    FINAL = "final"


@dataclass
class BookInfo:
    """书籍信息"""
    id: str
    name: str
    path: str
    genre: str
    platform: str = "番茄小说"
    words_per_chapter: int = 3000
    total_chapters: int = 80
    completed_chapters: int = 0
    status: str = "进行中"
    created_at: str = ""
    is_inspiration: bool = False  # 是否为灵感对话模式

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "genre": self.genre,
            "platform": self.platform,
            "words_per_chapter": self.words_per_chapter,
            "total_chapters": self.total_chapters,
            "completed_chapters": self.completed_chapters,
            "status": self.status,
            "created_at": self.created_at,
            "is_inspiration": self.is_inspiration
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'BookInfo':
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            path=data.get("path", ""),
            genre=data.get("genre", ""),
            platform=data.get("platform", "番茄小说"),
            words_per_chapter=data.get("words_per_chapter", 3000),
            total_chapters=data.get("total_chapters", 80),
            completed_chapters=data.get("completed_chapters", 0),
            status=data.get("status", "进行中"),
            created_at=data.get("created_at", ""),
            is_inspiration=data.get("is_inspiration", False)
        )


@dataclass
class BookSettings:
    """书籍自定义设定"""
    # 基础设定
    target_audience: str = ""           # 目标读者
    writing_style: str = ""             # 文风（轻松/严肃/悬疑...）
    story_tone: str = ""                # 基调（热血/治愈/暗黑/搞笑...）
    pov: str = "第三人称"               # 叙事视角

    # 内容设定
    main_themes: list = field(default_factory=list)        # 核心主题
    prohibited_content: list = field(default_factory=list) # 禁止内容
    sensitive_topics: list = field(default_factory=list)   # 敏感话题处理

    # 风格设定
    chapter_title_style: str = "章节名"   # 章节标题风格
    include_prologue: bool = True       # 是否有序章
    include_epilogue: bool = True       # 是否有尾声

    # 发布时间设定
    update_schedule: str = ""            # 更新计划
    chapter_release_count: int = 1      # 每次发布章节数

    # 扩展字段（自由添加）
    custom_fields: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "target_audience": self.target_audience,
            "writing_style": self.writing_style,
            "story_tone": self.story_tone,
            "pov": self.pov,
            "main_themes": self.main_themes,
            "prohibited_content": self.prohibited_content,
            "sensitive_topics": self.sensitive_topics,
            "chapter_title_style": self.chapter_title_style,
            "include_prologue": self.include_prologue,
            "include_epilogue": self.include_epilogue,
            "update_schedule": self.update_schedule,
            "chapter_release_count": self.chapter_release_count,
            "custom_fields": self.custom_fields
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'BookSettings':
        return cls(
            target_audience=data.get("target_audience", ""),
            writing_style=data.get("writing_style", ""),
            story_tone=data.get("story_tone", ""),
            pov=data.get("pov", "第三人称"),
            main_themes=data.get("main_themes", []),
            prohibited_content=data.get("prohibited_content", []),
            sensitive_topics=data.get("sensitive_topics", []),
            chapter_title_style=data.get("chapter_title_style", "章节名"),
            include_prologue=data.get("include_prologue", True),
            include_epilogue=data.get("include_epilogue", True),
            update_schedule=data.get("update_schedule", ""),
            chapter_release_count=data.get("chapter_release_count", 1),
            custom_fields=data.get("custom_fields", {})
        )


@dataclass
class ChapterInfo:
    """章节信息"""
    chapter_num: int
    title: str = ""
    status: str = "draft"
    audit_score: int = 0
    audit_passed: bool = False
    finalized: bool = False
    retry_count: int = 0
    last_updated: str = ""
    file_path: str = ""
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "chapter_num": self.chapter_num,
            "title": self.title,
            "status": self.status,
            "audit_score": self.audit_score,
            "audit_passed": self.audit_passed,
            "finalized": self.finalized,
            "retry_count": self.retry_count,
            "last_updated": self.last_updated,
            "file_path": self.file_path,
            "summary": self.summary
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ChapterInfo':
        return cls(
            chapter_num=data.get("chapter_num", 1),
            title=data.get("title", ""),
            status=data.get("status", "draft"),
            audit_score=data.get("audit_score", 0),
            audit_passed=data.get("audit_passed", False),
            finalized=data.get("finalized", False),
            retry_count=data.get("retry_count", 0),
            last_updated=data.get("last_updated", ""),
            file_path=data.get("file_path", ""),
            summary=data.get("summary", "")
        )


@dataclass
class HookInfo:
    """伏笔信息"""
    hook_id: str
    content: str
    hook_type: str = "前台"  # 种子/前台/后台/立即
    status: str = "埋设中"
    set_in_chapter: int = 0
    expected_resolve_chapter: int = 0
    actual_resolve_chapter: int = 0
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "hook_id": self.hook_id,
            "content": self.content,
            "hook_type": self.hook_type,
            "status": self.status,
            "set_in_chapter": self.set_in_chapter,
            "expected_resolve_chapter": self.expected_resolve_chapter,
            "actual_resolve_chapter": self.actual_resolve_chapter,
            "created_at": self.created_at
        }


@dataclass
class AuditResult:
    """审核结果"""
    chapter_num: int
    ai_tell_density: float = 0.0
    paragraph_warnings: int = 0
    audit_issues: int = 0
    hook_resolution_rate: float = 0.0
    chapter_score: int = 0
    decision: str = "通过"
    issues: List[Dict] = field(default_factory=list)
    word_count: int = 0                          # 实际字数
    target_word_count: int = 0                  # 目标字数
    word_count_deviation: int = 0               # 字数误差
    core_issues: List[Dict] = field(default_factory=list)  # 核心漏洞列表

    def calculate_score(self) -> int:
        """计算章节综合得分"""
        score = 100
        score -= self.audit_issues * 5
        score -= self.ai_tell_density * 20
        score -= self.paragraph_warnings * 3
        self.chapter_score = max(0, min(100, score))

        # 核心漏洞必须修订（无论分数多高）
        has_core_issues = len(self.core_issues) > 0
        
        # 字数误差超限必须修订（误差不超过200字）
        word_count_ok = abs(self.word_count_deviation) <= 200 if self.word_count_deviation != 0 else True

        if self.chapter_score >= 75 and not has_core_issues and word_count_ok:
            self.decision = "通过"
        elif has_core_issues:
            self.decision = "核心漏洞需修订"
        elif not word_count_ok:
            self.decision = "字数偏差需修订"
        elif self.chapter_score >= 60:
            self.decision = "修订后通过"
        else:
            self.decision = "不通过"

        return self.chapter_score

    def to_dict(self) -> dict:
        return {
            "chapter_num": self.chapter_num,
            "ai_tell_density": self.ai_tell_density,
            "paragraph_warnings": self.paragraph_warnings,
            "audit_issues": self.audit_issues,
            "hook_resolution_rate": self.hook_resolution_rate,
            "chapter_score": self.chapter_score,
            "decision": self.decision,
            "issues": self.issues,
            "word_count": self.word_count,
            "target_word_count": self.target_word_count,
            "word_count_deviation": self.word_count_deviation,
            "core_issues": self.core_issues
        }


@dataclass
class ChapterAuditLog:
    """章节审计日志条目"""
    chapter_num: int
    action: str                    # write/audit/revise/golden_review
    timestamp: str                  # ISO格式时间
    chapter_status: str            # draft/final/revised
    chapter_score: int = 0
    word_count: int = 0
    target_word_count: int = 0
    word_count_deviation: int = 0
    core_issues: List[Dict] = field(default_factory=list)
    decision: str = ""
    issues: List[Dict] = field(default_factory=list)
    message: str = ""
    revision_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chapter_num": self.chapter_num,
            "action": self.action,
            "timestamp": self.timestamp,
            "chapter_status": self.chapter_status,
            "chapter_score": self.chapter_score,
            "word_count": self.word_count,
            "target_word_count": self.target_word_count,
            "word_count_deviation": self.word_count_deviation,
            "core_issues": self.core_issues,
            "decision": self.decision,
            "issues": self.issues,
            "message": self.message,
            "revision_reasons": self.revision_reasons
        }


@dataclass
class AuditLogTable:
    """章节审计日志表"""
    book_id: str = ""
    book_name: str = ""
    logs: List[ChapterAuditLog] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def add_log(self, log: ChapterAuditLog):
        self.logs.append(log)
        self.updated_at = datetime.now().isoformat()

    def get_chapter_logs(self, chapter_num: int) -> List[ChapterAuditLog]:
        return [log for log in self.logs if log.chapter_num == chapter_num]

    def get_latest_log(self, chapter_num: int) -> Optional[ChapterAuditLog]:
        chapter_logs = self.get_chapter_logs(chapter_num)
        return chapter_logs[-1] if chapter_logs else None

    def to_dict(self) -> dict:
        return {
            "book_id": self.book_id,
            "book_name": self.book_name,
            "logs": [log.to_dict() for log in self.logs],
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuditLogTable":
        logs = [ChapterAuditLog(**log) for log in data.get("logs", [])]
        return cls(
            book_id=data.get("book_id", ""),
            book_name=data.get("book_name", ""),
            logs=logs,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", "")
        )


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    success: bool
    message: str = ""
    data: Optional[Dict] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "error": self.error
        }


@dataclass
class GlobalConfig:
    """全局配置"""
    # 过滤词库
    banned_words: list = field(default_factory=list)        # 屏蔽词
    sensitive_topics: list = field(default_factory=list)    # 敏感话题
    prohibited_content: list = field(default_factory=list)  # 禁止内容

    # 提示词模板
    system_prompt: str = ""                                # 系统级提示词

    # 其他全局设置
    default_words_per_chapter: int = 3000                   # 默认每章字数
    default_temperature: float = 0.7                       # 默认温度

    def to_dict(self) -> dict:
        return {
            "banned_words": self.banned_words,
            "sensitive_topics": self.sensitive_topics,
            "prohibited_content": self.prohibited_content,
            "system_prompt": self.system_prompt,
            "default_words_per_chapter": self.default_words_per_chapter,
            "default_temperature": self.default_temperature
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'GlobalConfig':
        return cls(
            banned_words=data.get("banned_words", []),
            sensitive_topics=data.get("sensitive_topics", []),
            prohibited_content=data.get("prohibited_content", []),
            system_prompt=data.get("system_prompt", ""),
            default_words_per_chapter=data.get("default_words_per_chapter", 3000),
            default_temperature=data.get("default_temperature", 0.7)
        )
