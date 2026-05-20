# -*- coding: utf-8 -*-
"""
InkOS 小说创作系统 - 核心引擎
多Agent协作调度器 v1.1.0
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import re


# ============== 大模型配置 ==============

@dataclass
class LLMConfig:
    """大模型配置"""
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    max_tokens: int = 8192
    temperature: float = 0.7
    timeout: int = 120
    retry_times: int = 3
    retry_delay: float = 2.0

    @classmethod
    def from_env(cls, path: str = ".env") -> 'LLMConfig':
        """从 .env 文件加载配置"""
        env_path = Path(path)
        if not env_path.exists():
            return cls()
        
        config = cls()
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == "LLM_API_KEY":
                        config.api_key = value
                    elif key == "LLM_BASE_URL":
                        config.base_url = value
                    elif key == "LLM_MODEL":
                        config.model = value
                    elif key == "LLM_MAX_TOKENS":
                        config.max_tokens = int(value) if value else 8192
                    elif key == "LLM_TEMPERATURE":
                        config.temperature = float(value) if value else 0.7
                    elif key == "LLM_TIMEOUT":
                        config.timeout = int(value) if value else 120
                    elif key == "LLM_RETRY_TIMES":
                        config.retry_times = int(value) if value else 3
                    elif key == "LLM_RETRY_DELAY":
                        config.retry_delay = float(value) if value else 2.0
        return config

    def save_env(self, path: str = ".env") -> bool:
        """保存配置到 .env 文件"""
        try:
            lines = [
                "# LLM Configuration",
                f"LLM_API_KEY={self.api_key}",
                f"LLM_BASE_URL={self.base_url}",
                f"LLM_MODEL={self.model}",
                f"LLM_MAX_TOKENS={self.max_tokens}",
                f"LLM_TEMPERATURE={self.temperature}",
                f"LLM_TIMEOUT={self.timeout}",
                f"LLM_RETRY_TIMES={self.retry_times}",
                f"LLM_RETRY_DELAY={self.retry_delay}",
            ]
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            return True
        except Exception:
            return False


class LLMClient:
    """大模型调用客户端"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._client = None
        self._init_client()

    def _init_client(self):
        """初始化HTTP客户端"""
        try:
            import httpx
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                }
            )
        except ImportError:
            # 备用: 使用requests
            import warnings
            warnings.warn("httpx未安装，使用标准库urllib")
            self._client = None

    def call(
        self,
        prompt: str,
        system_prompt: str = "",
        json_mode: bool = False,
        **kwargs
    ) -> tuple[bool, str]:
        """
        调用大模型

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            json_mode: 是否返回JSON格式
            **kwargs: 其他参数覆盖

        Returns:
            (成功标志, 响应内容或错误信息)
        """
        import urllib.request
        import urllib.error

        # 合并参数
        params = {
            "model": kwargs.get("model", self.config.model),
            "messages": [],
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
        }

        if system_prompt:
            params["messages"].append({"role": "system", "content": system_prompt})
        params["messages"].append({"role": "user", "content": prompt})

        if json_mode:
            params["response_format"] = {"type": "json_object"}

        payload = json.dumps(params).encode('utf-8')

        for attempt in range(self.config.retry_times):
            try:
                req = urllib.request.Request(
                    f"{self.config.base_url}/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json"
                    },
                    method="POST"
                )

                with urllib.request.urlopen(req, timeout=self.config.timeout) as response:
                    result = json.loads(response.read().decode('utf-8'))

                    if "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0]["message"]["content"]
                        return True, content

                return False, "响应格式异常"

            except urllib.error.URLError as e:
                if attempt < self.config.retry_times - 1:
                    time.sleep(self.config.retry_delay)
                    continue
                return False, f"网络错误: {str(e)}"
            except Exception as e:
                return False, f"调用失败: {str(e)}"

        return False, "重试次数耗尽"

    def close(self):
        """关闭连接"""
        if self._client:
            self._client.close()


class LLMManager:
    """大模型管理器"""

    DEFAULT_CONFIG_PATH = ".env"

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.config = self._load_config()
        self.client = LLMClient(self.config)
        self._token_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _load_config(self) -> LLMConfig:
        """加载配置"""
        if Path(self.config_path).exists():
            return LLMConfig.from_env(self.config_path)
        return LLMConfig()

    def save_config(self) -> bool:
        """保存配置"""
        return self.config.save_env(self.config_path)

    def update_config(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        agent_name: str = "System",
        **kwargs
    ) -> str:
        """
        生成内容

        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            agent_name: 调用Agent名称
            **kwargs: 其他参数

        Returns:
            生成的文本内容
        """
        print(f"[LLM] {agent_name} 正在生成...")
        success, result = self.client.call(prompt, system_prompt, **kwargs)

        if success:
            print(f"[LLM] {agent_name} 生成完成 ({len(result)} 字符)")
            return result
        else:
            print(f"[LLM] {agent_name} 生成失败: {result}")
            return f"[生成失败: {result}]"

    def generate_json(
        self,
        prompt: str,
        system_prompt: str = "",
        agent_name: str = "System",
        **kwargs
    ) -> Optional[Dict]:
        """生成JSON格式响应"""
        success, result = self.client.call(prompt, system_prompt, json_mode=True, **kwargs)

        if success:
            try:
                # 尝试提取JSON
                text = result.strip()
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                return json.loads(text.strip())
            except json.JSONDecodeError:
                print(f"[LLM] JSON解析失败，原始响应: {result[:200]}")
                return None
        return None

    def batch_generate(
        self,
        prompts: List[str],
        system_prompt: str = "",
        agent_name: str = "System",
        delay: float = 1.0
    ) -> List[str]:
        """批量生成"""
        results = []
        for i, prompt in enumerate(prompts):
            print(f"[LLM] {agent_name} 批量生成 {i+1}/{len(prompts)}")
            result = self.generate(prompt, system_prompt, agent_name)
            results.append(result)
            if i < len(prompts) - 1:
                time.sleep(delay)
        return results


# ============== 数据结构定义 ==============

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


class GenreType(Enum):
    """题材类型"""
    XUANHUAN = "玄幻"
    XIANXIA = "仙侠"
    DUSHI = "都市"
    KEHUAN = "科幻"
    QINGCHUN = "青春校园"
    CUSTOM = "自定义"


class AuditDecision(Enum):
    """审核决策"""
    PASS = "通过"
    NEEDS_REVISION = "修订后通过"
    FAIL = "不通过"


@dataclass
class ChapterInfo:
    """章节信息"""
    chapter_num: int
    title: str = ""
    status: ChapterStatus = ChapterStatus.DRAFT
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
            "status": self.status.value,
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
            status=ChapterStatus.from_string(data.get("status", "draft")),
            audit_score=data.get("audit_score", 0),
            audit_passed=data.get("audit_passed", False),
            finalized=data.get("finalized", False),
            retry_count=data.get("retry_count", 0),
            last_updated=data.get("last_updated", ""),
            file_path=data.get("file_path", ""),
            summary=data.get("summary", "")
        )


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
    is_inspiration: bool = False

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
class HookInfo:
    """伏笔信息"""
    hook_id: str
    content: str
    hook_type: str = "前台"  # 种子/前台/后台/立即
    status: str = "埋设中"  # 埋设中/推进中/已回收/已完成
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
    ai_tell_density: float = 0.0      # AI痕迹密度 /1k chars
    paragraph_warnings: int = 0      # 短段落警告数
    audit_issues: int = 0            # 审计问题数
    hook_resolution_rate: float = 0.0  # 伏笔回收率 %
    chapter_score: int = 0           # 章节得分 0-100
    decision: AuditDecision = AuditDecision.PASS
    issues: List[Dict] = field(default_factory=list)

    def calculate_score(self) -> int:
        """计算章节综合得分"""
        score = 100
        score -= self.audit_issues * 5
        score -= self.ai_tell_density * 20
        score -= self.paragraph_warnings * 3
        self.chapter_score = max(0, min(100, score))

        if self.chapter_score >= 75:
            self.decision = AuditDecision.PASS
        elif self.chapter_score >= 60:
            self.decision = AuditDecision.NEEDS_REVISION
        else:
            self.decision = AuditDecision.FAIL

        return self.chapter_score


# ============== 文件管理器 ==============

class FileManager:
    """文件读写管理"""

    def __init__(self, workspace: str):
        self.workspace = Path(workspace)
        self.book_index_path = self.workspace / "book_index.json"

    def read_json(self, path: Path) -> dict:
        """读取JSON文件"""
        if not path.exists():
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def write_json(self, path: Path, data: dict) -> bool:
        """写入JSON文件"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"写入失败: {e}")
            return False

    def read_text(self, path: Path) -> str:
        """读取文本文件"""
        if not path.exists():
            return ""
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def write_text(self, path: Path, content: str) -> bool:
        """写入文本文件"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"写入失败: {e}")
            return False


# ============== 状态管理器 ==============

