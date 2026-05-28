# -*- coding: utf-8 -*-
"""
Agent 引擎
管理所有 Agent 实例和工作流执行
"""

from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field

from .loader import AgentLoader, AgentRole
from .base import UniversalAgent, AgentResult


@dataclass
class WorkflowStep:
    """工作流步骤"""
    role: str
    on_failure: str = "abort"      # abort / skip / retry
    params: Dict[str, Any] = field(default_factory=dict)
    retry: int = 0                 # 重试次数
    condition: str = ""             # 执行条件


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    success: bool = False
    steps: List[AgentResult] = field(default_factory=list)
    message: str = ""
    data: Optional[Dict] = None
    workflow_name: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "steps": [s.to_dict() for s in self.steps],
            "message": self.message,
            "data": self.data,
            "workflow_name": self.workflow_name
        }


class AgentEngine:
    """Agent 引擎 - 管理所有 Agent 调用"""

    def __init__(self, llm_manager=None, roles_dir: Optional[str] = None):
        self.llm = llm_manager
        self.loader = AgentLoader(roles_dir)
        self.agents: Dict[str, UniversalAgent] = {}
        self._init_agents()

    def _init_agents(self):
        """初始化所有 Agent 实例"""
        roles = self.loader.load_all_roles()
        for name, role in roles.items():
            self.agents[name] = UniversalAgent(role, self.llm)

    def call_agent(self, role_name: str, context: dict) -> AgentResult:
        """
        调用指定角色的 Agent

        Args:
            role_name: Agent 角色名称
            context: 上下文字典

        Returns:
            AgentResult: 执行结果
        """
        print(f"[Agent] {role_name} 开始执行...")
        agent = self.agents.get(role_name)
        if not agent:
            print(f"[Agent] {role_name} 未找到")
            return AgentResult(
                success=False,
                error=f"未找到 Agent 角色: {role_name}",
                agent_name=role_name
            )

        if not self.llm:
            agent.set_llm(self.llm)

        try:
            result = agent.execute(context)
            print(f"[Agent] {role_name} 执行完成: success={result.success}, content长度={len(result.content) if result.content else 0}, data={bool(result.data)}")
            return result
        except Exception as e:
            print(f"[Agent] {role_name} 执行异常: {e}")
            import traceback
            traceback.print_exc()
            return AgentResult(
                success=False,
                error=f"执行异常: {str(e)}",
                agent_name=role_name
            )

    def get_agent(self, role_name: str) -> Optional[UniversalAgent]:
        """获取指定 Agent"""
        return self.agents.get(role_name)

    def get_role(self, role_name: str) -> Optional[AgentRole]:
        """获取指定角色定义"""
        return self.loader.load_role(role_name)

    def reload(self):
        """重新加载 Agent 职责"""
        self._init_agents()

    def execute_workflow(self, workflow_name: str, context: dict,
                       workflow_config: List[Dict]) -> WorkflowResult:
        """
        执行工作流

        Args:
            workflow_name: 工作流名称
            context: 初始上下文
            workflow_config: 工作流配置 [dict with role, on_failure, params, retry]

        Returns:
            WorkflowResult: 工作流执行结果
        """
        result = WorkflowResult(workflow_name=workflow_name)

        # 深拷贝上下文，避免修改原始数据
        current_context = dict(context)

        for i, step_config in enumerate(workflow_config):
            role = step_config.get('role')
            on_failure = step_config.get('on_failure', 'abort')
            params = step_config.get('params', {})
            retry = step_config.get('retry', 0)

            if not role:
                continue

            # 更新上下文参数
            if params:
                current_context.update(params)

            # 执行 Agent
            step_result = self._execute_with_retry(role, current_context, retry)
            result.steps.append(step_result)

            # 处理失败情况
            if not step_result.success:
                if on_failure == 'abort':
                    result.message = f"步骤 {i+1} ({role}) 执行失败，终止工作流"
                    return result
                elif on_failure == 'skip':
                    result.message = f"步骤 {i+1} ({role}) 执行失败，已跳过"
                    continue
                elif on_failure == 'retry':
                    # 重试已在上面处理
                    pass

            # 将结果添加到上下文，供下一步使用
            if step_result.content:
                current_context[f"{role}_result"] = step_result.content
            if step_result.data:
                current_context[f"{role}_data"] = step_result.data

        # 所有步骤都成功
        result.success = all(s.success for s in result.steps)
        result.message = "工作流执行完成" if result.success else "工作流执行部分成功"
        result.data = current_context

        return result

    def _execute_with_retry(self, role: str, context: dict, max_retries: int) -> AgentResult:
        """执行带重试的 Agent"""
        last_result = None

        for attempt in range(max_retries + 1):
            result = self.call_agent(role, context)
            last_result = result

            if result.success:
                return result

            # 非最终尝试，打印日志
            if attempt < max_retries:
                print(f"[AgentEngine] {role} 执行失败，尝试重试 ({attempt+1}/{max_retries})")

        return last_result or AgentResult(
            success=False,
            error=f"重试 {max_retries} 次后仍失败",
            agent_name=role
        )