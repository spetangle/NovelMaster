# -*- coding: utf-8 -*-
"""
Agent 职责加载器
从 YAML 文件加载 Agent 职责定义
"""

import yaml
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass
class Dimension:
    """评分维度"""
    name: str
    weight: float = 1.0
    description: str = ""


@dataclass
class AgentRole:
    """Agent 职责定义"""
    name: str                          # 角色名称 (英文)
    name_cn: str = ""                  # 角色中文名
    description: str = ""              # 职责描述
    system_prompt: str = ""           # 系统提示词
    dimensions: List[Dimension] = field(default_factory=list)  # 评分维度
    output_format: str = "text"        # 输出格式: text / json / markdown
    required_fields: List[str] = field(default_factory=list)    # JSON输出必需字段
    workflows: List[str] = field(default_factory=list)           # 关联的工作流
    retry_on_failure: bool = True     # 失败时是否重试
    max_retries: int = 3              # 最大重试次数

    @classmethod
    def from_dict(cls, data: dict) -> 'AgentRole':
        """从字典创建 AgentRole"""
        dimensions = []
        for dim in data.get('dimensions', []):
            if isinstance(dim, dict):
                dimensions.append(Dimension(
                    name=dim.get('name', ''),
                    weight=dim.get('weight', 1.0),
                    description=dim.get('description', '')
                ))
            else:
                dimensions.append(Dimension(name=str(dim)))

        return cls(
            name=data.get('name', ''),
            name_cn=data.get('name_cn', ''),
            description=data.get('description', ''),
            system_prompt=data.get('system_prompt', ''),
            dimensions=dimensions,
            output_format=data.get('output_format', 'text'),
            required_fields=data.get('required_fields', []),
            workflows=data.get('workflows', []),
            retry_on_failure=data.get('retry_on_failure', True),
            max_retries=data.get('max_retries', 3)
        )


class AgentLoader:
    """Agent 职责加载器"""

    def __init__(self, roles_dir: Optional[str] = None):
        if roles_dir:
            self.roles_dir = Path(roles_dir)
        else:
            self.roles_dir = Path(__file__).parent / "roles"

    def load_role(self, role_name: str) -> Optional[AgentRole]:
        """加载单个 Agent 职责"""
        yaml_file = self.roles_dir / f"{role_name}.yaml"
        if not yaml_file.exists():
            yaml_file = self.roles_dir / f"{role_name}.yml"

        if not yaml_file.exists():
            return None

        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            return AgentRole.from_dict(data)
        except Exception as e:
            print(f"[AgentLoader] 加载职责 {role_name} 失败: {e}")
            return None

    def load_all_roles(self) -> Dict[str, AgentRole]:
        """加载所有 Agent 职责"""
        roles = {}
        if not self.roles_dir.exists():
            return roles

        for yaml_file in self.roles_dir.glob("*.yaml"):
            role_name = yaml_file.stem
            role = self.load_role(role_name)
            if role:
                roles[role_name] = role

        for yaml_file in self.roles_dir.glob("*.yml"):
            role_name = yaml_file.stem
            if role_name not in roles:  # 避免重复
                role = self.load_role(role_name)
                if role:
                    roles[role_name] = role

        return roles

    def reload_roles(self) -> Dict[str, AgentRole]:
        """热重载所有职责"""
        return self.load_all_roles()


def load_all_roles() -> Dict[str, AgentRole]:
    """快捷函数：加载所有职责"""
    loader = AgentLoader()
    return loader.load_all_roles()