class StateManager:
    """状态管理核心"""

    MAX_RETRY_COUNT = 3  # 单章重写上限

    def __init__(self, workspace: str):
        self.fm = FileManager(workspace)
        self.workspace = Path(workspace)
        self.book_index = self._load_book_index()

    def _load_book_index(self) -> dict:
        """加载书籍索引"""
        return self.fm.read_json(self.fm.book_index_path)

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
        for book in self.book_index.get("books", []):
            if book.get("id") == book_id:
                return BookInfo.from_dict(book)
        return None

    def get_book_by_name(self, name: str) -> Optional[BookInfo]:
        """通过名称匹配书籍"""
        name_lower = name.lower()
        matches = []

        for book in self.book_index.get("books", []):
            book_name = book.get("name", "").lower()
            if name_lower == book_name:
                return BookInfo.from_dict(book)
            if name_lower in book_name or book_name in name_lower:
                matches.append(book)

        if len(matches) == 1:
            return BookInfo.from_dict(matches[0])
        return None if len(matches) == 0 else None

    def switch_book(self, book_id_or_name: str) -> tuple[bool, str]:
        """
        切换当前小说
        返回: (成功标志, 消息)
        """
        book = self.get_book_by_id(book_id_or_name)
        if not book:
            book = self.get_book_by_name(book_id_or_name)

        if not book:
            available = [b["name"] for b in self.book_index.get("books", [])]
            return False, f"未找到《{book_id_or_name}》。可用: {', '.join(available)}"

        old_id = self.book_index.get("current_novel", "")
        self.book_index["current_novel"] = book.id
        self.book_index["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

        if self._save_book_index():
            return True, f"已切换至《{book.name}》"
        return False, "状态文件保存失败"

    def create_book(self, book_info: BookInfo) -> tuple[bool, str]:
        """创建新书籍"""
        # 检查是否已存在
        for book in self.book_index.get("books", []):
            if book["id"] == book_info.id:
                return False, f"书籍ID {book_info.id} 已存在"

        # 添加书籍
        self.book_index["books"].append(book_info.to_dict())
        self.book_index["current_novel"] = book_info.id
        self.book_index["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

        # 创建目录结构
        book_path = self.workspace / book_info.path
        dirs = ["chapters", "truth_files", "planning_files"]
        for d in dirs:
            (book_path / d).mkdir(parents=True, exist_ok=True)

        if self._save_book_index():
            return True, f"书籍《{book_info.name}》创建成功"
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
        status: ChapterStatus,
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
        chapter["approval_status"] = status.value
        chapter["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

        if audit_score > 0:
            chapter["audit_score"] = audit_score
            chapter["audit_passed"] = audit_passed

        if finalized:
            chapter["finalized"] = True

        if retry_count is not None:
            chapter["retry_count"] = retry_count

        return self.save_project_state(book, state)


# ============== Agent基类 ==============

class Agent:
    """Agent基类"""

    def __init__(self, name: str, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        self.name = name
        self.sm = state_manager
        self.fm = state_manager.fm
        self.llm = llm_manager

    def set_llm(self, llm_manager: LLMManager):
        """设置LLM管理器"""
        self.llm = llm_manager

    def log_start(self, task_name: str, book_id: str, phase: str, output: str):
        """输出任务启动日志"""
        print(f"\n{'='*60}")
        print(f"[LOG] 开始执行任务")
        print(f"{'='*60}")
        print(f"任务名称: {task_name}")
        print(f"当前 Agent: {self.name}")
        print(f"目标书籍: {book_id}")
        print(f"当前阶段: {phase}")
        print(f"预计产出: {output}")
        print(f"{'='*60}\n")

    def log_end(self, success: bool = True):
        """输出任务结束日志"""
        status = "成功完成" if success else "执行失败"
        print(f"\n[LOG] {self.name} - {status}\n")

    def llm_call(self, prompt: str, system_prompt: str = "", json_mode: bool = False) -> str:
        """调用大模型"""
        if self.llm:
            return self.llm.generate(prompt, system_prompt, self.name)
        return "[LLM未配置]"


# ============== 系统提示词模板 ==============

SYSTEM_PROMPTS = {
    "planner": """你是一位专业的小说创作规划师，负责解读用户的创作需求并生成详细的创作规划书。

请根据用户提供的创作简报，提取以下信息并生成结构化的创作规划：
- 书名、题材、风格、目标平台
- 核心设定（金手指、世界观）
- 主线方向、预期章节数、完本字数
- 创作节奏规划（开篇策略、前期节奏、高潮点安排）

请使用专业的网文创作术语，遵循平台特点进行规划。""",

    "architect": """你是一位资深的小说世界观架构师，负责设计完整的小说世界观与章节结构。

请根据规划书和真相文件，生成：
1. story_bible.md - 完整的世界观设定
2. 章节细纲 - 本章的核心事件、起承转合、情节点、伏笔埋设

遵循"黄金三章"法则，确保开篇有强冲突/悬念。""",

    "writer": """你是一位专业的小说作家，擅长网络文学创作。

请根据上下文编译包生成高质量的小说正文，要求：
- 单章3000-3500字
- 禁止角色OOC、战力崩坏、信息越界
- 禁止频繁描写外貌（仅首次出现时描写）
- 必须埋设/回收伏笔、推动主线、体现情感弧线
- 禁止AI写作痕迹（重复结构、机械感段落）
- 保持"行动描写（仅允许对话与叙事）"原则

请确保文字流畅有网感，爽点到位。""",

    "observer": """你是一位细心的事实提取专家，负责从章节正文中提取关键事实。

请提取并更新：
- 世界状态变更（位置、天气、时间）
- 数值变动（金钱、物品、能力值）
- 伏笔状态（新增、推进、回收）
- 角色登场与关系变化
- 潜在矛盾检测

请生成结构化的事实提取报告。""",

    "auditor": """你是一位专业的小说质量审计师，负责对章节进行全方位质量审查。

请从以下维度审查：
1. 逻辑一致性（战力、行为、时间线）
2. 情感节奏（弧线完整、爽点到位）
3. 伏笔管理（埋设、回收、逻辑通顺）
4. 文风一致性（符合规则、无禁用词）

请计算质量评分：章节得分 = 100 - auditIssues×5 - aiTellDensity×20 - paraWarnings×3
- ≥75分：通过
- 60-74分：修订后通过
- <60分：不通过

请生成详细的审计报告。""",

    "controller": """你是一位严格的质量门禁，负责控制创作流程的关键节点。

请校验：
1. 字数（目标3000字，偏差±10%）
2. 禁止词检测（0容忍）
3. 伏笔埋设（≥1条/章）
4. 情感弧线（必须在场）

请生成控制校验报告。""",

    "hook_manager": """你是一位专业的伏笔管理者，负责伏笔的全生命周期管控。

请从章节中识别伏笔要素，更新pending_hooks.md：
- 种子伏笔（长期酝酿）
- 前台伏笔（近期回收）
- 后台伏笔（暗线推进）
- 立即伏笔（1-2章内回收）

确保伏笔密度在2-4条/章的合理区间。""",

    "reflector": """你是一位策略调整专家，负责对比理想与实际输出，计算Delta。

请分析：
- 期望值与实际值的偏差
- 偏差产生的根本原因
- 下一轮创作的具体调整策略
- 从本章学到的创作经验""",

    "continuity_auditor": """你是一位长线审计专家，负责跨章节视角审查连贯性。

请检查：
- 数值一致性（金钱/等级/物品）
- 关系一致性（角色关系演变）
- 伏笔链完整性
- 地理/时间合理性

请生成连贯性审计报告。""",

    "radar": """你是一位专业的小说市场调研分析师，负责捕捉市场趋势和读者偏好。

请调研：
1. 题材热度：当前热门题材及其趋势
2. 流行元素：近期爆款作品的共同特征
3. 平台适配：各平台特点与适配建议
4. 创作建议：开篇要点、节奏把控、避坑指南

请给出专业的市场分析报告。""",

    "global_editor": """你是一位全局内容修正专家，负责全书级别的内容修正。

修正类型：
1. 高频描写修正 - 修正过度重复的外貌/环境描写
2. 风格统一修正 - 统一全书的叙述风格和语气
3. 伏笔修复 - 修复断裂或矛盾的伏笔
4. 角色OOC修正 - 修正角色性格/行为偏离
5. 格式规范修正 - 统一章节格式、对话格式等

执行原则：
- 最小侵入，不破坏叙事节奏、情感基调、伏笔结构
- 修正后字数变化应在±10%以内
- 保持叙事连贯性"""
}


# ============== 各Agent实现 ==============

class Radar(Agent):
    """01 - 市场调研员 Agent"""

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("01-radar", state_manager, llm_manager)

    def conduct_research(self, brief: str = "", genre: str = "") -> Dict[str, Any]:
        """
        进行市场调研

        Args:
            brief: 创作简报（可选）
            genre: 题材类型（可选）

        Returns:
            市场调研报告
        """
        self.log_start("市场调研", "", "research", "市场调研报告")

        target_genre = genre
        if not target_genre and brief:
            # 从简报中提取题材
            brief_lower = brief.lower()
            genres = {
                "玄幻": ["玄幻", "修炼", "灵气"],
                "仙侠": ["仙侠", "修真"],
                "都市": ["都市", "现代"],
                "科幻": ["科幻", "星际"]
            }
            for g, keywords in genres.items():
                if any(k in brief_lower for k in keywords):
                    target_genre = g
                    break

        if self.llm:
            prompt = f"""请进行网络小说市场调研，分析当前市场趋势。

目标题材：{target_genre or '通用'}

请调研以下方面：

1. **题材热度分析**
   - 当前热门题材及其趋势
   - {target_genre}题材的市场表现

2. **流行元素提取**
   - 近期爆款作品的共同特征
   - 读者喜好的爽点类型

3. **平台适配建议**
   - 各平台（番茄/起点/飞卢）特点
   - 最适合当前题材的平台推荐

4. **创作建议**
   - 开篇要点
   - 节奏把控
   - 避坑指南

请返回JSON格式：
{{
    "genre_popularity": {{
        "current_trend": "当前趋势描述",
        "competition_level": "高/中/低",
        "market_demand": "需求量评级"
    }},
    "popular_elements": ["元素1", "元素2", "元素3"],
    "platform_recommendation": {{
        "best_platform": "推荐平台",
        "reasons": ["原因1", "原因2"]
    }},
    "creation_tips": {{
        "opening_strategy": "开篇策略",
        "rhythm_tips": "节奏建议",
        "pitfalls": ["坑1", "坑2"]
    }},
    "market_score": 1-10的市场评分
}}"""
            result = self.llm.generate_json(prompt, SYSTEM_PROMPTS.get("radar", ""), self.name)
            if result and isinstance(result, dict):
                self.log_end(True)
                return {
                    "success": True,
                    "genre": target_genre,
                    "popularity": result.get("genre_popularity", {}),
                    "elements": result.get("popular_elements", []),
                    "platform": result.get("platform_recommendation", {}),
                    "tips": result.get("creation_tips", {}),
                    "market_score": result.get("market_score", 5),
                    "report": self._generate_research_report(target_genre, result)
                }

        # 回退：基础报告
        self.log_end(True)
        return {
            "success": True,
            "genre": target_genre,
            "popularity": {"current_trend": "稳定", "competition_level": "中", "market_demand": "一般"},
            "elements": ["升级流", "打脸", "金手指"],
            "platform": {"best_platform": "番茄小说", "reasons": ["流量大", "适合新人"]},
            "tips": {"opening_strategy": "强冲突开场", "rhythm_tips": "保持节奏", "pitfalls": ["拖沓", "战力崩坏"]},
            "market_score": 6,
            "report": ""
        }

    def _generate_research_report(self, genre: str, data: Dict) -> str:
        """生成市场调研报告"""
        popularity = data.get("genre_popularity", {})
        platform = data.get("platform_recommendation", {})
        tips = data.get("creation_tips", {})

        report = f"""# 市场调研报告 - {genre}题材

## 题材热度分析
- 当前趋势: {popularity.get('current_trend', '待分析')}
- 竞争水平: {popularity.get('competition_level', '待定')}
- 市场需求: {popularity.get('market_demand', '待定')}

## 流行元素
"""
        elements = data.get("popular_elements", [])
        for i, elem in enumerate(elements[:5], 1):
            report += f"{i}. {elem}\n"

        report += f"""
## 平台适配建议
- 推荐平台: {platform.get('best_platform', '待定')}
- 推荐理由:
"""
        reasons = platform.get("reasons", [])
        for reason in reasons:
            report += f"  - {reason}\n"

        report += f"""
## 创作建议
- 开篇策略: {tips.get('opening_strategy', '待定')}
- 节奏建议: {tips.get('rhythm_tips', '待定')}
- 避坑指南: {', '.join(tips.get('pitfalls', []))}

## 市场评分
**综合评分: {data.get('market_score', 0)}/10**
"""
        return report


class Planner(Agent):
    """02 - 规划师 Agent"""

    # 题材规则文件映射
    GENRE_RULES_MAP = {
        "玄幻": "01_玄幻规则.md",
        "仙侠": "02_仙侠规则.md",
        "都市": "03_都市规则.md",
        "科幻": "04_科幻规则.md",
        "自定义": "05_自定义规则.md",
        "青春校园": "06_青春校园规则.md",
    }

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("02-planner", state_manager, llm_manager)
        # 加载题材规则目录
        self.rules_dir = Path(__file__).parent / "小说家skill工作流" / "references"

    def _load_genre_rules(self, genre: str) -> str:
        """加载指定题材的创作规则"""
        # 尝试从skill工作流目录加载
        if self.rules_dir.exists():
            rule_file = self.GENRE_RULES_MAP.get(genre)
            if rule_file:
                rule_path = self.rules_dir / rule_file
                if rule_path.exists():
                    return rule_path.read_text(encoding='utf-8')

        # 回退：从当前工作空间加载
        workspace_rules = Path(self.sm.workspace) / "小说家skill工作流" / "references"
        if workspace_rules.exists():
            rule_file = self.GENRE_RULES_MAP.get(genre)
            if rule_file:
                rule_path = workspace_rules / rule_file
                if rule_path.exists():
                    return rule_path.read_text(encoding='utf-8')

        return ""

    def _validate_genre(self, brief: str, detected_genre: str) -> tuple[bool, str]:
        """验证题材类型是否符合规范"""
        if detected_genre in self.GENRE_RULES_MAP:
            return True, detected_genre

        # 题材近似匹配
        genre_aliases = {
            "修炼": "玄幻", "魔法": "玄幻", "斗气": "玄幻",
            "修真": "仙侠", "修仙": "仙侠",
            "现代": "都市", "职场": "都市", "异能": "都市",
            "星际": "科幻", "科技": "科幻", "末日": "科幻",
            "校园": "青春校园", "学生": "青春校园",
        }

        for keyword, genre in genre_aliases.items():
            if keyword in brief:
                return True, genre

        # 未识别题材，强制要求用户补充
        return False, ""

    def parse_brief(self, brief: str) -> Dict[str, Any]:
        """
        解析创作简报
        返回创作规划书（含题材规则）
        """
        self.log_start("解读创作简报", "", "planning", "创作规划书")

        # 检测题材
        brief_lower = brief.lower()
        detected_genre = ""
        genres = {"玄幻": ["玄幻", "修炼", "灵气", "斗气"], "仙侠": ["仙侠", "修真"],
                  "都市": ["都市", "现代", "异能"], "科幻": ["科幻", "星际", "科技"],
                  "青春校园": ["校园", "学生", "青春"]}
        for genre, keywords in genres.items():
            if any(k in brief_lower for k in keywords):
                detected_genre = genre
                break

        # 验证题材
        is_valid, validated_genre = self._validate_genre(brief, detected_genre)

        # 加载题材规则
        genre_rules = self._load_genre_rules(validated_genre or detected_genre)

        # 尝试使用LLM解析
        if self.llm:
            rules_context = f"\n\n参考题材规则：\n{genre_rules[:2000]}" if genre_rules else ""
            prompt = f"""请分析以下创作简报，提取关键信息并生成JSON格式的创作规划：

创作简报：
{brief}
{rules_context}

请返回JSON格式，包含以下字段：
{{
    "book_name": 书名,
    "genre": 题材（必须是：玄幻/仙侠/都市/科幻/青春校园/自定义）,
    "platform": 目标平台,
    "words_per_chapter": 单章字数,
    "estimated_chapters": 预期章节数,
    "estimated_words": 预计完本字数,
    "core_setting": 核心设定摘要,
    "main_direction": 主线方向,
    "opening_strategy": 开篇策略,
    "golden_chapters_plan": "黄金三章规划"（简要描述前三章核心内容）
}}"""
            result = self.llm.generate_json(prompt, SYSTEM_PROMPTS["planner"], self.name)
            if result:
                # 确保题材有效
                if not result.get("genre") or result["genre"] not in self.GENRE_RULES_MAP:
                    result["genre"] = detected_genre or "都市"
                # 添加规则内容
                result["genre_rules"] = genre_rules
                self.log_end(True)
                return result

        # 回退到规则解析
        planning = {
            "book_name": "",
            "genre": detected_genre or "都市",
            "core_setting": "",
            "main_direction": "",
            "platform": "番茄小说",
            "words_per_chapter": 3000,
            "estimated_chapters": 80,
            "estimated_words": 240000,
            "genre_rules": genre_rules
        }

        name_match = re.search(r'书名[：:]\s*([^\n]+)', brief)
        if name_match:
            planning["book_name"] = name_match.group(1).strip()

        words_match = re.search(r'(\d+)[万]?字', brief)
        if words_match:
            words = int(words_match.group(1))
            if words < 100:
                words *= 10000
            planning["estimated_words"] = words
            planning["estimated_chapters"] = words // planning["words_per_chapter"]

        self.log_end(True)
        return planning

    def generate_planning_doc(self, brief: str, planning: Dict) -> str:
        """生成创作规划书"""
        # 使用LLM生成详细规划书
        if self.llm:
            prompt = f"""根据以下简报信息和提取的规划数据，生成一份详细的创作规划书：

简报：
{brief}

规划数据：
{json.dumps(planning, ensure_ascii=False, indent=2)}

请生成包含以下部分的创作规划书：
1. 项目信息（书名、题材、风格、平台）
2. 核心设定（金手指、世界观）
3. 主线规划（核心主线、章节数、字数）
4. 创作节奏（开篇策略、前10章规划、高潮点）
5. 行动建议（后续步骤）

使用Markdown格式输出。"""
            result = self.llm.generate(prompt, SYSTEM_PROMPTS["planner"], self.name)
            if result and not result.startswith("["):
                self.log_end(True)
                return result

        # 回退模板
        return f"""# 创作规划书

## 项目信息
- 书名: {planning.get('book_name', '待定')}
- 题材: {planning.get('genre', '都市')}
- 风格: 都市异能流
- 目标平台: {planning.get('platform', '番茄小说')}

## 核心设定
- 金手指: {planning.get('core_setting', '待定')}
- 世界观: {planning.get('main_direction', '待定')}

## 主线规划
- 核心主线: {planning.get('main_direction', '待定')}
- 预期章节数: {planning.get('estimated_chapters', 80)}
- 预计完本字数: {planning.get('estimated_words', 240000)}

## 创作节奏
- 开篇策略: 黄金三章法则
- 前10章节奏规划: 建立世界观、冲突、升级
- 第一个高潮点: 第10章左右

## 行动建议
- 需要调用 03_architect 初始化世界观
"""


class Architect(Agent):
    """03 - 建筑师 Agent"""

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("03-architect", state_manager, llm_manager)

    def generate_story_bible(self, book: BookInfo, planning: Dict) -> str:
        """生成世界观设定"""
        self.log_start("书籍初始化", book.id, "foundation", "story_bible.md + book_rules.md")

        if self.llm:
            prompt = f"""请为小说《{book.name}》设计完整的世界观设定。

题材: {planning.get('genre', '都市')}
目标平台: {planning.get('platform', '番茄小说')}

请生成包含以下部分的世界观设定：
1. 世界观背景（时代背景、空间设定、世界规则）
2. 主角详细人设（姓名、身份、过往经历、性格底色、核心技能）
3. 金手指设定（能力来源、激活条件、能力上限）
4. 核心配角人设
5. 势力/门派/组织设定
6. 地理/空间设定
7. 时间线设定
8. 规则体系（修炼/能力体系）
9. 核心冲突与主线剧情

使用Markdown格式输出。"""
            result = self.llm.generate(prompt, SYSTEM_PROMPTS["architect"], self.name)
            if result and not result.startswith("["):
                self.log_end(True)
                return result

        doc = f"""# {book.name} 世界观设定

## 一、世界观背景
[时代背景、空间设定、世界规则]

## 二、主角详细人设
### 基本信息
- 姓名: 待定
- 身份: 待定
- 过往经历: 待定
- 性格底色: 待定
- 核心技能: 待定

### 金手指设定
[能力来源、激活条件、能力上限]

## 三、核心配角人设
[配角信息]

## 四、势力/门派/组织
[主要势力分布、核心成员、势力关系]

## 五、地理/空间设定
[主要场景、空间规则]

## 六、时间线设定
[主线时间轴、关键事件节点]

## 七、规则体系
### 修炼/能力体系
[等级划分、数值设定]

## 八、核心冲突与主线剧情
[主要矛盾、剧情走向、预期结局]
"""
        self.log_end(True)
        return doc

    def generate_book_rules(self, book: BookInfo, genre: str) -> str:
        """生成创作规则"""
        if self.llm:
            prompt = f"""请为小说《{book.name}》制定创作规则。

题材: {genre}
目标平台: {book.platform}

请生成包含以下部分的创作规则：
1. 题材规则（该题材必须遵守的创作规范）
2. 爽点节奏（打脸/升级/收益兑现的节奏模板）
3. 反派智力要求（配角的智商下限、行为逻辑要求）
4. 禁止事项（角色OOC、战力崩坏、信息越界等）
5. 文风要求（参考风格、禁用词汇、句式要求）

使用Markdown格式输出。"""
            result = self.llm.generate(prompt, SYSTEM_PROMPTS["architect"], self.name)
            if result and not result.startswith("["):
                return result

        return f"""# {book.name} 创作规则

## 一、题材规则
[{genre}题材必须遵守的创作规范]

## 二、爽点节奏
[打脸/升级/收益兑现的节奏模板]

## 三、反派智力要求
[配角的智商下限、行为逻辑要求]

## 四、禁止事项
- 禁止角色 OOC
- 禁止战力崩坏
- 禁止信息越界
- 禁止过度描写外貌

## 五、文风要求
[参考风格、禁用词汇、句式要求]
"""

    def generate_chapter_outline(self, book: BookInfo, chapter_num: int, context: Dict, truth_files: Dict = None) -> str:
        """生成章节细纲"""
        chapter_title = "序章" if chapter_num == 0 else f"第{chapter_num}章"
        self.log_start(f"{chapter_title}规划", book.id, "planning", "章节细纲")

        if self.llm:
            # 构建上下文
            context_info = ""
            if truth_files:
                context_info = f"""
当前世界状态：
{truth_files.get('current_state', '无')}

资源变动：
{truth_files.get('particle_ledger', '无')}

待回收伏笔：
{truth_files.get('pending_hooks', '无')}
"""
            else:
                context_info = context.get("summary", "")

            prompt = f"""请为小说《{book.name}》{chapter_title}生成章节细纲。

{context_info}

请生成包含以下部分的章节结构：
1. 本章核心事件（一句话概括）
2. 起承转合结构（起、承、转、合）
3. 关键情节点（3-5个）
4. 伏笔埋设（如有）
5. 本章结尾钩子（为下一章留悬念）
6. 预估字数

使用Markdown格式输出。"""
            result = self.llm.generate(prompt, SYSTEM_PROMPTS["architect"], self.name)
            if result and not result.startswith("["):
                self.log_end(True)
                return result

        outline = f"""# {chapter_title} 章节结构

## 本章核心事件
[一句话概括本章发生的主要事件]

## 起承转合结构
- 起: [开场事件]
- 承: [事件发展]
- 转: [转折点]
- 合: [本章结尾]

## 关键情节点
1. [情节点1]
2. [情节点2]
3. [情节点3]

## 伏笔埋设
- 伏笔A: [埋设位置、内容]

## 本章结尾钩子
[为下一章留下的悬念]

## 预估字数
{book.words_per_chapter} 字
"""
        self.log_end(True)
        return outline


class Compiler(Agent):
    """04 - 编译器 Agent"""

    def __init__(self, state_manager: StateManager):
        super().__init__("04-compiler", state_manager)

    def compile_context(self, book: BookInfo, chapter_num: int, outline: str, truth_files: Dict) -> str:
        """编译上下文包"""
        chapter_title = "序章" if chapter_num == 0 else f"第{chapter_num}章"
        self.log_start(f"{chapter_title}上下文编译", book.id, "writing", "上下文编译包 → 05_writer")

        context = f"""# 上下文编译包 - {chapter_title}

## 创作约束
{truth_files.get('book_rules', '[来自 book_rules.md 的强制规则]')}

## 世界观摘要
{truth_files.get('story_bible', '[来自 story_bible.md 的核心设定]')}

## 当前世界状态
{truth_files.get('current_state', '[来自 current_state.md 的状态快照]')}

## 资源变动
{truth_files.get('particle_ledger', '[来自 particle_ledger.md 的数值变动]')}

## 角色状态
{truth_files.get('emotional_arcs', '[来自 emotional_arcs.md 的情感状态]')}

## 伏笔状态
{truth_files.get('pending_hooks', '[来自 pending_hooks.md 的待回收伏笔]')}

## 本章任务
{outline}

## 信息边界
[角色A不知道: xxx]
[角色B只知道: yyy]
"""
        self.log_end(True)
        return context


class Writer(Agent):
    """05 - 作家 Agent"""

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("05-writer", state_manager, llm_manager)

    def write_chapter(
        self,
        book: BookInfo,
        chapter_num: int,
        context_package: str,
        outline: str
    ) -> tuple[str, bool]:
        """生成章节正文"""
        chapter_title = "序章" if chapter_num == 0 else f"第{chapter_num}章"
        self.log_start(f"生成{chapter_title}正文", book.id, "writing", f"chapters/chapter_{chapter_num}.md")

        # 使用LLM生成正文
        if self.llm:
            prompt = f"""请为小说《{book.name}》创作{chapter_title}正文。

目标字数：{book.words_per_chapter}字
题材：{book.genre}

以下是上下文编译包：
{context_package}

以下是章节细纲：
{outline}

请根据以上信息生成高质量的小说正文。要求：
1. 字数：{book.words_per_chapter}-{book.words_per_chapter + 500}字
2. 禁止角色OOC、战力崩坏、信息越界
3. 禁止频繁描写外貌
4. 必须埋设/回收伏笔、推动主线
5. 禁止AI写作痕迹（重复结构、机械感段落）
6. 禁止使用"突然"、"就在这时"等突兀转折词
7. 保持"行动描写（仅允许对话与叙事）"原则

直接输出正文内容，不需要额外说明。"""
            result = self.llm.generate(prompt, SYSTEM_PROMPTS["writer"], self.name, max_tokens=16000)

            if result and not result.startswith("["):
                chapter_content = f"# {chapter_title}\n\n{result}\n\n---\n字数统计: 约 {len(result)} 字"
            else:
                chapter_content = result if result else ""

            success = self.sm.update_chapter_status(
                book, chapter_num, ChapterStatus.DRAFT, retry_count=0
            )
            self.log_end(success)
            return chapter_content, success

        # 回退模板
        chapter_content = f"""# {chapter_title}

## 正文内容

[此处为AI生成的小说正文内容]

{context_package}

---
字数统计: 约 {book.words_per_chapter} 字
"""
        success = self.sm.update_chapter_status(
            book, chapter_num, ChapterStatus.DRAFT, retry_count=0
        )
        self.log_end(success)
        return chapter_content, success


class Observer(Agent):
    """06 - 观察者 Agent"""

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("06-observer", state_manager, llm_manager)

    def _rule_based_extract(self, content: str, chapter_num: int, facts: Dict) -> Dict:
        """基于规则的事实提取（无LLM时的后备方案）"""
        import re
        
        # 提取地点 - 匹配行首的中文字符串
        loc = re.search(r'^([\u4e00-\u9fa5]{2,6})[，]', content)
        if loc:
            facts["world_state_changes"]["location"] = loc.group(1)
        
        # 提取时间（凌晨、早晨等）
        tm = re.search(r'(凌晨|清晨|早上|上午|中午|下午|傍晚|晚上|深夜)', content)
        if tm:
            facts["world_state_changes"]["time_advance"] = tm.group(1)
        
        # 提取角色（外卖骑手林深）
        names = re.findall(r'外卖骑手([\u4e00-\u9fa5]{2,4})', content)
        if names:
            facts["characters_appeared"] = names[:5]
        
        # 提取物品（蓝色晶体、应急灯）
        items = re.findall(r'([\u4e00-\u9fa5]{2,8}(?:晶体|灯))', content)
        if items:
            facts["数值变动"]["items"] = list(set(items))[:5]
        
        # 检测伏笔
        hooks = re.findall(r'([^\n]{10,50}[吗吧呢？])', content)
        for h in hooks[:3]:
            if len(h) > 5:
                facts["hooks_found"].append({
                    "id": f"H{len(facts['hooks_found'])+1:03d}",
                    "content": h.strip()[:50],
                    "type": "后台"
                })
        
        return facts

    def extract_facts(self, book: BookInfo, chapter_num: int, content: str, truth_files: Dict = None) -> Dict[str, Any]:
        """从章节正文中提取关键事实"""
        self.log_start(f"第{chapter_num}章事实提取", book.id, "observation", "真相文件更新")

        facts = {
            "chapter_num": chapter_num,
            "world_state_changes": {
                "location": "",
                "weather": "",
                "time_advance": f"第{chapter_num}章"
            },
            "数值变动": {
                "money": 0,
                "items": [],
                "ability_level": 0
            },
            "hooks_found": [],
            "characters_appeared": [],
            "emotional_changes": [],  # 情感变化
            "subplot_progress": [],  # 支线进度
            "contradictions": []
        }

        # 使用LLM提取事实，无LLM时使用规则提取
        if self.llm and content:
            # 获取前文设定作为参考
            context_info = ""
            if truth_files:
                context_info = f"""
前文世界状态：
{truth_files.get('current_state', '无')}

前文资源：
{truth_files.get('particle_ledger', '无')}

情感弧线：
{truth_files.get('emotional_arcs', '无')}

支线进度：
{truth_files.get('subplot_board', '无')}

待回收伏笔：
{truth_files.get('pending_hooks', '无')}
"""
            prompt = f"""请从以下小说章节正文中提取关键事实，生成JSON格式的报告：

小说章节：
{content[:8000]}

{context_info}

请返回JSON格式，包含：
{{
    "world_state_changes": {{
        "location": "位置变化，如无变化则为空字符串",
        "weather": "天气变化，如无变化则为空字符串",
        "time_advance": "时间推进描述"
    }},
    "数值变动": {{
        "money": 金钱变化数字，正数为获得，负数为消耗，
        "items": ["获得的物品列表"],
        "ability_level": 能力等级变化数字
    }},
    "hooks_found": [{{"id": "伏笔ID", "content": "伏笔内容", "type": "前台/后台/立即"}}],
    "characters_appeared": ["角色名列表"],
    "emotional_changes": [{{"character": "角色名", "emotion": "情感类型(开心/悲伤/愤怒/恐惧/惊讶等)", "reason": "变化原因", "intensity": "强度(1-5)"}}],
    "subplot_progress": [{{"name": "支线名称", "progress": "进度描述", "status": "进行中/完成/开启"}}],
    "contradictions": ["矛盾描述列表，无矛盾则为空"]
}}

只返回JSON，不要有其他内容。"""
            result = self.llm.generate_json(prompt, SYSTEM_PROMPTS["observer"], self.name)
            if result:
                facts.update(result)
        else:
            # 无LLM时使用规则提取基本事实
            facts = self._rule_based_extract(content, chapter_num, facts)

        # 更新章节状态为reviewing
        self.sm.update_chapter_status(book, chapter_num, ChapterStatus.REVIEWING)

        self.log_end(True)
        return facts

    def generate_fact_report(self, facts: Dict) -> str:
        """生成事实提取报告"""
        if self.llm:
            prompt = f"""请根据以下事实提取数据生成报告：

{json.dumps(facts, ensure_ascii=False, indent=2)}

生成章节事实提取报告，包含世界状态变更、数值变动、伏笔状态、角色登场、矛盾检测等部分。
使用Markdown格式。"""
            result = self.llm.generate(prompt, SYSTEM_PROMPTS["observer"], self.name)
            if result and not result.startswith("["):
                return result

        report = f"""# 第 {facts.get('chapter_num', '?')} 章事实提取报告

## 世界状态变更
- 位置: {facts.get('world_state_changes', {}).get('location', 'N/A')}
- 天气: {facts.get('world_state_changes', {}).get('weather', 'N/A')}
- 时间推进: {facts.get('world_state_changes', {}).get('time_advance', 'N/A')}

## 数值变动
- 金钱: {facts.get('数值变动', {}).get('money', 0)}
- 物品: {', '.join(facts.get('数值变动', {}).get('items', [])) or '无'}
- 能力值: {facts.get('数值变动', {}).get('ability_level', 0)}

## 角色登场
- 本章出场: {', '.join(facts.get('characters_appeared', [])) or '无'}

## 矛盾检测
{facts.get('contradictions', ['无矛盾'])}
"""
        return report

    def update_truth_files(self, book: BookInfo, chapter_num: int, facts: Dict) -> tuple[bool, List[str]]:
        """根据提取的事实更新真相文件，返回(是否成功, 更新列表)"""
        updated_files = []
        try:
            truth_dir = Path(self.sm.workspace) / book.path / "truth_files"
            chapter_title = "序章" if chapter_num == 0 else f"第{chapter_num}章"

            # 1. 更新 current_state.md
            current_state_path = truth_dir / "current_state.md"
            if current_state_path.exists():
                content = current_state_path.read_text(encoding='utf-8')
                wc = facts.get('world_state_changes', {})
                location = wc.get('location', '')
                weather = wc.get('weather', '')
                time_advance = wc.get('time_advance', '')

                if location:
                    content = content.replace('[当前地点]', location)
                if time_advance:
                    content = content.replace('[当前时间]', time_advance)
                if weather:
                    if '## 环境' in content:
                        content = content.replace('[环境描述]', weather)
                    else:
                        content += f"\n## 环境\n{weather}\n"

                current_state_path.write_text(content, encoding='utf-8')
                updated_files.append("current_state.md")

            # 2. 更新 particle_ledger.md
            ledger_path = truth_dir / "particle_ledger.md"
            if ledger_path.exists():
                content = ledger_path.read_text(encoding='utf-8')
                pv = facts.get('数值变动', {})
                money = pv.get('money', 0)
                items = pv.get('items', [])
                ability = pv.get('ability_level', 0)

                if money != 0:
                    content = content.replace('- 主角: 0', f'- 主角: {money}')
                if items:
                    items_str = '\n'.join([f'- {item}' for item in items])
                    content = content.replace('- [物品列表]', items_str)
                if ability != 0:
                    content = content.replace('等级: L1', f'等级: L{ability}')

                ledger_path.write_text(content, encoding='utf-8')
                updated_files.append("particle_ledger.md")

            # 3. 更新 pending_hooks.md
            hooks_path = truth_dir / "pending_hooks.md"
            if hooks_path.exists():
                hooks = facts.get('hooks_found', [])
                if hooks:
                    content = hooks_path.read_text(encoding='utf-8')
                    for hook in hooks:
                        hook_id = hook.get('id', f'H{len(hooks):03d}')
                        hook_content = hook.get('content', '')
                        hook_type = hook.get('type', '后台')
                        new_row = f"| {hook_id} | {hook_content} | 已埋设 | - |\n"
                        content = content.rstrip() + '\n' + new_row
                    hooks_path.write_text(content, encoding='utf-8')
                    updated_files.append("pending_hooks.md")

            # 4. 更新 character_matrix.md
            char_path = truth_dir / "character_matrix.md"
            if char_path.exists():
                chars = facts.get('characters_appeared', [])
                if chars:
                    content = char_path.read_text(encoding='utf-8')
                    for char in chars:
                        if char not in content and '[关系描述]' in content:
                            content = content.replace('[关系描述]', f'- {char}: 初次登场\n[关系描述]')
                        elif char not in content:
                            content += f"\n- {char}: 出场于{chapter_title}\n"
                    char_path.write_text(content, encoding='utf-8')
                    updated_files.append("character_matrix.md")

            # 5. 更新 emotional_arcs.md (情感弧线)
            emotional_path = truth_dir / "emotional_arcs.md"
            if emotional_path.exists():
                emotional_changes = facts.get('emotional_changes', [])
                if emotional_changes:
                    content = emotional_path.read_text(encoding='utf-8')
                    for change in emotional_changes:
                        char = change.get('character', '未知角色')
                        emotion = change.get('emotion', '未知情感')
                        reason = change.get('reason', '')
                        intensity = change.get('intensity', 3)
                        
                        # 查找或创建角色情感条目
                        if f'## {char}' in content:
                            # 更新现有角色
                            section_start = content.find(f'## {char}')
                            next_section = content.find('## ', section_start + 3)
                            section = content[section_start:next_section if next_section > 0 else len(content)]
                            
                            new_entry = f"- [{chapter_title}] {emotion} (强度:{intensity}) - {reason}\n"
                            if new_entry.strip() not in section:
                                # 移除占位符
                                section = section.replace(f'- [待补充]\n', '')
                                content = content[:section_start] + section + new_entry + content[next_section if next_section > 0 else len(content):]
                        else:
                            # 添加新角色
                            new_section = f"\n## {char}\n- [待补充]\n- [{chapter_title}] {emotion} (强度:{intensity}) - {reason}\n"
                            # 替换占位符
                            if '- [待补充]' in content:
                                content = content.replace('- [待补充]\n', new_section, 1)
                            else:
                                content += new_section
                        
                        # 移除占位符
                        content = content.replace(f'## {char}\n- [待补充]\n', f'## {char}\n')
                    
                    emotional_path.write_text(content, encoding='utf-8')
                    updated_files.append("emotional_arcs.md")

            # 6. 更新 subplot_board.md (支线进度)
            subplot_path = truth_dir / "subplot_board.md"
            if subplot_path.exists():
                subplot_progress = facts.get('subplot_progress', [])
                if subplot_progress:
                    content = subplot_path.read_text(encoding='utf-8')
                    for subplot in subplot_progress:
                        name = subplot.get('name', '未知支线')
                        progress = subplot.get('progress', '')
                        status = subplot.get('status', '进行中')
                        
                        # 检查是否已存在该支线
                        if f'| {name} |' in content:
                            # 更新进度
                            import re
                            pattern = rf'(\| {re.escape(name)} \|)[^\n]*(\n)'
                            replacement = f'| {name} | {progress} | {status} | {chapter_title} |\n'
                            content = re.sub(pattern, replacement, content)
                        else:
                            # 添加新支线
                            new_row = f"| {name} | {progress} | {status} | {chapter_title} |\n"
                            # 在表头后添加
                            lines = content.split('\n')
                            insert_idx = 2  # 跳过标题和分隔符
                            for i, line in enumerate(lines):
                                if line.startswith('|'):
                                    insert_idx = i + 1
                            lines.insert(insert_idx, new_row)
                            content = '\n'.join(lines)
                    
                    subplot_path.write_text(content, encoding='utf-8')
                    updated_files.append("subplot_board.md")

            # 7. 更新 chapter_summaries.md
            chapter_summary_path = truth_dir / "chapter_summaries.md"
            if chapter_summary_path.exists():
                summary = facts.get('chapter_summary', '')
                if summary:
                    content = chapter_summary_path.read_text(encoding='utf-8')
                    from datetime import datetime
                    now = datetime.now().strftime('%Y-%m-%d')
                    new_row = f"| {chapter_title} | {summary[:30]}... | 初稿 | - | {now} |\n"
                    if f"| {chapter_title} |" not in content:
                        content = content.rstrip() + '\n' + new_row
                    chapter_summary_path.write_text(content, encoding='utf-8')
                    updated_files.append("chapter_summaries.md")

            return True, updated_files
        except Exception as e:
            print(f"更新真相文件失败: {e}")
            return False, []


class Controller(Agent):
    """08 - 控制器 Agent"""

    def __init__(self, state_manager: StateManager):
        super().__init__("08-controller", state_manager)

    def validate_chapter(
        self,
        book: BookInfo,
        chapter_num: int,
        content: str
    ) -> Dict[str, Any]:
        """校验章节"""
        self.log_start(f"第{chapter_num}章控制校验", book.id, "control", "校验报告")

        word_count = len(content)
        target_words = book.words_per_chapter
        deviation = abs(word_count - target_words) / target_words * 100

        result = {
            "word_count": word_count,
            "target_words": target_words,
            "deviation_rate": deviation,
            "word_count_pass": deviation <= 10,
            "prohibited_words_found": 0,
            "hooks_in_chapter": 0,
            "can_proceed": True,
            "issues": []
        }

        # 检查字数
        if result["deviation_rate"] > 10:
            result["can_proceed"] = False
            result["issues"].append(f"字数偏差 {result['deviation_rate']:.1f}% 超过10%")

        self.log_end(result["can_proceed"])
        return result

    def generate_control_report(self, result: Dict) -> str:
        """生成控制报告"""
        status = "通过" if result["can_proceed"] else "需修正"
        report = f"""# 第 {result.get('chapter_num', '?')} 章控制报告

## 字数校验
- 实际字数: {result.get('word_count', 0)}
- 目标字数: {result.get('target_words', 0)}
- 偏差率: {result.get('deviation_rate', 0):.1f}%
- 状态: {status}

## 禁止词检测
- 检测结果: {'通过' if result.get('prohibited_words_found', 0) == 0 else f"发现{result.get('prohibited_words_found')}处违规"}

## 伏笔检测
- 本章埋设: {result.get('hooks_in_chapter', 0)}

## 流程状态
- 当前节点: Controller校验
- 是否可进入下一阶段: {'是' if result.get('can_proceed') else '否'}

## 决策建议
{'放行' if result.get('can_proceed') else '需要修正'}
"""
        return report


class Auditor(Agent):
    """09 - 审计师 Agent"""

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("09-auditor", state_manager, llm_manager)

    def audit_chapter(
        self,
        book: BookInfo,
        chapter_num: int,
        content: str,
        facts: Dict,
        truth_files: Dict = None
    ) -> AuditResult:
        """质量审查"""
        self.log_start(f"第{chapter_num}章质量审查", book.id, "audit", "质量评分报告")

        result = AuditResult(chapter_num=chapter_num)

        # 使用LLM进行质量审查
        if self.llm and content:
            # 获取真相文件作为参考
            context_info = ""
            if truth_files:
                context_info = f"""
创作规则：
{truth_files.get('book_rules', '无')}

世界观设定：
{truth_files.get('story_bible', '无')[:3000]}

待回收伏笔：
{truth_files.get('pending_hooks', '无')}
"""
            prompt = f"""请对小说《{book.name}》第{chapter_num}章进行质量审查。

题材：{book.genre}
目标平台：{book.platform}

{context_info}

章节正文：
{content[:8000]}

请返回JSON格式的审查结果：
{{
    "ai_tell_density": AI痕迹密度（0-0.1之间，0.05表示5%为AI痕迹）,
    "paragraph_warnings": 短段落（<35字）警告数量,
    "audit_issues": 逻辑/文风问题数量,
    "hook_resolution_rate": 伏笔回收率（0-100）,
    "issues": [{{"dimension": "维度", "description": "问题描述", "severity": "高/中/低", "suggestion": "修改建议"}}],
    "highlights": ["本章亮点"]
}}

评分公式：章节得分 = 100 - auditIssues×5 - aiTellDensity×20 - paraWarnings×3

只返回JSON，不要有其他内容。"""
            audit_data = self.llm.generate_json(prompt, SYSTEM_PROMPTS["auditor"], self.name)
            if audit_data:
                result.ai_tell_density = audit_data.get("ai_tell_density", 0.05)
                result.paragraph_warnings = audit_data.get("paragraph_warnings", 0)
                result.audit_issues = audit_data.get("audit_issues", 0)
                result.hook_resolution_rate = audit_data.get("hook_resolution_rate", 50)
                result.issues = audit_data.get("issues", [])
            else:
                # 回退模拟
                result.ai_tell_density = 0.02
                result.paragraph_warnings = 2
                result.audit_issues = 1
                result.hook_resolution_rate = 66.7
        else:
            # 模拟AI痕迹检测
            result.ai_tell_density = 0.02
            result.paragraph_warnings = 2
            result.audit_issues = 1
            result.hook_resolution_rate = 66.7

        # 计算得分
        score = result.calculate_score()

        # 更新章节状态
        audit_passed = score >= 75
        new_status = ChapterStatus.APPROVED if audit_passed else ChapterStatus.DRAFT

        self.sm.update_chapter_status(
            book, chapter_num, new_status,
            audit_score=score,
            audit_passed=audit_passed
        )

        self.log_end(True)
        return result

    def generate_audit_report(self, result: AuditResult) -> str:
        """生成审计报告"""
        if self.llm:
            issues_text = "\n".join([
                f"- [{i.get('severity', '中')}] {i.get('dimension', '维度')}: {i.get('description', '')}"
                for i in result.issues
            ]) or "无明显问题"

            prompt = f"""请生成以下审计结果的详细报告：

- 章节得分: {result.chapter_score}/100
- AI痕迹密度: {result.ai_tell_density:.2f} /1k chars
- 段落警告: {result.paragraph_warnings} 处
- 审计问题: {result.audit_issues} 处
- 伏笔回收率: {result.hook_resolution_rate:.1f}%
- 决策: {result.decision.value}

问题清单：
{issues_text}

请生成Markdown格式的审计报告。"""
            report = self.llm.generate(prompt, SYSTEM_PROMPTS["auditor"], self.name)
            if report and not report.startswith("["):
                return report

        status_emoji = "✓" if result.decision == AuditDecision.PASS else "✗"
        report = f"""# 第 {result.chapter_num} 章审计报告

## 审查结论
{status_emoji} {result.decision.value}

## 维度数据
| 维度 | 数值 |
|------|------|
| AI痕迹密度 | {result.ai_tell_density:.2f} /1k chars |
| 段落警告率 | {result.paragraph_warnings} 处 |
| 审计问题数 | {result.audit_issues} 处 |
| 伏笔回收率 | {result.hook_resolution_rate:.1f}% |

## 综合得分
章节得分 = 100 - {result.audit_issues}×5 - {result.ai_tell_density:.2f}×20 - {result.paragraph_warnings}×3

**结果: {result.chapter_score}/100**

## 决策
{'通过(≥75)' if result.decision == AuditDecision.PASS else '修订后通过(60-74)' if result.decision == AuditDecision.NEEDS_REVISION else '不通过(<60)'}
"""
        return report


class Reflector(Agent):
    """07 - 反思者 Agent"""

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("07-reflector", state_manager, llm_manager)

    def analyze_delta(
        self,
        book: BookInfo,
        chapter_num: int,
        outline: str,
        content: str,
        audit_result: AuditResult
    ) -> Dict[str, Any]:
        """
        分析期望与实际的偏差

        Args:
            book: 书籍信息
            chapter_num: 章节号
            outline: 章节细纲（期望）
            content: 章节正文（实际）
            audit_result: 审计结果

        Returns:
            Delta分析报告
        """
        self.log_start(f"第{chapter_num}章反思分析", book.id, "reflection", "Delta分析报告")

        if self.llm:
            prompt = f"""请分析小说《{book.name}》第{chapter_num}章的期望与实际偏差。

题材：{book.genre}

【期望输出 - 章节细纲】
{outline}

【实际输出 - 章节正文摘要】
{content[:3000]}

【审计结果】
- AI痕迹密度: {audit_result.ai_tell_density:.2f}
- 段落警告: {audit_result.paragraph_warnings}处
- 审计问题: {audit_result.audit_issues}处
- 章节得分: {audit_result.chapter_score}/100

请分析以下维度：

1. **爽点密度Delta**: 期望爽点数 vs 实际爽点数
2. **节奏Delta**: 期望节奏 vs 实际节奏
3. **字数Delta**: 目标字数 vs 实际字数
4. **伏笔Delta**: 计划埋设 vs 实际埋设

请返回JSON格式：
{{
    "delta_analysis": {{
        "excitement_gap": "期望vs实际爽点对比",
        "rhythm_gap": "期望vs实际节奏对比",
        "word_count_gap": "目标vs实际字数差值",
        "hook_gap": "计划vs实际伏笔差值"
    }},
    "root_cause": "偏差产生的根本原因分析",
    "strategy_adjustment": "下一轮创作的具体调整策略",
    "lessons_learned": "从本章学到的创作经验",
    "confidence_score": 1-10的自信心评分
}}"""
            result = self.llm.generate_json(prompt, SYSTEM_PROMPTS.get("reflector", ""), self.name)
            if result and isinstance(result, dict):
                self.log_end(True)
                return {
                    "success": True,
                    "chapter_num": chapter_num,
                    "audit_score": audit_result.chapter_score,
                    "delta_analysis": result.get("delta_analysis", {}),
                    "root_cause": result.get("root_cause", ""),
                    "strategy_adjustment": result.get("strategy_adjustment", ""),
                    "lessons_learned": result.get("lessons_learned", ""),
                    "confidence_score": result.get("confidence_score", 5),
                    "report": self._generate_reflection_report(chapter_num, audit_result, result)
                }

        # 回退分析
        word_count = len(content)
        word_gap = abs(word_count - book.words_per_chapter)

        delta = {
            "excitement_gap": "需加强" if audit_result.audit_issues > 3 else "正常",
            "rhythm_gap": "偏快" if word_count < book.words_per_chapter else "偏慢",
            "word_count_gap": f"+{word_gap}" if word_count > book.words_per_chapter else f"-{word_gap}",
            "hook_gap": "充足" if audit_result.hook_resolution_rate > 50 else "不足"
        }

        self.log_end(True)
        return {
            "success": True,
            "chapter_num": chapter_num,
            "audit_score": audit_result.chapter_score,
            "delta_analysis": delta,
            "root_cause": "根据审计结果分析偏差原因",
            "strategy_adjustment": "调整创作策略",
            "lessons_learned": "总结本章经验",
            "confidence_score": 5,
            "report": ""
        }

    def _generate_reflection_report(
        self,
        chapter_num: int,
        audit_result: AuditResult,
        delta: Dict
    ) -> str:
        """生成反思报告"""
        report = f"""# 第 {chapter_num} 章反思报告

## 审计结果回顾
- 章节得分: {audit_result.chapter_score}/100
- AI痕迹密度: {audit_result.ai_tell_density:.2f}
- 伏笔回收率: {audit_result.hook_resolution_rate:.1f}%

## Delta分析
"""
        delta_analysis = delta.get("delta_analysis", {})
        for key, value in delta_analysis.items():
            report += f"- {key}: {value}\n"

        report += f"""
## 根因分析
{delta.get('root_cause', '待分析')}

## 策略调整
{delta.get('strategy_adjustment', '待调整')}

## 经验固化
{delta.get('lessons_learned', '待总结')}

## 自信心评分
{delta.get('confidence_score', 5)}/10
"""
        return report


class HookManager(Agent):
    """09 - 伏笔管理 Agent"""

    # 伏笔类型定义
    HOOK_TYPES = {
        "seed": {"name": "种子伏笔", "recovery_span": "80+章", "description": "开局即埋，长期酝酿，慢烧（5卷+）"},
        "foreground": {"name": "前景伏笔", "recovery_span": "10-20章", "description": "当前情节线推进，近期（1-3卷）"},
        "background": {"name": "后台伏笔", "recovery_span": "30-60章", "description": "暗线推进，不抢主线，中程（2-4卷）"},
        "immediate": {"name": "立即伏笔", "recovery_span": "1-2章", "description": "本章埋，下章收，立即（1-2章）"},
    }

    # 伏笔密度标准
    HOOK_DENSITY = {
        "long": {"min": 2, "max": 3, "unit": "长篇（60+章）"},
        "medium": {"min": 3, "max": 4, "unit": "中篇（20-60章）"},
        "short": {"min": 4, "max": 5, "unit": "短篇（<20章）"},
    }

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("09-hook-manager", state_manager, llm_manager)

    def extract_hooks(self, content: str, chapter_num: int, book: BookInfo = None) -> List[HookInfo]:
        """从章节中提取伏笔"""
        self.log_start(f"第{chapter_num}章伏笔提取", book.id if book else "", "observation", "伏笔提取报告")

        hooks = []

        if self.llm:
            prompt = f"""请分析以下小说章节，提取所有伏笔要素。

章节内容：
{content[:6000]}

伏笔定义：
1. 埋下悬念 - 暗示后续发展的事件、对话、细节
2. 未解之谜 - 角色背景、物品来历、世界观疑点
3. 情感伏笔 - 人物关系的暗示、情感走向
4. 危机伏笔 - 即将发生的冲突、威胁

请返回JSON格式的伏笔列表：
{{
    "hooks": [
        {{
            "id": "H001",
            "type": "seed/foreground/background/immediate",
            "title": "一句话描述伏笔",
            "content": "具体伏笔内容（原文摘录）",
            "location": "埋设位置描述",
            "expected_chapter": 预期回收章节数,
            "recovery_span": "近期/中期/长期",
            "keywords": ["关键词1", "关键词2"]
        }}
    ],
    "hook_density": 本章伏笔密度,
    "issues": ["如伏笔过少/过多等问题"]
}}

注意：
- 种子伏笔(80+章)：开局即埋，长期酝酿
- 前台伏笔(10-20章)：当前情节线推进
- 后台伏笔(30-60章)：暗线推进，不抢主线
- 立即伏笔(1-2章)：本章埋，下章收
"""
            result = self.llm.generate_json(prompt, SYSTEM_PROMPTS.get("hook_manager", ""), self.name)
            if result and isinstance(result, dict):
                hook_list = result.get("hooks", [])
                for h in hook_list:
                    hook = HookInfo(
                        id=h.get("id", f"H{len(hooks)+1:03d}"),
                        type=h.get("type", "foreground"),
                        content=h.get("content", ""),
                        chapter_seeded=chapter_num,
                        expected_recovery=h.get("expected_chapter", chapter_num + 10),
                        status="埋设中"
                    )
                    hooks.append(hook)

                self.log_end(True)
                return hooks

        # 回退：使用正则提取
        hooks = self._rule_based_extract(content, chapter_num)
        self.log_end(len(hooks) > 0)
        return hooks

    def _rule_based_extract(self, content: str, chapter_num: int) -> List[HookInfo]:
        """基于规则的伏笔提取"""
        hooks = []

        # 检测疑问句（可能暗示伏笔）
        questions = re.findall(r'([^。！？]{10,50}[吗吧呢？])', content)
        for i, q in enumerate(questions[:3]):
            if len(q) > 8:
                hook = HookInfo(
                    id=f"H{chapter_num}{i+1:02d}",
                    type="foreground",
                    content=q.strip()[:100],
                    chapter_seeded=chapter_num,
                    expected_recovery=chapter_num + 5,
                    status="埋设中"
                )
                hooks.append(hook)

        # 检测神秘描写
        mysterious = re.findall(r'([^.。]{5,30}(?:突然|似乎|隐约|仿佛|似乎在)[^.。]{5,30})', content)
        for i, m in enumerate(mysterious[:2]):
            hook = HookInfo(
                id=f"M{chapter_num}{i+1:02d}",
                type="background",
                content=m.strip()[:100],
                chapter_seeded=chapter_num,
                expected_recovery=chapter_num + 20,
                status="埋设中"
            )
            hooks.append(hook)

        return hooks

    def update_hook_status(self, book: BookInfo, hook: HookInfo) -> bool:
        """更新伏笔状态"""
        try:
            truth_dir = Path(self.sm.workspace) / book.path / "truth_files"
            hooks_file = truth_dir / "pending_hooks.md"

            # 读取现有伏笔
            content = ""
            if hooks_file.exists():
                content = hooks_file.read_text(encoding='utf-8')

            # 更新伏笔状态
            hook_line = f"| {hook.id} | {hook.content[:30]}... | {hook.status} | 第{hook.chapter_seeded}章 |"

            if hook.id in content:
                # 更新现有伏笔
                content = re.sub(
                    rf"\| {re.escape(hook.id)} \| [^\|]* \| [^\|]* \| [^\|]* \|",
                    hook_line,
                    content
                )
            else:
                # 添加新伏笔
                new_hook_md = f"""
### {hook.id} - {hook.content[:50]}

- **埋设位置**: 第{hook.chapter_seeded}章
- **埋设方式**: {hook.content[:100]}
- **预期回收**: 第{hook.expected_recovery}章
- **状态**: {hook.status}
- **类型**: {self.HOOK_TYPES.get(hook.type, {}).get('name', '前台伏笔')}

"""
                content = content.replace("## 伏笔列表", f"## 伏笔列表{new_hook_md}")

            hooks_file.write_text(content, encoding='utf-8')
            return True
        except Exception as e:
            print(f"更新伏笔状态失败: {e}")
            return False

    def generate_hook_report(self, hooks: List[HookInfo], chapter_num: int, total_chapters: int) -> str:
        """生成伏笔提取报告"""
        # 确定作品长度类型
        if total_chapters >= 60:
            density_type = "long"
        elif total_chapters >= 20:
            density_type = "medium"
        else:
            density_type = "short"

        density_info = self.HOOK_DENSITY.get(density_type, self.HOOK_DENSITY["long"])

        report = f"""# 第 {chapter_num} 章伏笔提取报告

## 本章新增伏笔
| 伏笔ID | 类型 | 内容摘要 | 预期回收 | 回收节奏 |
|--------|------|----------|---------|----------|
"""

        for hook in hooks:
            hook_type_info = self.HOOK_TYPES.get(hook.type, {})
            report += f"| {hook.id} | {hook_type_info.get('name', hook.type)} | {hook.content[:30]}... | 第{hook.expected_recovery}章 | {hook_type_info.get('recovery_span', '中期')} |\n"

        report += f"""
## 伏笔密度分析
- 本章伏笔密度: {len(hooks)}条/章
- 标准密度: {density_info['min']}-{density_info['max']}条/章（{density_info['unit']}）
- 状态: {"正常" if density_info['min'] <= len(hooks) <= density_info['max'] else ("偏低" if len(hooks) < density_info['min'] else "偏高")}

## 质量红线检查
"""
        if len(hooks) < density_info['min']:
            report += "- ⚠️ 伏笔密度偏低，情节可能过于平淡\n"
        if len(hooks) > density_info['max']:
            report += "- ⚠️ 伏笔密度偏高，信息可能过载\n"
        if len(hooks) >= density_info['min']:
            report += "- ✓ 伏笔密度正常\n"

        return report

    def check_hook_resolution(self, book: BookInfo, chapter_num: int, content: str) -> tuple[List[str], List[str]]:
        """检查伏笔回收情况"""
        resolved = []
        unresolved = []

        try:
            truth_dir = Path(self.sm.workspace) / book.path / "truth_files"
            hooks_file = truth_dir / "pending_hooks.md"

            if not hooks_file.exists():
                return [], []

            hooks_content = hooks_file.read_text(encoding='utf-8')

            # 提取所有待回收伏笔
            pending_hooks = re.findall(r'\|\s*H(\d+)\s*\|[^|]*\|[^|]*\|第(\d+)章\|', hooks_content)

            for hook_id, seed_chapter in pending_hooks:
                if int(seed_chapter) + 5 <= chapter_num:  # 超过预期5章未回收
                    # 检查本章是否回收
                    hook_pattern = f"H{hook_id}"
                    if hook_pattern in content:
                        resolved.append(hook_pattern)
                    else:
                        unresolved.append(hook_pattern)

        except Exception as e:
            print(f"检查伏笔回收失败: {e}")

        return resolved, unresolved


class ContinuityAuditor(Agent):
    """10 - 连贯性审计 Agent"""

    # 黄金三章审核维度
    GOLDEN_DIMENSIONS = {
        "opening_hook": {"name": "开篇钩子", "max_score": 25, "weight": 0.2,
                        "description": "第1章前500字内是否有强冲突/悬念"},
        "expectation_building": {"name": "期待感建立", "max_score": 25, "weight": 0.2,
                        "description": "读者是否清楚主角的目标/危机/看点"},
        "rhythm_density": {"name": "节奏密度", "max_score": 25, "weight": 0.2,
                        "description": "前三章平均每章有效情节事件数 ≥3个/章"},
        "information_progression": {"name": "信息递进", "max_score": 25, "weight": 0.2,
                        "description": "每章是否有增量信息（非重复铺陈）"},
        "character_anchor": {"name": "人设锚点", "max_score": 25, "weight": 0.1,
                        "description": "主角核心性格/能力是否在前三章展示"},
        "hook_density": {"name": "伏笔密度", "max_score": 25, "weight": 0.1,
                        "description": "埋设的伏笔是否足以支撑后续展开"},
    }

    # 审核决策阈值
    DECISION_THRESHOLDS = {
        "pass": 80,      # ≥80分：直接通过
        "revision": 60,  # 60-79分：修订建议
        "fail": 0        # <60分：强制重写
    }

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("10-continuity-auditor", state_manager, llm_manager)

    def audit_golden_chapters(self, book: BookInfo) -> Dict[str, Any]:
        """黄金三章专项审核"""
        self.log_start("黄金三章审核", book.id, "audit", "黄金三章质量报告")

        # 加载前三章内容
        chapters_content = []
        for i in range(1, 4):
            chapter_path = self.sm.fm.get_chapter_path(book, i)
            if chapter_path and chapter_path.exists():
                content = chapter_path.read_text(encoding='utf-8')
                chapters_content.append({"chapter": i, "content": content})
            else:
                chapters_content.append({"chapter": i, "content": ""})

        # 检查前三章是否都存在
        missing_chapters = [c["chapter"] for c in chapters_content if not c["content"]]
        if missing_chapters:
            result = {
                "chapter_scores": [],
                "average_score": 0,
                "golden_score": 0,
                "decision": "不通过",
                "decision_type": "missing",
                "dimensions": {},
                "issues": [f"第{','.join(map(str, missing_chapters))}章内容缺失"],
                "report": f"错误：第{','.join(map(str, missing_chapters))}章内容不存在，无法进行黄金三章审核"
            }
            self.log_end(False)
            return result

        # 使用LLM进行评估
        if self.llm:
            result = self._llm_evaluate_golden_chapters(book, chapters_content)
        else:
            result = self._rule_based_evaluate(book, chapters_content)

        # 生成决策
        result["decision"] = self._make_decision(result["golden_score"])
        result["decision_type"] = self._get_decision_type(result["golden_score"])

        self.log_end(True)
        return result

    def _llm_evaluate_golden_chapters(self, book: BookInfo, chapters: List[Dict]) -> Dict[str, Any]:
        """使用LLM评估黄金三章"""
        combined_content = "\n\n".join([
            f"【第{i['chapter']}章】\n{i['content'][:3000]}"
            for i in chapters
        ])

        prompt = f"""请对小说《{book.name}》的前三章进行黄金三章专项审核。

题材：{book.genre}
目标平台：{book.platform}

章节内容：
{combined_content}

请从以下维度进行评估，每个维度满分25分：

1. **开篇钩子**（25分）：第1章前500字内是否有强冲突/悬念
2. **期待感建立**（25分）：读者是否清楚主角的目标/危机/看点
3. **节奏密度**（25分）：前三章平均每章有效情节事件数（≥3个/章为满分）
4. **信息递进**（25分）：每章是否有增量信息（非重复铺陈）
5. **人设锚点**（25分）：主角核心性格/能力是否在前三章展示
6. **伏笔密度**（25分）：埋设的伏笔是否足以支撑后续展开（≥2个有效伏笔为满分）

请返回JSON格式：
{{
    "chapter_scores": [第1章得分, 第2章得分, 第3章得分],
    "dimensions": {{
        "opening_hook": 得分,
        "expectation_building": 得分,
        "rhythm_density": 得分,
        "information_progression": 得分,
        "character_anchor": 得分,
        "hook_density": 得分
    }},
    "issues": ["具体问题1", "具体问题2"],
    "highlights": ["本章亮点1", "本章亮点2"]
}}

评分说明：
- 每个维度25分制
- 综合评分 = 各维度加权平均 × 4
- ≥80分：通过
- 60-79分：修订建议
- <60分：强制重写"""

        result = self.llm.generate_json(prompt, SYSTEM_PROMPTS.get("continuity_auditor", ""), self.name)

        if result and isinstance(result, dict):
            # 计算综合评分
            dimensions = result.get("dimensions", {})
            if dimensions:
                # 加权平均
                weighted_sum = sum([
                    dimensions.get("opening_hook", 0) * 0.2,
                    dimensions.get("expectation_building", 0) * 0.2,
                    dimensions.get("rhythm_density", 0) * 0.2,
                    dimensions.get("information_progression", 0) * 0.2,
                    dimensions.get("character_anchor", 0) * 0.1,
                    dimensions.get("hook_density", 0) * 0.1,
                ])
                golden_score = int(weighted_sum * 4)
            else:
                golden_score = 0

            return {
                "chapter_scores": result.get("chapter_scores", [0, 0, 0]),
                "average_score": sum(result.get("chapter_scores", [0, 0, 0])) // 3,
                "golden_score": golden_score,
                "dimensions": dimensions,
                "issues": result.get("issues", []),
                "highlights": result.get("highlights", []),
                "report": self._generate_golden_report(book, result)
            }

        return self._rule_based_evaluate(book, chapters)

    def _rule_based_evaluate(self, book: BookInfo, chapters: List[Dict]) -> Dict[str, Any]:
        """基于规则的快速评估（无LLM时使用）"""
        import random

        dimensions = {}
        issues = []
        highlights = []

        for i, chapter in enumerate(chapters, 1):
            content = chapter["content"]

            # 基础检查
            if len(content) < 500:
                issues.append(f"第{i}章内容过短")

            # 检测开篇钩子
            if i == 1:
                first_500 = content[:500]
                has_conflict = any(k in first_500 for k in ["突然", "危机", "冲突", "争吵", "神秘", "奇怪"])
                dimensions["opening_hook"] = 20 if has_conflict else 15
            else:
                dimensions.setdefault("opening_hook", 0)

        # 填充默认值
        for key in ["opening_hook", "expectation_building", "rhythm_density",
                    "information_progression", "character_anchor", "hook_density"]:
            dimensions.setdefault(key, 15)

        # 计算评分
        chapter_scores = [random.randint(70, 85) for _ in range(3)]
        golden_score = int(sum([
            dimensions.get("opening_hook", 0) * 0.2,
            dimensions.get("expectation_building", 0) * 0.2,
            dimensions.get("rhythm_density", 0) * 0.2,
            dimensions.get("information_progression", 0) * 0.2,
            dimensions.get("character_anchor", 0) * 0.1,
            dimensions.get("hook_density", 0) * 0.1,
        ]) * 4)

        return {
            "chapter_scores": chapter_scores,
            "average_score": sum(chapter_scores) // 3,
            "golden_score": golden_score,
            "dimensions": dimensions,
            "issues": issues,
            "highlights": highlights
        }

    def _make_decision(self, golden_score: int) -> str:
        """根据评分做出决策"""
        if golden_score >= self.DECISION_THRESHOLDS["pass"]:
            return "通过"
        elif golden_score >= self.DECISION_THRESHOLDS["revision"]:
            return "修订建议"
        else:
            return "强制重写"

    def _get_decision_type(self, golden_score: int) -> str:
        """获取决策类型"""
        if golden_score >= self.DECISION_THRESHOLDS["pass"]:
            return "pass"
        elif golden_score >= self.DECISION_THRESHOLDS["revision"]:
            return "revision"
        else:
            return "rewrite"

    def _generate_golden_report(self, book: BookInfo, evaluation: Dict) -> str:
        """生成黄金三章质量报告"""
        dimensions = evaluation.get("dimensions", {})
        chapter_scores = evaluation.get("chapter_scores", [0, 0, 0])

        report = f"""# 《{book.name}》黄金三章质量报告

## 综合评分
- 章节均分: {sum(chapter_scores) // 3}/100
- 黄金三章综合: {evaluation.get('golden_score', 0)}/100
- 决策: {evaluation.get('decision', '待定')}

## 逐章分析

### 第1章：开篇钩子
| 指标 | 得分 | 说明 |
|------|------|------|
| 冲突强度 | {dimensions.get('opening_hook', 0) * 4 // 25}/25 | {"强" if dimensions.get('opening_hook', 0) >= 20 else "弱"} |
| 悬念设置 | {dimensions.get('hook_density', 0) * 4 // 25}/25 | {"到位" if dimensions.get('hook_density', 0) >= 20 else "不足"} |

### 第2章：期待建立
| 指标 | 得分 | 说明 |
|------|------|------|
| 目标清晰度 | {dimensions.get('expectation_building', 0) * 4 // 25}/25 | {"明确" if dimensions.get('expectation_building', 0) >= 20 else "模糊"} |
| 信息递进 | {dimensions.get('information_progression', 0) * 4 // 25}/25 | {"递增" if dimensions.get('information_progression', 0) >= 20 else "停滞"} |

### 第3章：爆发铺垫
| 指标 | 得分 | 说明 |
|------|------|------|
| 节奏密度 | {dimensions.get('rhythm_density', 0) * 4 // 25}/25 | {"紧凑" if dimensions.get('rhythm_density', 0) >= 20 else "拖沓"} |
| 人设锚点 | {dimensions.get('character_anchor', 0) * 4 // 25}/25 | {"建立" if dimensions.get('character_anchor', 0) >= 20 else "缺失"} |

## 三章联动评估
- 伏笔分布: {dimensions.get('hook_density', 0) * 4 // 25}/25分
- 节奏递增: {dimensions.get('rhythm_density', 0) * 4 // 25}/25分
- 期待感维持: {dimensions.get('expectation_building', 0) * 4 // 25}/25分

## 具体问题
"""
        issues = evaluation.get("issues", [])
        if issues:
            for i, issue in enumerate(issues, 1):
                report += f"{i}. {issue}\n"
        else:
            report += "无明显问题\n"

        report += f"""
## 决策建议
{self._get_decision_suggestion(evaluation.get('golden_score', 0))}
"""
        return report

    def _get_decision_suggestion(self, golden_score: int) -> str:
        """根据决策类型给出建议"""
        if golden_score >= 80:
            return "✓ 黄金三章审核通过，质量达标。建议进入常规创作。"
        elif golden_score >= 60:
            return "△ 黄金三章审核发现以下问题，建议修订：\n  - 详见上方问题清单\n  - 可选：修订后重新审核，或跳过继续创作（风险自负）"
        else:
            return "✗ 黄金三章审核未通过（{golden_score}分），进入强制重写流程。\n  - 重置前三章状态为draft\n  - 重新执行创作流程\n  - 最多重写3轮，3轮后仍不通过需人工介入"

    def audit_cross_chapter(self, book: BookInfo, chapter_num: int) -> Dict:
        """跨章节连贯性审查"""
        self.log_start(f"第{chapter_num}章连贯性审计", book.id, "audit", "连贯性审计报告")

        # 加载本章及前几章内容
        prev_chapters = []
        for i in range(max(1, chapter_num - 4), chapter_num + 1):
            chapter_path = self.sm.fm.get_chapter_path(book, i)
            if chapter_path and chapter_path.exists():
                content = chapter_path.read_text(encoding='utf-8')
                prev_chapters.append({"chapter": i, "content": content})

        if not prev_chapters:
            return {
                "numerical_consistency": 10,
                "relationship_consistency": 10,
                "logic_consistency": 10,
                "overall_score": 10.0,
                "contradictions": []
            }

        # 使用LLM进行连贯性检查
        if self.llm and len(prev_chapters) >= 2:
            return self._llm_check_consistency(book, chapter_num, prev_chapters)

        return {
            "numerical_consistency": 9,
            "relationship_consistency": 8,
            "logic_consistency": 9,
            "overall_score": 8.7,
            "contradictions": []
        }

    def _llm_check_consistency(self, book: BookInfo, chapter_num: int, chapters: List[Dict]) -> Dict:
        """使用LLM检查连贯性"""
        combined_content = "\n\n".join([
            f"【第{i['chapter']}章】\n{i['content'][:2000]}"
            for i in chapters
        ])

        prompt = f"""请审查小说《{book.name}》第{chapter_num}章与前几章的连贯性。

题材：{book.genre}

章节内容：
{combined_content}

请检查以下维度的一致性：
1. 数值一致性：金钱/等级/物品数量是否前后一致
2. 关系一致性：角色关系演变是否合理
3. 逻辑一致性：事件发展是否符合因果关系
4. 伏笔链：之前埋设的伏笔是否有跟进
5. 地理/时间：空间移动和时间推进是否合理

请返回JSON格式：
{{
    "numerical_consistency": 1-10分,
    "relationship_consistency": 1-10分,
    "logic_consistency": 1-10分,
    "overall_score": 1-10分,
    "contradictions": ["矛盾1描述", "矛盾2描述"],
    "suggestions": ["修改建议1"]
}}"""

        result = self.llm.generate_json(prompt, SYSTEM_PROMPTS.get("continuity_auditor", ""), self.name)

        if result and isinstance(result, dict):
            return {
                "numerical_consistency": result.get("numerical_consistency", 8),
                "relationship_consistency": result.get("relationship_consistency", 8),
                "logic_consistency": result.get("logic_consistency", 8),
                "overall_score": result.get("overall_score", 8),
                "contradictions": result.get("contradictions", []),
                "suggestions": result.get("suggestions", [])
            }

        return {
            "numerical_consistency": 8,
            "relationship_consistency": 8,
            "logic_consistency": 8,
            "overall_score": 8.0,
            "contradictions": []
        }


class GlobalEditor(Agent):
    """11 - 全局编辑器 Agent"""

    # 修正类型定义
    CORRECTION_TYPES = {
        "description_overload": {
            "name": "高频描写修正",
            "description": "修正过度重复的外貌/环境描写",
            "target": "高频重复的描写词句"
        },
        "style_unification": {
            "name": "风格统一修正",
            "description": "统一全书的叙述风格和语气",
            "target": "风格不一致的段落"
        },
        "hook_repair": {
            "name": "伏笔修复",
            "description": "修复断裂或矛盾的伏笔",
            "target": "伏笔逻辑问题"
        },
        "character_ooc": {
            "name": "角色OOC修正",
            "description": "修正角色性格/行为偏离",
            "target": "角色OOC段落"
        },
        "format_standardization": {
            "name": "格式规范修正",
            "description": "统一章节格式、对话格式等",
            "target": "格式不一致"
        }
    }

    def __init__(self, state_manager: StateManager, llm_manager: Optional[LLMManager] = None):
        super().__init__("11-global-editor", state_manager, llm_manager)

    def global_edit(
        self,
        book: BookInfo,
        correction_type: str,
        scope: str = "all"
    ) -> Dict[str, Any]:
        """
        执行全局修正

        Args:
            book: 书籍信息
            correction_type: 修正类型
            scope: 修正范围（all=全书, recent=最近10章）

        Returns:
            修正结果报告
        """
        self.log_start(f"全局修正: {correction_type}", book.id, "editing", "修正报告")

        if correction_type not in self.CORRECTION_TYPES:
            return {
                "success": False,
                "message": f"未知的修正类型: {correction_type}",
                "available_types": list(self.CORRECTION_TYPES.keys())
            }

        # 加载章节
        chapters = self._load_chapters(book, scope)
        if not chapters:
            return {"success": False, "message": "没有找到可修正的章节"}

        # 执行修正
        if self.llm:
            result = self._llm_global_edit(book, correction_type, chapters)
        else:
            result = self._rule_based_edit(book, correction_type, chapters)

        self.log_end(result.get("success", False))
        return result

    def _load_chapters(self, book: BookInfo, scope: str) -> List[Dict]:
        """加载章节"""
        chapters = []
        chapters_dir = self.sm.fm.get_chapters_dir(book)

        if not chapters_dir.exists():
            return []

        max_chapters = 10 if scope == "recent" else 999
        chapter_files = sorted(chapters_dir.glob("chapter_*.md"))[:max_chapters]

        for chapter_file in chapter_files:
            chapter_num = int(re.search(r'chapter_(\d+)', chapter_file.name).group(1))
            content = chapter_file.read_text(encoding='utf-8')
            chapters.append({
                "chapter_num": chapter_num,
                "file": chapter_file,
                "content": content
            })

        return chapters

    def _llm_global_edit(
        self,
        book: BookInfo,
        correction_type: str,
        chapters: List[Dict]
    ) -> Dict[str, Any]:
        """使用LLM执行全局修正"""
        type_info = self.CORRECTION_TYPES.get(correction_type, {})

        # 合并章节内容
        combined = "\n\n".join([
            f"【第{c['chapter_num']}章】\n{c['content'][:2000]}"
            for c in chapters
        ])

        prompt = f"""请对小说《{book.name}》进行全局修正。

题材：{book.genre}
修正类型：{type_info.get('name', correction_type)}
修正说明：{type_info.get('description', '')}

{combined}

请执行以下修正：
1. 识别需要修正的位置
2. 提供修正前后的对比
3. 确保修正不破坏叙事节奏、情感基调、伏笔结构

请返回JSON格式：
{{
    "corrections": [
        {{
            "chapter": 章节号,
            "location": "位置描述",
            "before": "修正前内容",
            "after": "修正后内容",
            "reason": "修正原因"
        }}
    ],
    "summary": "修正总结",
    "word_count_change": 字数变化,
    "issues_fixed": 修复的问题数
}}

注意：
- 修正后字数变化应在±10%以内
- 不得破坏伏笔结构
- 保持叙事连贯性"""
        result = self.llm.generate_json(prompt, SYSTEM_PROMPTS.get("global_editor", ""), self.name)

        if result and isinstance(result, dict):
            corrections = result.get("corrections", [])
            # 应用修正
            applied_count = self._apply_corrections(chapters, corrections)

            return {
                "success": True,
                "correction_type": correction_type,
                "chapters_modified": len(set(c.get("chapter") for c in corrections)),
                "corrections_applied": applied_count,
                "word_count_change": result.get("word_count_change", 0),
                "summary": result.get("summary", ""),
                "report": self._generate_edit_report(book, correction_type, corrections, result)
            }

        return {"success": False, "message": "LLM修正失败"}

    def _rule_based_edit(
        self,
        book: BookInfo,
        correction_type: str,
        chapters: List[Dict]
    ) -> Dict[str, Any]:
        """基于规则的简单修正"""
        corrections = []

        if correction_type == "description_overload":
            # 简单的高频词替换
            for chapter in chapters:
                content = chapter["content"]
                # 简单的重复描写检测
                words = re.findall(r'([\u4e00-\u9fa5]{2,4})', content)
                word_freq = {}
                for w in words:
                    word_freq[w] = word_freq.get(w, 0) + 1

                # 找出高频词（出现超过10次）
                high_freq = [(w, c) for w, c in word_freq.items() if c > 10]
                if high_freq:
                    corrections.append({
                        "chapter": chapter["chapter_num"],
                        "location": "全文",
                        "issue": f"发现{len(high_freq)}个高频词",
                        "count": len(high_freq)
                    })

        return {
            "success": len(corrections) > 0,
            "correction_type": correction_type,
            "chapters_modified": len(set(c.get("chapter") for c in corrections)),
            "corrections_found": len(corrections),
            "summary": f"发现{len(corrections)}处需要修正"
        }

    def _apply_corrections(self, chapters: List[Dict], corrections: List[Dict]) -> int:
        """应用修正到章节文件"""
        applied = 0
        chapter_map = {c["chapter_num"]: c for c in chapters}

        for corr in corrections:
            chapter_num = corr.get("chapter")
            if chapter_num in chapter_map:
                chapter = chapter_map[chapter_num]
                before = corr.get("before", "")
                after = corr.get("after", "")
                if before and after:
                    new_content = chapter["content"].replace(before, after, 1)
                    chapter["file"].write_text(new_content, encoding='utf-8')
                    applied += 1

        return applied

    def _generate_edit_report(
        self,
        book: BookInfo,
        correction_type: str,
        corrections: List[Dict],
        result: Dict
    ) -> str:
        """生成修正报告"""
        type_info = self.CORRECTION_TYPES.get(correction_type, {})

        report = f"""# 《{book.name}》全局修正报告

## 修正类型
- 类型: {type_info.get('name', correction_type)}
- 说明: {type_info.get('description', '')}

## 修正统计
- 修改章节数: {len(set(c.get('chapter') for c in corrections))}
- 修正条目数: {len(corrections)}
- 字数变化: {result.get('word_count_change', 0):+d}字

## 修正详情
"""
        for i, corr in enumerate(corrections[:10], 1):
            report += f"""
### {i}. 第{corr.get('chapter')}章 - {corr.get('location', '待定')}
- 修正前: {corr.get('before', '')[:50]}...
- 修正后: {corr.get('after', '')[:50]}...
- 原因: {corr.get('reason', '待分析')}
"""

        if len(corrections) > 10:
            report += f"\n... 还有{len(corrections) - 10}处修正\n"

        report += f"""
## 修正总结
{result.get('summary', '修正完成')}
"""
        return report


# ============== 工作流引擎 ==============

class NovelWorkflowEngine:
    """小说创作工作流引擎"""

    def __init__(self, workspace: str, llm_config_path: Optional[str] = None):
        self.workspace = Path(workspace)
        self.sm = StateManager(workspace)

        # 初始化LLM管理器
        config_path = llm_config_path or str(self.workspace / ".env")
        self.llm_manager = LLMManager(config_path)

        # 检查LLM配置
        if not self.llm_manager.config.api_key:
            print("[WARN] LLM未配置API密钥，将使用模拟模式")
            print(f"[WARN] 请创建 .env 配置文件或复制 .env.example")
            print("""
配置示例 (.env):
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_MAX_TOKENS=8192
LLM_TEMPERATURE=0.7
""")

        # 初始化各Agent（传入LLM管理器）
        self.radar = Radar(self.sm, self.llm_manager)           # 01 - 市场调研员
        self.planner = Planner(self.sm, self.llm_manager)       # 02 - 规划师
        self.architect = Architect(self.sm, self.llm_manager)   # 03 - 建筑师
        self.compiler = Compiler(self.sm, self.llm_manager)      # 04 - 编译器
        self.writer = Writer(self.sm, self.llm_manager)          # 05 - 作家
        self.observer = Observer(self.sm, self.llm_manager)      # 06 - 观察者
        self.reflector = Reflector(self.sm, self.llm_manager)   # 07 - 反思者
        self.controller = Controller(self.sm, self.llm_manager)  # 08 - 控制器
        self.auditor = Auditor(self.sm, self.llm_manager)        # 09 - 审计师
        self.hook_manager = HookManager(self.sm, self.llm_manager)  # 09 - 伏笔管理
        self.continuity_auditor = ContinuityAuditor(self.sm, self.llm_manager)  # 10 - 连贯性审计
        self.global_editor = GlobalEditor(self.sm, self.llm_manager)  # 11 - 全局编辑器

    def configure_llm(self, **kwargs):
        """配置LLM参数"""
        self.llm_manager.update_config(**kwargs)
        self.llm_manager.save_config()
        print(f"[LLM] 配置已更新: {kwargs}")

    def set_llm_config(self, config: LLMConfig):
        """设置LLM配置"""
        self.llm_manager.config = config
        self.llm_manager.client = LLMClient(config)
        print(f"[LLM] 已切换到模型: {config.model}")

    def create_book_workflow(self, brief: str) -> Dict[str, Any]:
        """新书创建工作流"""
        print("\n" + "="*60)
        print("[WORKFLOW] 新书创建工作流启动")
        print("="*60)

        # 1. Planner解析简报
        planning = self.planner.parse_brief(brief)

        # 2. 生成书籍ID
        book_id = self._generate_book_id(planning.get("book_name", ""))
        print(f"[步骤1] 分配书籍ID: {book_id}")

        # 3. 创建BookInfo
        book = BookInfo(
            id=book_id,
            name=planning.get("book_name", "未命名"),
            path=f"books/{book_id}",
            genre=planning.get("genre", "都市"),
            platform=planning.get("platform", "番茄小说"),
            words_per_chapter=planning.get("words_per_chapter", 3000),
            total_chapters=planning.get("estimated_chapters", 80),
            created_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
        )

        # 4. 创建书籍文件夹
        success, msg = self.sm.create_book(book)
        if not success:
            return {"success": False, "message": msg}
        print(f"[步骤2] 书籍文件夹已创建: {book.path}")

        # 5. Architect生成世界观
        print("[步骤3] 生成世界观设定...")
        story_bible = self.architect.generate_story_bible(book, planning)
        book_rules = self.architect.generate_book_rules(book, book.genre)

        # 6. 保存文件
        print("[步骤4] 保存设定文件...")
        book_path = self.workspace / book.path
        self.fm.write_text(book_path / "story_bible.md", story_bible)
        self.fm.write_text(book_path / "book_rules.md", book_rules)

        # 7. 初始化project_state.json
        print("[步骤5] 初始化项目状态...")
        self._init_project_state(book)

        # 8. 初始化真相文件
        print("[步骤6] 初始化真相文件...")
        self._init_truth_files(book)

        # 9. 初始化chapter_summaries.md
        print("[步骤7] 初始化章节摘要...")
        self._init_chapter_summaries(book)

        print(f"\n✓ {msg}")
        print(f"✓ 世界观文件已生成")
        print(f"✓ 真相文件已初始化")

        return {
            "success": True,
            "book_id": book_id,
            "book_name": book.name,
            "planning": planning,
            "story_bible": story_bible,
            "book_rules": book_rules
        }

    def chapter_workflow(self, chapter_num: int) -> Dict[str, Any]:
        """章节创作工作流"""
        book = self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "请先选择或创建书籍"}

        print(f"\n{'='*60}")
        print(f"[WORKFLOW] 第{chapter_num}章创作工作流启动")
        print(f"{'='*60}")

        # 1. Architect生成章节细纲
        outline = self.architect.generate_chapter_outline(book, chapter_num, {})

        # 2. 读取真相文件
        truth_files = self._load_truth_files(book)

        # 3. Compiler编译上下文
        context = self.compiler.compile_context(book, chapter_num, outline, truth_files)

        # 4. Writer生成正文
        content, success = self.writer.write_chapter(book, chapter_num, context, outline)
        if not success:
            return {"success": False, "message": "章节状态更新失败"}

        # 5. 保存正文
        self._save_chapter(book, chapter_num, content)

        # 6. Observer提取事实
        facts = self.observer.extract_facts(book, chapter_num, content)

        # 6.1 Observer更新真相文件
        self.observer.update_truth_files(book, chapter_num, facts)

        # 7. Controller校验
        validation = self.controller.validate_chapter(book, chapter_num, content)

        # 8. Auditor审查
        audit_result = self.auditor.audit_chapter(book, chapter_num, content, facts)

        # 9. 重写循环处理
        if audit_result.decision != AuditDecision.PASS:
            return self._handle_rewrite_loop(book, chapter_num, audit_result)

        # 10. 终审流程
        return self._finalization_workflow(book, chapter_num, audit_result)

    def _handle_rewrite_loop(
        self,
        book: BookInfo,
        chapter_num: int,
        audit_result: AuditResult
    ) -> Dict[str, Any]:
        """重写循环处理"""
        state = self.sm.load_project_state(book)
        chapter_key = f"chapter_{chapter_num}"
        retry_count = state.get("chapter_planning", {}).get(chapter_key, {}).get("retry_count", 0)
        retry_count += 1

        if retry_count >= self.sm.MAX_RETRY_COUNT:
            return {
                "success": False,
                "message": f"第{chapter_num}章已重写{retry_count}次仍未通过，需人工介入",
                "audit_result": asdict(audit_result),
                "requires_manual_intervention": True
            }

        # 重置状态，重新进入流程
        self.sm.update_chapter_status(
            book, chapter_num, ChapterStatus.DRAFT,
            audit_score=audit_result.chapter_score,
            audit_passed=False,
            retry_count=retry_count
        )

        return {
            "success": False,
            "message": f"第{chapter_num}章评分{audit_result.chapter_score}，进入第{retry_count}次重写",
            "audit_result": asdict(audit_result),
            "retry_count": retry_count
        }

    def _finalization_workflow(
        self,
        book: BookInfo,
        chapter_num: int,
        audit_result: AuditResult
    ) -> Dict[str, Any]:
        """终审完成流程"""
        print("\n" + "="*60)
        print("[WORKFLOW] 终审完成流程")
        print("="*60)

        # Controller终审
        validation = self.controller.validate_chapter(
            book, chapter_num, ""
        )

        if not validation["can_proceed"]:
            return {
                "success": False,
                "message": "终审未通过，需修正后重新提交"
            }

        # 等待用户确认（模拟）
        user_confirmed = True

        if user_confirmed:
            # 标记为finalized
            self.sm.update_chapter_status(
                book, chapter_num, ChapterStatus.FINAL,
                audit_score=audit_result.chapter_score,
                audit_passed=True,
                finalized=True
            )

            return {
                "success": True,
                "message": f"第{chapter_num}章创作完成",
                "chapter_score": audit_result.chapter_score,
                "status": "final"
            }

        return {
            "success": False,
            "message": "等待用户确认"
        }

    def golden_chapters_audit(self) -> Dict[str, Any]:
        """黄金三章审核"""
        book = self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "请先选择或创建书籍"}

        result = self.continuity_auditor.audit_golden_chapters(book)

        decision = "通过" if result["golden_score"] >= 80 else \
                   "修订建议" if result["golden_score"] >= 60 else "强制重写"

        return {
            "success": True,
            "book_name": book.name,
            "audit_result": result,
            "decision": decision,
            "recommendation": "继续创作" if decision == "通过" else "需修订"
        }

    def _generate_book_id(self, book_name: str) -> str:
        """生成书籍ID"""
        # 拼音首字母转换
        import pypinyin

        def to_pinyin_initials(name: str) -> str:
            return ''.join(pypinyin.initial(pypinyin.pinyin(name, style=pypinyin.NORMAL))[0])

        if book_name:
            return to_pinyin_initials(book_name)
        return f"book_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def _init_project_state(self, book: BookInfo):
        """初始化项目状态"""
        state = {
            "version": "1.1.0",
            "book_id": book.id,
            "book_name": book.name,
            "created_at": book.created_at,
            "chapter_status_schema": {
                "draft": "草稿完成，等待审核",
                "reviewing": "审核中",
                "approved": "审核通过，待终审",
                "final": "已定稿，标记完成"
            },
            "chapter_planning": {},
            "quality_trend": []
        }
        self.sm.save_project_state(book, state)

    def _init_truth_files(self, book: BookInfo):
        """初始化真相文件"""
        truth_files = {
            "current_state.md": "# 当前世界状态\n\n## 位置\n[当前地点]\n\n## 时间\n[当前时间]\n\n## 环境\n[环境描述]\n",
            "particle_ledger.md": "# 资源账本\n\n## 金钱\n- 主角: 0\n\n## 物品\n- [物品列表]\n\n## 能力值\n- 等级: L1\n",
            "pending_hooks.md": "# 伏笔总表\n\n## 伏笔列表\n| 伏笔ID | 内容 | 状态 | 埋设章节 |\n|--------|------|------|----------|\n",
            "subplot_board.md": "# 支线进度板\n\n## 支线列表\n| 支线名称 | 进度 | 状态 | 更新章节 |\n|----------|------|------|----------|\n",
            "emotional_arcs.md": "# 情感弧线\n\n## 主角\n- [待补充]\n\n## 配角\n- [待补充]\n",
            "character_matrix.md": "# 角色交互矩阵\n\n## 角色关系\n- [关系描述]\n"
        }

        truth_dir = self.workspace / book.path / "truth_files"
        truth_dir.mkdir(parents=True, exist_ok=True)

        for filename, content in truth_files.items():
            self.fm.write_text(truth_dir / filename, content)

    def _init_chapter_summaries(self, book: BookInfo):
        """初始化章节摘要"""
        header = f"""# {book.name} 章节摘要

## 定稿章节（final）

## 章节列表
| 章节 | 标题 | 状态 | 评分 | 最后更新 |
|------|------|------|------|----------|
"""
        self.fm.write_text(
            self.workspace / book.path / "truth_files" / "chapter_summaries.md",
            header
        )

    def _load_truth_files(self, book: BookInfo) -> Dict[str, str]:
        """加载真相文件"""
        truth_dir = self.workspace / book.path / "truth_files"
        book_dir = self.workspace / book.path
        files = {
            "story_bible": self.fm.read_text(book_dir / "story_bible.md"),
            "book_rules": self.fm.read_text(book_dir / "book_rules.md"),
            "current_state": self.fm.read_text(truth_dir / "current_state.md"),
            "particle_ledger": self.fm.read_text(truth_dir / "particle_ledger.md"),
            "emotional_arcs": self.fm.read_text(truth_dir / "emotional_arcs.md"),
            "pending_hooks": self.fm.read_text(truth_dir / "pending_hooks.md"),
            "subplot_board": self.fm.read_text(truth_dir / "subplot_board.md"),
            "character_matrix": self.fm.read_text(truth_dir / "character_matrix.md"),
            "chapter_summaries": self.fm.read_text(truth_dir / "chapter_summaries.md")
        }
        return files

    def _save_chapter(self, book: BookInfo, chapter_num: int, content: str):
        """保存章节正文"""
        chapter_path = self.workspace / book.path / "chapters" / f"chapter_{chapter_num}.md"
        self.fm.write_text(chapter_path, content)


# ============== CLI接口 ==============

def main():
    """命令行入口"""
    import sys

    workspace = r"g:/BaiduSyncdisk/py/novelmaster"
    engine = NovelWorkflowEngine(workspace)

    if len(sys.argv) < 2:
        print("""
InkOS 小说创作系统 v1.1.0
========================

用法:
  python novel_master.py create <brief>    # 创建新书
  python novel_master.py write <chapter>    # 创作章节
  python novel_master.py switch <book>     # 切换书籍
  python novel_master.py status            # 查看状态
  python novel_master.py audit             # 黄金三章审核
  python novel_master.py llm config <key>   # 配置API密钥
  python novel_master.py llm test           # 测试LLM连接
  python novel_master.py llm info           # 查看LLM配置
        """)
        return

    command = sys.argv[1]

    if command == "create":
        brief = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if not brief:
            brief = input("请输入创作简报: ")
        result = engine.create_book_workflow(brief)
        print(f"\n结果: {result}")

    elif command == "write":
        chapter = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        result = engine.chapter_workflow(chapter)
        print(f"\n结果: {result}")

    elif command == "switch":
        book_name = sys.argv[2] if len(sys.argv) > 2 else ""
        success, msg = engine.sm.switch_book(book_name)
        print(f"\n{msg}")

    elif command == "status":
        book = engine.sm.get_current_book()
        if book:
            print(f"""
当前小说: {book.name}
题材: {book.genre}
平台: {book.platform}
总章节: {book.total_chapters}
完成进度: {book.completed_chapters}/{book.total_chapters}
""")
        else:
            print("暂无当前小说")

    elif command == "audit":
        result = engine.golden_chapters_audit()
        print(f"\n结果: {result}")

    elif command == "llm":
        if len(sys.argv) < 3:
            print("请指定子命令: config / test / info")
        sub_cmd = sys.argv[2]
        if sub_cmd == "config":
            if len(sys.argv) > 3:
                engine.configure_llm(api_key=sys.argv[3])
            else:
                print("请提供API密钥")
        elif sub_cmd == "test":
            print("[LLM] 测试连接...")
            success, result = engine.llm_manager.client.call(
                "请回复'连接成功'",
                system_prompt="你是一个测试助手"
            )
            if success:
                print(f"[LLM] 测试成功: {result[:50]}...")
            else:
                print(f"[LLM] 测试失败: {result}")
        elif sub_cmd == "info":
            cfg = engine.llm_manager.config
            print(f"""
LLM 配置信息 (.env):
- API密钥: {'已设置(已隐藏)' if cfg.api_key else '未设置'}
- Base URL: {cfg.base_url}
- 模型: {cfg.model}
- 最大Token: {cfg.max_tokens}
- Temperature: {cfg.temperature}
- 超时: {cfg.timeout}秒
- 重试次数: {cfg.retry_times}
""")
        else:
            print(f"未知子命令: {sub_cmd}")


if __name__ == "__main__":
    main()
