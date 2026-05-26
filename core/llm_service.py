# -*- coding: utf-8 -*-
"""
LLM服务封装
包含配置、客户端、管理器等
"""

import json
import time
from typing import Optional, Dict, Tuple, List
from pathlib import Path
from dataclasses import dataclass, field


# ============== LLM 配置 ==============

@dataclass
class LLMConfig:
    """大模型配置"""
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    max_tokens: int = 8192
    temperature: float = 0.7
    timeout: int = 600  # 默认10分钟超时
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
                        config.timeout = int(value) if value else 600
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


# ============== LLM 客户端 ==============

class LLMClient:
    """大模型调用客户端"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()

    def call(
        self,
        prompt: str,
        system_prompt: str = "",
        json_mode: bool = False,
        **kwargs
    ) -> Tuple[bool, str]:
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


# ============== LLM 管理器 ==============

class LLMManager:
    """大模型管理器"""

    DEFAULT_CONFIG_PATH = ".env"

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.config = self._load_config()
        self.client = LLMClient(self.config)
        self._token_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _load_config(self):
        """加载配置（支持多提供商JSON格式）"""
        if Path(self.config_path).exists():
            return MultiProviderLLMConfig.from_env_json(self.config_path)
        return MultiProviderLLMConfig()

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
        """生成内容"""
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


# ============== LLM 服务（原 LLMService 类） ==============


@dataclass
class ProviderConfig:
    """单个大模型提供商配置"""
    id: str = ""
    name: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    max_tokens: int = 8192
    temperature: float = 0.7
    timeout: int = 600  # 默认10分钟超时
    retry_times: int = 3
    retry_delay: float = 2.0
    enabled: bool = True
    is_default: bool = False
    stream: bool = False  # 是否启用流式输出
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "retry_times": self.retry_times,
            "retry_delay": self.retry_delay,
            "enabled": self.enabled,
            "is_default": self.is_default,
            "stream": self.stream
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ProviderConfig':
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url", ""),
            model=data.get("model", ""),
            max_tokens=data.get("max_tokens", 8192),
            temperature=data.get("temperature", 0.7),
            timeout=data.get("timeout", 600),
            retry_times=data.get("retry_times", 3),
            retry_delay=data.get("retry_delay", 2.0),
            enabled=data.get("enabled", True),
            is_default=data.get("is_default", False),
            stream=data.get("stream", False)
        )


class MultiProviderLLMConfig:
    """大模型配置（支持多提供商）"""
    
    # 内置提供商模板
    PROVIDER_TEMPLATES = {
        "deepseek": {
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-coder"]
        },
        "openai": {
            "name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-4o-mini",
            "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]
        },
        "anthropic": {
            "name": "Anthropic (Claude)",
            "base_url": "https://api.anthropic.com/v1",
            "default_model": "claude-3-5-sonnet-20241022",
            "models": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"]
        },
        "zhipu": {
            "name": "智谱AI",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "default_model": "glm-4",
            "models": ["glm-4", "glm-4-flash", "glm-4-plus", "glm-3-turbo"]
        },
        "qwen": {
            "name": "通义千问",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "default_model": "qwen-turbo",
            "models": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-max-longcontext"]
        },
        "yi": {
            "name": "零一万物",
            "base_url": "https://api.lingyiwanwu.com/v1",
            "default_model": "yi-medium",
            "models": ["yi-ultra", "yi-large", "yi-medium", "yi-medium-200k"]
        },
        "moonshot": {
            "name": "月之暗面 (Kimi)",
            "base_url": "https://api.moonshot.cn/v1",
            "default_model": "moonshot-v1-8k",
            "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]
        },
        "siliconflow": {
            "name": "SiliconFlow",
            "base_url": "https://api.siliconflow.cn/v1",
            "default_model": "Qwen/Qwen2.5-7B-Instruct",
            "models": ["Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V2.5", "THUDM/glm-4-9b-chat"]
        },
        "custom": {
            "name": "自定义",
            "base_url": "",
            "default_model": "",
            "models": []
        }
    }
    
    def __init__(self):
        self.providers: List[ProviderConfig] = []
        self.active_provider_id: str = ""
    
    def get_active_provider(self) -> Optional[ProviderConfig]:
        """获取当前激活的提供商"""
        if not self.providers:
            return None
        for p in self.providers:
            if p.id == self.active_provider_id and p.enabled:
                return p
        # 返回默认启用的提供商
        for p in self.providers:
            if p.enabled:
                return p
        return self.providers[0] if self.providers else None
    
    def get_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        """根据ID获取提供商"""
        for p in self.providers:
            if p.id == provider_id:
                return p
        return None
    
    def add_provider(self, provider: ProviderConfig) -> bool:
        """添加提供商"""
        # 检查ID是否已存在
        for i, p in enumerate(self.providers):
            if p.id == provider.id:
                self.providers[i] = provider
                return True
        self.providers.append(provider)
        return True
    
    def remove_provider(self, provider_id: str) -> bool:
        """移除提供商"""
        self.providers = [p for p in self.providers if p.id != provider_id]
        if self.active_provider_id == provider_id and self.providers:
            self.active_provider_id = self.providers[0].id
        return True
    
    def set_active(self, provider_id: str) -> bool:
        """设置激活的提供商"""
        provider = self.get_provider(provider_id)
        if provider and provider.enabled:
            self.active_provider_id = provider_id
            return True
        return False
    
    def to_dict(self) -> dict:
        return {
            "providers": [p.to_dict() for p in self.providers],
            "active_provider_id": self.active_provider_id
        }
    
    def is_configured(self) -> bool:
        """检查是否已配置至少一个有效的提供商"""
        return self.get_active_provider() is not None and bool(self.get_active_provider().api_key)
    
    # 向后兼容方法
    @property
    def api_key(self) -> str:
        p = self.get_active_provider()
        return p.api_key if p else ""
    
    @property
    def base_url(self) -> str:
        p = self.get_active_provider()
        return p.base_url if p else ""
    
    @property
    def model(self) -> str:
        p = self.get_active_provider()
        return p.model if p else ""
    
    @property
    def max_tokens(self) -> int:
        p = self.get_active_provider()
        return p.max_tokens if p else 8192
    
    @property
    def temperature(self) -> float:
        p = self.get_active_provider()
        return p.temperature if p else 0.7
    
    @property
    def timeout(self) -> int:
        p = self.get_active_provider()
        return p.timeout if p else 600
    
    @property
    def retry_times(self) -> int:
        p = self.get_active_provider()
        return p.retry_times if p else 3
    
    @property
    def retry_delay(self) -> float:
        p = self.get_active_provider()
        return p.retry_delay if p else 2.0
    
    @property
    def stream(self) -> bool:
        """是否启用流式输出"""
        p = self.get_active_provider()
        return p.stream if p else False

    @classmethod
    def from_env(cls, path: str = ".env") -> 'LLMConfig':
        """从 .env 文件加载配置（兼容旧格式）"""
        env_path = Path(path)
        config = cls()
        
        if not env_path.exists():
            return config
        
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # 兼容旧的单提供商格式
                    if key == "LLM_API_KEY" and not config.providers:
                        provider = ProviderConfig(
                            id="default",
                            name="默认",
                            api_key=value,
                            base_url="https://api.deepseek.com/v1",
                            model="deepseek-chat",
                            is_default=True
                        )
                        config.providers.append(provider)
                        config.active_provider_id = "default"
                    elif key == "LLM_BASE_URL" and config.providers:
                        config.providers[0].base_url = value
                    elif key == "LLM_MODEL" and config.providers:
                        config.providers[0].model = value
                    elif key == "LLM_MAX_TOKENS" and config.providers:
                        config.providers[0].max_tokens = int(value) if value else 8192
                    elif key == "LLM_TEMPERATURE" and config.providers:
                        config.providers[0].temperature = float(value) if value else 0.7
                    elif key == "LLM_TIMEOUT" and config.providers:
                        config.providers[0].timeout = int(value) if value else 600
                    elif key == "LLM_RETRY_TIMES" and config.providers:
                        config.providers[0].retry_times = int(value) if value else 3
                    elif key == "LLM_RETRY_DELAY" and config.providers:
                        config.providers[0].retry_delay = float(value) if value else 2.0
        
        return config

    def save_env(self, path: str = ".env") -> bool:
        """保存配置到 .env 文件（支持多提供商）"""
        try:
            import json
            lines = [
                "# LLM Configuration (Multi-Provider JSON)",
                f"LLM_CONFIG_JSON={json.dumps(self.to_dict(), ensure_ascii=False)}"
            ]
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            return True
        except Exception:
            return False

    @classmethod
    def from_env_json(cls, path: str = ".env") -> 'LLMConfig':
        """从 .env 文件加载多提供商配置"""
        env_path = Path(path)
        config = cls()
        
        if not env_path.exists():
            return config
        
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("LLM_CONFIG_JSON="):
                    json_str = line.split("=", 1)[1].strip()
                    try:
                        data = json.loads(json_str)
                        providers_data = data.get("providers", [])
                        for p_data in providers_data:
                            provider = ProviderConfig.from_dict(p_data)
                            config.providers.append(provider)
                        config.active_provider_id = data.get("active_provider_id", "")
                    except json.JSONDecodeError:
                        pass
                    break
        
        # 如果没有激活的提供商但有提供商列表，设置第一个为激活
        if not config.active_provider_id and config.providers:
            config.active_provider_id = config.providers[0].id
        
        return config

    @classmethod
    def from_json(cls, path: str = "llm_providers.json") -> 'LLMConfig':
        """从 JSON 文件加载多提供商配置"""
        json_path = Path(path)
        config = cls()
        
        if not json_path.exists():
            # 尝试从 .env 加载
            return cls.from_env(".env")
        
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        providers_data = data.get("providers", [])
        for p_data in providers_data:
            provider = ProviderConfig.from_dict(p_data)
            config.providers.append(provider)
        
        config.active_provider_id = data.get("active_provider_id", "")
        
        # 如果没有激活的提供商但有提供商列表，设置第一个为激活
        if not config.active_provider_id and config.providers:
            config.active_provider_id = config.providers[0].id
        
        return config

    def save_json(self, path: str = "llm_providers.json") -> bool:
        """保存多提供商配置到 JSON 文件"""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False


class LLMService:
    """LLM服务类"""
    
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._token_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self._log_dir: Optional[Path] = None
        self._log_file: Optional[Path] = None
    
    def set_log_dir(self, log_dir: str) -> None:
        """设置日志目录"""
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        # 按日期生成日志文件
        from datetime import datetime
        log_name = datetime.now().strftime("%Y%m%d") + ".log"
        self._log_file = self._log_dir / log_name
    
    def _write_log(self, log_type: str, content: dict) -> None:
        """写入日志"""
        if not self._log_file:
            return
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self._log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{timestamp}] {log_type}\n")
                f.write(f"{'='*60}\n")
                for key, value in content.items():
                    f.write(f"\n--- {key} ---\n")
                    # 限制单条日志长度
                    text = str(value)
                    if len(text) > 5000:
                        text = text[:5000] + "\n... [内容过长已截断]"
                    f.write(text + "\n")
        except Exception:
            pass  # 日志写入失败不影响主流程

    def _clean_content(self, content: str) -> str:
        """清理AI思考过程和元数据标记"""
        import re

        # 1. 过滤<think>...</think>思考过程标签及其内容
        content = re.sub(r'<think>[\s\S]*?</think>', '', content)

        # 2. 过滤XML格式的think标签（如<think>...</think>）
        content = re.sub(r'<think>[\s\S]*?</think>', '', content, flags=re.IGNORECASE)

        # 3. 过滤行号前缀格式（如 "     1|", "    10|" 等）
        content = re.sub(r'^\s*\d+\|\s*', '', content, flags=re.MULTILINE)

        # 4. 清理多余的空行（连续3行以上空行合并为2行）
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

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
- 单章目标字数（见用户输入中的"目标字数"）
- 禁止角色OOC、战力崩坏、信息越界
- 禁止频繁描写外貌（仅首次出现时描写）
- 必须埋设/回收伏笔、推动主线、体现情感弧线
- 禁止AI写作痕迹（重复结构、机械感段落）
- 保持"行动描写（仅允许对话与叙事）"原则

请确保文字流畅有网感，爽点到位。""",

        "auditor": """你是一位专业的小说质量审计师，负责对章节进行全方位质量审查。

请从以下维度审查：
1. 逻辑一致性（战力、行为、时间线）
2. 情感节奏（弧线完整、爽点到位）
3. 伏笔管理（埋设、回收、逻辑通顺）
4. 文风一致性（符合规则、无禁用词）

评分公式：章节得分 = 100 - auditIssues×5 - aiTellDensity×20 - paraWarnings×3
- ≥75分：通过
- 60-74分：修订后通过
- <60分：不通过

请返回JSON格式的审查结果。""",

        "outline_auditor": """你是一位专业的章节细纲审计师，负责在正文创作前审查细纲质量。
你的审查重点在于结构合理性和可行性。

审查维度（各维度满分20分）：
1. 情节结构完整性 (权重25%)：起承转合是否齐全、逻辑通顺
2. 字数分配合理性 (权重30%)：各情节点字数分配是否匹配目标字数
3. 伏笔埋设质量 (权重20%)：伏笔是否合理、可回收
4. 钩子有效性 (权重15%)：结尾钩子是否制造悬念
5. 字数预估准确性 (权重10%)：预估字数是否在目标范围±500字内

通过标准：总分≥75 且 字数分配维度≥12分。

请返回JSON格式评分结果。""",
    }

    def call(
        self,
        prompt: str,
        system_prompt: str = "",
        json_mode: bool = False,
        agent_name: str = "Unknown",
        **kwargs
    ) -> Tuple[bool, str]:
        """调用大模型
        
        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            json_mode: 是否JSON模式
            agent_name: Agent名称（用于日志）
            **kwargs: 支持 timeout（超时秒数）、max_tokens、temperature、model
        """
        import urllib.request
        import urllib.error

        params = {
            "model": kwargs.get("model", self.config.model),
            "messages": [],
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
        }
        # 自定义超时（章节生成等耗时任务可传入更长超时）
        call_timeout = kwargs.get("timeout", self.config.timeout)

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

                with urllib.request.urlopen(req, timeout=call_timeout) as response:
                    result = json.loads(response.read().decode('utf-8'))

                    if "choices" in result and len(result["choices"]) > 0:
                        raw_content = result["choices"][0]["message"]["content"]
                        # 清理AI思考过程和元数据
                        content = self._clean_content(raw_content)
                        # 记录成功日志（使用原始内容用于调试）
                        self._write_log(f"LLM调用成功 [{agent_name}]", {
                            "Agent": agent_name,
                            "Model": params["model"],
                            "System Prompt": system_prompt[:500] if system_prompt else "(无)",
                            "User Prompt": prompt[:2000],
                            "Response (raw)": raw_content[:3000]
                        })
                        return True, content

                # 记录失败日志
                self._write_log(f"LLM响应异常 [{agent_name}]", {
                    "Agent": agent_name,
                    "Model": params["model"],
                    "Response": str(result)
                })
                return False, "响应格式异常"

            except urllib.error.URLError as e:
                if attempt < self.config.retry_times - 1:
                    time.sleep(self.config.retry_delay)
                    continue
                # 记录网络错误日志
                self._write_log(f"LLM网络错误 [{agent_name}]", {
                    "Agent": agent_name,
                    "Model": params["model"],
                    "Error": f"网络错误: {str(e)}",
                    "Attempt": attempt + 1
                })
                return False, f"网络错误: {str(e)}"
            except Exception as e:
                # 记录异常日志
                self._write_log(f"LLM调用异常 [{agent_name}]", {
                    "Agent": agent_name,
                    "Model": params["model"],
                    "Error": f"调用失败: {str(e)}"
                })
                return False, f"调用失败: {str(e)}"

        self._write_log(f"LLM重试耗尽 [{agent_name}]", {
            "Agent": agent_name,
            "Model": params["model"],
            "Retries": self.config.retry_times
        })
        return False, "重试次数耗尽"

    def call_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        agent_name: str = "Unknown",
        callback=None,
        **kwargs
    ):
        """流式调用大模型
        
        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            agent_name: Agent名称（用于日志）
            callback: 回调函数，接收每个chunk的文本
        """
        import urllib.request
        import urllib.error

        params = {
            "model": kwargs.get("model", self.config.model),
            "messages": [],
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "stream": True,  # 启用流式
        }

        if system_prompt:
            params["messages"].append({"role": "system", "content": system_prompt})
        params["messages"].append({"role": "user", "content": prompt})

        payload = json.dumps(params).encode('utf-8')
        
        full_content = []

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
                    # 流式读取响应
                    for line in response:
                        line = line.decode('utf-8').strip()
                        if not line or line == "data: [DONE]":
                            continue
                        if line.startswith("data: "):
                            line = line[6:]  # 去掉 "data: " 前缀
                        try:
                            data = json.loads(line)
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    chunk = delta["content"]
                                    full_content.append(chunk)
                                    if callback:
                                        callback(chunk)
                        except json.JSONDecodeError:
                            continue
                
                # 流式完成
                raw_content = "".join(full_content)
                # 清理AI思考过程和元数据
                content = self._clean_content(raw_content)

                # 记录成功日志（使用原始内容用于调试）
                self._write_log(f"LLM流式调用成功 [{agent_name}]", {
                    "Agent": agent_name,
                    "Model": params["model"],
                    "Stream": True,
                    "System Prompt": system_prompt[:500] if system_prompt else "(无)",
                    "User Prompt": prompt[:2000],
                    "Response Length (raw)": len(raw_content),
                    "Response Length (cleaned)": len(content)
                })
                return True, content

            except urllib.error.URLError as e:
                if attempt < self.config.retry_times - 1:
                    time.sleep(self.config.retry_delay)
                    continue
                self._write_log(f"LLM流式网络错误 [{agent_name}]", {
                    "Agent": agent_name,
                    "Model": params["model"],
                    "Error": f"网络错误: {str(e)}"
                })
                return False, f"网络错误: {str(e)}"
            except Exception as e:
                self._write_log(f"LLM流式调用异常 [{agent_name}]", {
                    "Agent": agent_name,
                    "Model": params["model"],
                    "Error": f"调用失败: {str(e)}"
                })
                return False, f"调用失败: {str(e)}"

        return False, "重试次数耗尽"

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        agent_name: str = "System",
        max_tokens: int = None,
        timeout: int = None
    ) -> str:
        """生成内容
        
        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            agent_name: Agent名称（用于日志）
            max_tokens: 最大输出token数
            timeout: 超时秒数（None则使用全局配置）
        """
        if not self.config.api_key:
            return "[LLM未配置API密钥]"
        
        kwargs = dict(agent_name=agent_name)
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if timeout is not None:
            kwargs["timeout"] = timeout
        
        success, result = self.call(prompt, system_prompt, **kwargs)
        if success:
            return result
        return f"[生成失败: {result}]"

    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        agent_name: str = "System",
        callback=None
    ) -> str:
        """流式生成内容"""
        if not self.config.api_key:
            return "[LLM未配置API密钥]"
        
        success, result = self.call_stream(prompt, system_prompt, agent_name, callback)
        if success:
            return result
        return f"[生成失败: {result}]"

    def generate_json(
        self,
        prompt: str,
        system_prompt: str = "",
        agent_name: str = "System"
    ) -> Optional[Dict]:
        """生成JSON格式响应"""
        success, result = self.call(prompt, system_prompt, json_mode=True, agent_name=agent_name)

        if success:
            try:
                text = result.strip()
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                return json.loads(text.strip())
            except json.JSONDecodeError:
                return None
        return None

    def get_system_prompt(self, agent: str) -> str:
        """获取系统提示词"""
        return self.SYSTEM_PROMPTS.get(agent, "")
