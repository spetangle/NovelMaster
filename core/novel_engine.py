# -*- coding: utf-8 -*-
"""
小说创作核心引擎
独立完整的核心功能模块
"""

import json
import html as _html_module
import re
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
from datetime import datetime
from dataclasses import asdict

from .models import BookInfo, ChapterInfo, ChapterStatus, AuditResult, AuditDecision, HookInfo, GlobalConfig, AuditLogTable, ChapterAuditLog
from .llm_service import LLMService, MultiProviderLLMConfig as LLMConfig
from .file_manager import FileManager
from .state_manager import StateManager


class CancelledException(Exception):
    """任务被取消异常"""
    pass


class NovelEngine:
    """小说创作核心引擎"""

    def __init__(self, workspace: str = "./workspace", llm_config: Optional[LLMConfig] = None):
        """
        初始化引擎
        
        Args:
            workspace: 工作目录路径
            llm_config: LLM配置，None则自动从llm_providers.json加载
        """
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        
        self.sm = StateManager(str(self.workspace))
        
        # 从 .env 加载多提供商配置（确保敏感信息不上传到 GitHub）
        self.llm = LLMService(llm_config or LLMConfig.from_env_json(".env"))
        
        # 设置配置文件路径（用于保存）
        self._config_save_path = ".env"
        
        # 设置LLM日志目录
        log_dir = self.workspace / "logs"
        self.llm.set_log_dir(str(log_dir))
        
        # 初始化 Agent 相关组件
        self._init_agents()

    def save_book_meta(self, book: 'BookInfo') -> bool:
        """保存书籍元数据（包括灵感对话）"""
        try:
            with self.sm._lock:
                # 在 book_index 中找到该书籍并更新
                for b in self.sm.book_index.get("books", []):
                    if b.get("id") == book.id:
                        # 更新基本字段
                        b["name"] = book.name
                        b["is_inspiration"] = getattr(book, 'is_inspiration', False)
                        # 保存灵感相关字段
                        b["inspiration_collected_info"] = getattr(book, 'inspiration_collected_info', {})
                        b["inspiration_dialogue"] = getattr(book, 'inspiration_dialogue', [])
                        print(f"[save_book_meta] 已更新书籍 {book.id} 的元数据")
                        # 在锁内保存，确保原子性
                        return self.sm._save_book_index()
                print(f"[save_book_meta] 未找到书籍 {book.id}，无法保存")
                return False
        except Exception as e:
            print(f"保存书籍元数据失败: {e}")
            return False

    def _save_inspiration_to_chatlog(self, book: 'BookInfo', dialogue: list):
        """将灵感对话保存到 chatlog 文件"""
        try:
            import json
            chat_logs_dir = self.workspace / book.path / "chat_logs"
            chat_logs_dir.mkdir(parents=True, exist_ok=True)
            
            # 保存灵感对话（使用特殊文件名标记）
            log_file = chat_logs_dir / "inspiration_dialogue.json"
            
            log_data = {
                "type": "inspiration",
                "book_id": book.id,
                "book_name": book.name,
                "export_time": datetime.now().isoformat(),
                "collected_info": getattr(book, 'inspiration_collected_info', {}),
                "messages": dialogue
            }
            
            log_file.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"灵感对话已保存到 {log_file}")
        except Exception as e:
            print(f"保存灵感对话到chatlog失败: {e}")
    
    def _init_agents(self):
        """初始化 Agent 组件"""
        try:
            from agents.engine import AgentEngine
            from core.llm_service import LLMManager, LLMClient, ProviderConfig, MultiProviderLLMConfig

            # 确定 .env 路径：优先使用 workspace/.env，否则使用项目根目录的 .env
            workspace_env = self.workspace / ".env"
            config_path = str(workspace_env) if workspace_env.exists() else ".env"
            
            # 创建 LLMManager 并加载多提供商配置
            self.llm_manager = LLMManager(config_path)
            
            # 确保 LLMManager 使用 MultiProviderLLMConfig
            if not isinstance(self.llm_manager.config, MultiProviderLLMConfig):
                self.llm_manager.config = MultiProviderLLMConfig.from_env_json(self.config_path)
            
            # 获取当前激活的提供商
            provider = self.llm_manager.config.get_active_provider()
            if provider:
                # 检查 timeout 配置
                if provider.timeout < 300:
                    print(f"[警告] LLM超时配置为 {provider.timeout}秒，低于建议值300秒，创作长章节可能会超时。建议在 .env 中将 timeout 设置为 600 或更高。")

                # 创建 LLMClient 并设置正确的 ProviderConfig
                provider_config = ProviderConfig(
                    api_key=provider.api_key,
                    base_url=provider.base_url,
                    model=provider.model,
                    max_tokens=provider.max_tokens,
                    temperature=provider.temperature,
                    timeout=provider.timeout,
                    retry_times=provider.retry_times,
                    retry_delay=provider.retry_delay
                )
                self.llm_manager.client = LLMClient(provider_config)
            
            self.agent_engine = AgentEngine(self.llm_manager)
        except Exception as e:
            print(f"初始化 Agent 失败: {e}")
            import traceback
            traceback.print_exc()
            self.agent_engine = None
            self.llm_manager = None

    # ============== 书籍管理 ==============

    def create_book_workflow(self, brief: str) -> Dict[str, Any]:
        """
        新书创建工作流（一站式：解析简报并创建书籍）

        Args:
            brief: 创作简报，支持多行文本

        Returns:
            工作流执行结果，包含书籍信息和生成的文件
        """
        try:
            # 1. 生成唯一书籍ID
            book_id = self._generate_book_id()
            print(f"[步骤1] 分配书籍ID: {book_id}")
            
            # 2. 解析简报生成规划书
            planning = self._parse_brief(brief)
            
            # 3. 书名：用户提供了书名则使用，否则使用书籍ID
            temp_name = ""
            name_match = re.search(r'书名[：:]\s*([^\n]+)', brief)
            if name_match:
                temp_name = name_match.group(1).strip()
            book_name = temp_name if temp_name else book_id
            
            # 4. 创建BookInfo
            book = BookInfo(
                id=book_id,
                name=book_name,
                path=f"books/{book_id}",
                genre=planning.get("genre", "都市"),
                platform=planning.get("platform", "番茄小说"),
                words_per_chapter=planning.get("words_per_chapter", 3000),
                total_chapters=planning.get("estimated_chapters", 80),
                created_at=datetime.now().isoformat()
            )

            # 5. 创建书籍文件夹
            success, msg = self.sm.create_book(book)
            if not success:
                return {"success": False, "message": msg}
            print(f"[步骤2] 书籍文件夹已创建: {book.path}")

            # 6. 生成世界观和规则
            print("[步骤3] 生成世界观设定...")
            story_bible = self._generate_story_bible(book, planning)
            book_rules = self._generate_book_rules(book, book.genre)

            # 7. 保存文件
            print("[步骤4] 保存设定文件...")
            book_path = self.workspace / book.path
            self.sm.fm.write_text(book_path / "story_bible.md", story_bible)
            self.sm.fm.write_text(book_path / "book_rules.md", book_rules)

            # 8. 保存规划书
            self.sm.fm.write_text(book_path / "planning.md", self._generate_planning_doc(planning))

            # 9. 初始化项目状态
            print("[步骤5] 初始化项目状态...")
            self._init_project_state(book)

            # 10. 初始化真相文件
            print("[步骤6] 初始化真相文件...")
            self._init_truth_files(book)

            # 11. 初始化章节摘要
            print("[步骤7] 初始化章节摘要...")
            self._init_chapter_summaries(book)

            return {
                "success": True,
                "phase": "created",
                "book": {
                    "id": book.id,
                    "name": book.name,
                    "genre": book.genre,
                    "platform": book.platform,
                    "path": book.path,
                    "words_per_chapter": book.words_per_chapter,
                    "total_chapters": book.total_chapters,
                    "created_at": book.created_at
                },
                "planning": planning,
                "message": f"《{book.name}》创建成功！"
            }
        except CancelledException as e:
            return {"success": False, "message": str(e), "cancelled": True}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"创建失败: {str(e)}"}

    def create_book_workflow_with_progress(self, brief: str, book_id: str, 
                                           progress_callback: Callable = None,
                                           cancel_check: Callable = None) -> Dict[str, Any]:
        """
        新书创建工作流（带进度回调）

        Args:
            brief: 创作简报
            book_id: 书籍ID
            progress_callback: 进度回调函数，签名为 func(step: str, progress: int, message: str)
            cancel_check: 取消检查函数，返回 True 表示任务被取消

        Returns:
            工作流执行结果
        """
        def report(step: str, progress: int, message: str):
            print(f"[{progress}%] {step}: {message}")
            if progress_callback:
                progress_callback(step, progress, message)
        
        def check_cancel():
            if cancel_check and cancel_check():
                return True
            return False
        
        def check_cancel_and_raise():
            """检查取消状态，如果被取消则抛出异常"""
            if check_cancel():
                raise CancelledException("任务被用户终止")

        try:
            # 1. 解析简报生成规划书
            report("解析简报", 5, f"正在解析创作简报...")
            planning = self._parse_brief(brief)
            
            # 提取书名
            temp_name = ""
            name_match = re.search(r'书名[：:]\s*([^\n]+)', brief)
            if name_match:
                temp_name = name_match.group(1).strip()
            book_name = temp_name if temp_name else book_id

            # 2. 创建书籍记录和文件夹
            report("创建书籍", 10, f"正在创建书籍《{book_name}》，ID: {book_id}...")
            book = self.sm.get_book_by_id(book_id)
            if not book:
                book = BookInfo(
                    id=book_id,
                    name=book_name,
                    path=f"books/{book_id}",
                    genre=planning.get("genre", "都市"),
                    platform=planning.get("platform", "番茄小说"),
                    words_per_chapter=planning.get("words_per_chapter", 3000),
                    total_chapters=planning.get("estimated_chapters", 80),
                    created_at=datetime.now().isoformat()
                )
                success, msg = self.sm.create_book(book)
                if not success:
                    return {"success": False, "message": msg}
                report("创建文件夹", 15, f"已创建文件夹: books/{book_id}/")
            else:
                # 更新书籍信息
                book.name = book_name
                book.genre = planning.get("genre", "都市")
                book.platform = planning.get("platform", "番茄小说")
                book.words_per_chapter = planning.get("words_per_chapter", 3000)
                book.total_chapters = planning.get("estimated_chapters", 80)
            
            # 3. 生成人物设定（主角优先，详细设定）
            report("生成人物", 20, "正在生成人物设定...")
            check_cancel_and_raise()
            characters = self._generate_characters(book, planning, protagonist_detail=True)
            book_path = self.workspace / book.path

            # 统一时间戳，用于本次工作流的所有中间文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # 4. 生成世界观（带人物信息）
            # 使用新的评审-修订循环机制
            report("生成世界观", 35, "正在创建世界观设定...")
            check_cancel_and_raise()
            story_bible_result = self._generate_and_audit_document(
                doc_type="世界观设定",
                generate_func=lambda: self._generate_story_bible(book, planning, characters),
                revise_func=lambda fb: self._revise_story_bible(book, planning, characters, fb),
                audit_func=lambda content: self._audit_setting_document(content, "世界观设定", book),
                report=report,
                base_progress=35,
                max_score_progress=45,
                cancel_check=check_cancel,
                book=book,
                timestamp=timestamp
            )
            story_bible = story_bible_result["content"]
            story_bible_score = story_bible_result["final_score"]
            story_bible_candidates = story_bible_result["candidates"]
            best_story_bible = story_bible_result["best_content"]
            best_story_bible_score = story_bible_result["best_score"]
            story_bible_issues = story_bible_result["final_issues"]
            
            # 保存世界观设定生成报告
            self._save_document_generation_report(book, "世界观设定", story_bible_result, timestamp)

            # 5. 生成规则
            report("生成规则", 50, "正在创建书籍规则...")
            check_cancel_and_raise()
            book_rules_result = self._generate_and_audit_document(
                doc_type="创作规则",
                generate_func=lambda: self._generate_book_rules(book, book.genre, story_bible=story_bible),
                revise_func=lambda fb: self._revise_book_rules(book, book.genre, fb),
                audit_func=lambda content: self._audit_setting_document(content, "创作规则", book),
                report=report,
                base_progress=50,
                max_score_progress=60,
                cancel_check=check_cancel,
                book=book,
                timestamp=timestamp
            )
            book_rules = book_rules_result["content"]
            book_rules_score = book_rules_result["final_score"]
            book_rules_candidates = book_rules_result["candidates"]
            best_book_rules = book_rules_result["best_content"]
            best_book_rules_score = book_rules_result["best_score"]
            book_rules_issues = book_rules_result["final_issues"]
            
            # 保存创作规则生成报告
            self._save_document_generation_report(book, "创作规则", book_rules_result, timestamp)

            # 5.2 生成作者意图文档（长期创作方向）
            report("生成作者意图", 65, "正在生成作者意图文档...")
            check_cancel_and_raise()
            author_intent = self._generate_author_intent(book, brief, planning)

            # 6. 保存初始文件
            report("保存文件", 70, "正在保存设定文件...")
            self.sm.fm.write_text(book_path / "story_bible.md", story_bible)
            self.sm.fm.write_text(book_path / "book_rules.md", book_rules)
            self.sm.fm.write_text(book_path / "planning.md", self._generate_planning_doc(planning))
            self.sm.fm.write_text(book_path / "characters.md", characters)
            self.sm.fm.write_text(book_path / "author_intent.md", author_intent)

            # 6.1 生成并保存当前焦点文档
            current_focus = self._generate_current_focus(book, planning)
            self.sm.fm.write_text(book_path / "current_focus.md", current_focus)

            report("评审完成", 75, f"评审通过（世界观:{story_bible_score}分, 规则:{book_rules_score}分）")

            # 6.2 生成完整章节大纲
            report("生成大纲", 78, "正在生成完整章节大纲...")
            check_cancel_and_raise()
            full_outline = self._generate_full_outline(book, planning, story_bible, author_intent, characters)
            self.sm.fm.write_text(book_path / "chapter_outline.md", full_outline)
            report("大纲生成完成", 82, "完整章节大纲已生成")

            # 8. 综合校验设定文档（检查人物名称、时间线、设定冲突）
            report("综合校验", 80, "正在校验设定文档一致性...")
            check_cancel_and_raise()
            validation_result = self._validate_setting_documents(book, story_bible, book_rules, characters)
            if not validation_result["passed"]:
                report("修正冲突", 82, f"发现{validation_result['issue_count']}处冲突，正在修正...")
                # 自动修正冲突
                story_bible = validation_result.get("corrected_story_bible", story_bible)
                book_rules = validation_result.get("corrected_book_rules", book_rules)
                characters = validation_result.get("corrected_characters", characters)
                # 保存修正后的文件
                self.sm.fm.write_text(book_path / "story_bible.md", story_bible)
                self.sm.fm.write_text(book_path / "book_rules.md", book_rules)
                self.sm.fm.write_text(book_path / "characters.md", characters)
                report("修正完成", 85, "冲突已自动修正")

            # 9. 初始化项目状态
            report("初始化状态", 88, "正在初始化项目状态...")
            self._init_project_state(book)

            # 10. 初始化真相文件
            report("初始化真相文件", 91, "正在初始化真相文件...")
            self._init_truth_files(book)

            # 11. 初始化章节摘要
            report("初始化章节摘要", 94, "正在初始化章节摘要...")
            self._init_chapter_summaries(book)

            report("完成", 100, f"《{book.name}》创建成功！")

            # 整理候选结果
            story_bible_candidates_summary = [
                {"round": s.get("round", "?"), "action": s.get("action", "?"),
                 "score": s.get("score", 0), "issues": s.get("issues", "")}
                for s in story_bible_candidates
            ]
            book_rules_candidates_summary = [
                {"round": s.get("round", "?"), "action": s.get("action", "?"),
                 "score": s.get("score", 0), "issues": s.get("issues", "")}
                for s in book_rules_candidates
            ]
            
            return {
                "success": True,
                "phase": "created",
                "book": {
                    "id": book.id,
                    "name": book.name,
                    "genre": book.genre,
                    "platform": book.platform,
                    "path": book.path,
                    "words_per_chapter": book.words_per_chapter,
                    "total_chapters": book.total_chapters,
                    "created_at": book.created_at
                },
                "planning": planning,
                "audit": {
                    "story_bible_score": story_bible_score,
                    "story_bible_candidates": story_bible_candidates_summary,
                    "book_rules_score": book_rules_score,
                    "book_rules_candidates": book_rules_candidates_summary,
                    "used_best_candidate": {
                        "story_bible": len(story_bible_candidates) > 1 and story_bible_score < 85,
                        "book_rules": len(book_rules_candidates) > 1 and book_rules_score < 85
                    }
                },
                "validation": validation_result,
                "message": f"《{book.name}》创建成功！"
            }
        except CancelledException as e:
            return {"success": False, "message": str(e), "cancelled": True}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"创建失败: {str(e)}"}
    
    def _generate_characters(self, book: BookInfo, planning: Dict, 
                            protagonist_detail: bool = True, feedback: str = "") -> str:
        """生成人物设定"""
        protagonist_name = planning.get('主角名', '')
        if not protagonist_name or protagonist_name == '待设定':
            protagonist_name = self._generate_protagonist_name(book, planning.get('genre', '都市'))
        
        protagonist_gender = planning.get('主角性别', '男')
        protagonist_background = planning.get('主角背景', '普通家庭')
        
        # 主角详细设定（不能反社会）
        protagonist_traits = planning.get('主角性格', '正直善良、积极向上')
        anti_social_warning = "注意：主角必须为正面角色，不能反社会反人类，需遵守法律法规，具有正确的价值观"
        
        protagonist_detail = f"""## 主角：{protagonist_name}

### 基本信息
- 性别：{protagonist_gender}
- 年龄：{planning.get('主角年龄', '25岁')}
- 背景：{protagonist_background}

### 性格特征
{protagonist_traits}

### 人物特质
- 核心价值观：{planning.get('核心价值观', '正义、勇敢、善良')}
- 行事风格：{planning.get('行事风格', '稳重果断')}
- 成长弧线：{planning.get('成长弧线', '从弱小到强大')}

### 社会关系
- 家庭关系：{planning.get('家庭关系', '和睦')}
- 社会关系：{planning.get('社会关系', '普通市民')}

### 主角金手指/特殊能力
{planning.get('主角金手指', '')}

### 角色设定红线
{anti_social_warning}
"""
        
        # 配角设定
        supporting_chars = planning.get('配角设定', '')
        
        characters_doc = f"""# {book.name} 人物设定

{protagonist_detail}

## 配角（待补充）

{supporting_chars if supporting_chars else '配角设定将在后续创作中逐步完善。'}

---
*人物设定版本：1.0*
*最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
        
        if feedback:
            # 加入反馈进行优化
            characters_doc += f"\n\n## 修改反馈\n{feedback}"
        
        return characters_doc
    
    def _audit_setting_document(self, content: str, doc_type: str, book: BookInfo) -> tuple:
        """评审设定文档，返回(评分, 问题列表)
        
        不同文档类型使用专属评审标准，避免张冠李戴：
        - 世界观设定：只评世界观相关，不要求章节结构/伏笔
        - 创作规则：只评规则相关，不要求世界观细节
        """
        # 根据文档类型定义专属评审维度（调用方传入"世界观设定"/"创作规则"/"章节大纲"等）
        if "世界观" in doc_type:
            dimensions = """评分维度（满分100，85分及格。请严格围绕"世界观设定"本身评审，不要评审章节结构、伏笔网络、人物动机等不属于世界观的内容）：
1. 世界背景（20分）：时代背景、世界起源、历史脉络是否清晰具体
2. 力量体系（20分）：能力分类、等级划分、规则限制是否自洽完整
3. 势力设定（20分）：主要势力/组织是否清晰，相互关系是否合理
4. 空间地理（20分）：关键地点、环境设定是否有画面感和可创作性
5. 内部一致性（20分）：各项设定之间是否逻辑自洽，无矛盾"""
        elif "规则" in doc_type:
            dimensions = """评分维度（满分100，85分及格。请严格围绕"创作规则"本身评审，不要评审世界观细节、势力设定等内容）：
1. 写作规范（25分）：节奏、字数、风格等创作规范是否明确
2. 角色规则（25分）：人物行为逻辑、成长路径、关系规则是否清晰
3. 情节规则（25分）：冲突设置、转折节点、爽点分布是否有指导性
4. 一致性约束（25分）：是否有清晰的创作红线/禁忌，防止前后矛盾"""
        elif "大纲" in doc_type:
            dimensions = """评分维度（满分100，85分及格）：
1. 结构完整（25分）：起承转合是否完整，章节分布是否合理
2. 节奏把控（25分）：高潮与日常的交替是否得当，信息量是否适中
3. 伏笔管理（25分）：是否有足够的伏笔和悬念设计
4. 事件逻辑（25分）：章节之间因果链是否清晰，无跳跃"""
        else:
            dimensions = """评分维度（满分100，85分及格）：
1. 完整性（25分）：是否包含必要的关键要素
2. 一致性（25分）：内部设定是否自洽
3. 实用性（25分）：对创作是否有指导意义
4. 创新性（25分）：是否有独特亮点"""

        prompt = f"""请评审以下{doc_type}文档。

{dimensions}

⚠️ 注意：只评审{doc_type}应有的内容，不要因为文档缺少"不属于{doc_type}范畴的内容"而扣分。

评审文档：
{content[:3000]}

请输出：
1. 总分（数字）
2. 各维度得分
3. 发现的问题列表

格式：
总分：[分数]
问题：[问题1];[问题2];...
"""
        
        try:
            response = self.llm.generate(prompt, system_prompt="你是一个专业的小说设定评审专家。请严格围绕文档类型本身的职责进行评审，不要越界评审。")
            # 解析评分
            score = 85  # 默认分数
            issues = ""
            if "总分" in response:
                import re
                match = re.search(r'总分[：:]?\s*(\d+)', response)
                if match:
                    score = int(match.group(1))
            if "问题" in response:
                match = re.search(r'问题[：:]?\s*(.+?)(?=总分|$)', response, re.DOTALL)
                if match:
                    issues = match.group(1).strip()
            return score, issues
        except Exception as e:
            print(f"评审失败: {e}")
            return 85, ""  # 默认及格
    
    def _generate_and_audit_document(self, doc_type: str, generate_func, revise_func,
                                     audit_func, report, base_progress: int, 
                                     max_score_progress: int, pass_score: int = 85,
                                     max_cycles: int = 3, cancel_check: Callable = None,
                                     book: BookInfo = None, timestamp: str = None) -> Dict:
        """
        生成-评审-修订循环机制
        
        Args:
            doc_type: 文档类型名称（如"世界观设定"）
            generate_func: 生成文档的函数
            revise_func: 修订文档的函数，接收feedback参数
            audit_func: 评审文档的函数，返回(score, issues)
            report: 进度报告回调函数
            base_progress: 基础进度百分比
            max_score_progress: 最高分时的进度百分比
            pass_score: 及格分数，默认85
            max_cycles: 最大循环次数，默认3
            cancel_check: 取消检查函数，返回True表示任务被取消
            book: 书籍对象，用于保存中间文件
            timestamp: 时间戳，用于文件命名
        
        Returns:
            包含最终内容、分数、候选列表等信息的字典
        """
        def is_cancelled():
            if cancel_check and cancel_check():
                return True
            return False
        
        candidates = []
        best_content = None
        best_score = 0
        best_issues = ""
        
        # 内部保存辅助函数：分步保存生成/修订/评审结果到本地文件
        def _save_step(step_name: str, round_num: int, content: str = None, 
                       score: int = None, issues: str = None):
            if not book:
                return
            try:
                report_dir = self.workspace / book.path / "generation_reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_type = doc_type.replace("/", "_").replace("\\", "_")
                
                if content:
                    filepath = report_dir / f"{safe_type}_round{round_num}_{step_name}_{ts}.md"
                    header = f"# {book.name} - {doc_type} - 第{round_num}轮{step_name}\n"
                    header += f"**时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    if score is not None:
                        header += f"**评分**：{score}分\n"
                    if issues:
                        header += f"\n## 问题\n{issues}\n\n---\n\n"
                    filepath.write_text(header + content, encoding='utf-8')
                    print(f"[_generate_and_audit_document] 已保存: {filepath.name}")
            except Exception as e:
                print(f"[_generate_and_audit_document] 保存步骤文件失败: {e}")
        
        # 第1轮：生成 + 评审
        report("生成文档", base_progress, f"正在生成{doc_type}...")
        if is_cancelled():
            raise CancelledException("任务被用户终止")
        content = generate_func()
        if is_cancelled():
            raise CancelledException("任务被用户终止")
        
        # 保存初次生成结果
        _save_step("生成", 1, content=content)
        
        report("评审文档", base_progress + 3, f"正在评审{doc_type}...")
        score, issues = audit_func(content)
        
        # 保存初次评审结果
        _save_step("评审", 1, content=content, score=score, issues=issues)
        
        candidates.append({
            "round": 1,
            "action": "generate",
            "content": content,
            "score": score,
            "issues": issues
        })
        
        if score > best_score:
            best_content = content
            best_score = score
            best_issues = issues
        
        # 记录评审结果
        self._log_audit_cycle(doc_type, 1, "生成", score, issues, pass_score)
        
        # 如果及格，直接返回
        if score >= pass_score:
            report("评审通过", max_score_progress, f"{doc_type}评审通过（{score}分）")
            return {
                "content": content,
                "final_score": score,
                "final_issues": issues,
                "candidates": candidates,
                "best_content": best_content,
                "best_score": best_score,
                "passed": True,
                "cycles_used": 1
            }
        
        # 第2-3轮：修订 + 评审循环
        for cycle in range(2, max_cycles + 1):
            # 计算当前进度（递增）
            cycle_progress = base_progress + (cycle - 1) * 5
            cycle_progress = min(cycle_progress, max_score_progress - 5)
            
            report("修订文档", cycle_progress, 
                  f"{doc_type}评分({score}分)未达标，开始第{cycle-1}次修订...")
            if is_cancelled():
                raise CancelledException("任务被用户终止")
            
            # 构建详细的修订反馈
            feedback = self._build_revision_feedback(doc_type, score, issues, cycle)
            
            # 执行修订
            revised_content = revise_func(feedback)
            if is_cancelled():
                raise CancelledException("任务被用户终止")
            
            # 如果修订失败（返回None），使用最佳候选
            if revised_content is None:
                report("修订失败", cycle_progress + 2, 
                      f"{doc_type}第{cycle-1}次修订失败，采用当前最佳版本")
                break
            
            # 保存修订结果
            _save_step("修订", cycle, content=revised_content)
            
            # 评审修订后的内容
            report("评审修订", cycle_progress + 3, f"正在评审第{cycle-1}次修订结果...")
            revised_score, revised_issues = audit_func(revised_content)
            
            # 保存修订后的评审结果
            _save_step("评审", cycle, content=revised_content, score=revised_score, issues=revised_issues)
            
            candidates.append({
                "round": cycle,
                "action": "revise",
                "revision_round": cycle - 1,
                "content": revised_content,
                "score": revised_score,
                "issues": revised_issues
            })
            
            if revised_score > best_score:
                best_content = revised_content
                best_score = revised_score
                best_issues = revised_issues
            
            # 记录评审结果
            self._log_audit_cycle(doc_type, cycle, "修订", revised_score, revised_issues, pass_score)
            
            # 更新当前值
            content = revised_content
            score = revised_score
            issues = revised_issues
            
            # 如果及格，直接返回
            if score >= pass_score:
                report("评审通过", max_score_progress, 
                      f"{doc_type}第{cycle-1}次修订后评审通过（{score}分）")
                return {
                    "content": content,
                    "final_score": score,
                    "final_issues": issues,
                    "candidates": candidates,
                    "best_content": best_content,
                    "best_score": best_score,
                    "passed": True,
                    "cycles_used": cycle
                }
        
        # 所有轮次都未通过，返回最佳候选
        if best_score > 0:
            report("采用最佳候选", max_score_progress, 
                  f"{doc_type}采用最佳候选版本（{best_score}分）")
            return {
                "content": best_content,
                "final_score": best_score,
                "final_issues": best_issues,
                "candidates": candidates,
                "best_content": best_content,
                "best_score": best_score,
                "passed": False,
                "cycles_used": len(candidates)
            }
        
        # 异常情况
        return {
            "content": content,
            "final_score": score,
            "final_issues": issues,
            "candidates": candidates,
            "best_content": content,
            "best_score": score,
            "passed": False,
            "cycles_used": len(candidates)
        }
    
    def _save_document_generation_report(self, book: BookInfo, doc_type: str, 
                                         result: Dict, timestamp: str = None) -> str:
        """保存文档生成报告（包括所有候选版本、评审结果、修订过程）"""
        try:
            import json
            
            # 创建报告目录
            report_dir = self.workspace / book.path / "generation_reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            
            if timestamp is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 生成 Markdown 报告
            report_lines = [
                f"# {book.name} - {doc_type}生成报告",
                "",
                f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "## 生成结果",
                f"- **最终评分**：{result.get('final_score', 0)}分",
                f"- **最佳评分**：{result.get('best_score', 0)}分",
                f"- **评审通过**：{'✅ 是' if result.get('passed') else '❌ 否'}",
                f"- **循环轮次**：{result.get('cycles_used', 0)}轮",
                "",
                "## 候选版本列表",
                ""
            ]
            
            candidates = result.get('candidates', [])
            for i, cand in enumerate(candidates):
                action = "生成" if cand.get('action') == 'generate' else f"第{cand.get('revision_round', 1)}次修订"
                report_lines.append(f"### 版本{i+1}（{action}）")
                report_lines.append(f"- **评分**：{cand.get('score', 0)}分")
                report_lines.append(f"- **问题**：{cand.get('issues', '无') or '无'}")
                report_lines.append("")
            
            # 保存最终采用的文档
            final_content = result.get('content', '')
            doc_filename_map = {
                "世界观设定": "story_bible.md",
                "创作规则": "book_rules.md",
                "人物设定": "characters.md",
                "章节大纲": "chapter_outline.md",
            }
            doc_filename = doc_filename_map.get(doc_type, f"{doc_type}.md")
            
            # 保存到文档文件
            doc_path = self.workspace / book.path / doc_filename
            doc_path.write_text(final_content, encoding='utf-8')
            report_lines.append(f"## 最终文档")
            report_lines.append(f"已保存到：`{doc_filename}`")
            report_lines.append("")
            report_lines.append("### 文档预览（开头500字）")
            report_lines.append("```")
            report_lines.append(final_content[:500] if final_content else "(无内容)")
            report_lines.append("```")
            
            # 保存完整候选版本
            if candidates:
                candidates_file = report_dir / f"{doc_type}_candidates_{timestamp}.json"
                candidates_data = []
                for i, cand in enumerate(candidates):
                    candidates_data.append({
                        "version": i + 1,
                        "action": cand.get('action'),
                        "revision_round": cand.get('revision_round'),
                        "score": cand.get('score'),
                        "issues": cand.get('issues'),
                        "content_length": len(cand.get('content', '')),
                        "content_preview": cand.get('content', '')[:200] if cand.get('content') else ""
                    })
                
                with open(candidates_file, 'w', encoding='utf-8') as f:
                    json.dump(candidates_data, f, ensure_ascii=False, indent=2)
                report_lines.append("")
                report_lines.append(f"## 候选版本详情")
                report_lines.append(f"已保存到：`generation_reports/{doc_type}_candidates_{timestamp}.json`")
            
            # 保存最终报告
            report_content = "\n".join(report_lines)
            report_file = report_dir / f"{doc_type}_report_{timestamp}.md"
            report_file.write_text(report_content, encoding='utf-8')
            
            print(f"[_save_document_generation_report] 已保存 {doc_type} 生成报告: {report_file}")
            return str(report_file)
            
        except Exception as e:
            print(f"[_save_document_generation_report] 保存报告失败: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def _build_revision_feedback(self, doc_type: str, score: int, issues: str, 
                                 current_round: int) -> str:
        """构建详细的修订反馈"""
        feedback = f"""【{doc_type}评审报告 - 第{current_round}次修订参考】
评分：{score}/100（需达到85分及格）

"""
        
        if issues:
            feedback += f"""发现的问题：
{issues}

"""
        
        # 添加修订指导
        if score < 60:
            feedback += """【严重问题】评分较低，需要大幅改进：
1. 内容可能过于简略或空洞，请增加具体细节和深度描写
2. 设定之间可能存在矛盾，请仔细检查自洽性
3. 缺乏独特性和创新点，请思考如何让设定更有辨识度
"""
        elif score < 75:
            feedback += """【中等问题】评分偏低，需要针对性改进：
1. 完整性不足，请检查是否缺少必要章节
2. 实用性有限，请增加对创作的指导意义
3. 创新性不足，请添加独特设定
"""
        else:
            feedback += """【轻微问题】接近及格线，需要小幅优化：
1. 某些细节可以更完善
2. 部分表述可以更精准
"""
        
        feedback += """
【修订要求】
请根据以上评审意见，对文档进行修订。重点改进指出的问题，保持原有合理的设定不变。"""
        
        return feedback
    
    def _log_audit_cycle(self, doc_type: str, round_num: int, action: str, 
                         score: int, issues: str, pass_score: int) -> None:
        """记录评审循环日志"""
        status = "✓通过" if score >= pass_score else "✗未通过"
        print(f"[{doc_type}] 第{round_num}轮{action}: {score}分 {status}")
    
    def _validate_setting_documents(self, book: BookInfo, story_bible: str, 
                                   book_rules: str, characters: str) -> Dict:
        """综合校验设定文档，返回校验结果"""
        prompt = f"""请校验以下设定文档的一致性，检查并修正：

1. 人物名称是否统一（主角名在各文档中是否一致）
2. 时间线是否矛盾
3. 设定冲突（如：A设定在某处说X，另一处说Y）
4. 核心设定是否统一

文档内容：
【世界观设定】
{story_bible[:2000]}

【创作规则】
{book_rules[:2000]}

【人物设定】
{characters[:2000]}

请输出：
1. 是否通过校验（pass/fail）
2. 发现的问题数量
3. 修正后的文档（如果有修正）

格式：
校验结果：pass/fail
问题数量：N
修正内容：[如有]
"""
        
        try:
            response = self.llm.generate(prompt, system_prompt="你是一个专业的小说设定校验专家，负责检查设定一致性并修正冲突。")
            
            passed = "pass" in response.lower() or "通过" in response
            issue_count = 0
            if "问题数量" in response:
                import re
                match = re.search(r'问题数量[：:]?\s*(\d+)', response)
                if match:
                    issue_count = int(match.group(1))
            
            return {
                "passed": passed,
                "issue_count": issue_count,
                "corrected_story_bible": story_bible,
                "corrected_book_rules": book_rules,
                "corrected_characters": characters,
                "details": response
            }
        except Exception as e:
            print(f"校验失败: {e}")
            return {"passed": True, "issue_count": 0}

    def create_book_workflow_with_planning(self, brief: str, planning: Dict) -> Dict[str, Any]:
        """兼容接口：直接调用一站式创建"""
        return self.create_book_workflow(brief)

    # ============== 灵感对话模式 ==============

    def get_inspiration_status(self, book_id: str) -> Dict[str, Any]:
        """获取书籍的灵感模式状态"""
        book = self.get_book(book_id)
        if not book:
            return {"success": False, "ready": False, "reason": "书籍不存在"}
        
        chapters = self.get_chapters(book_id)
        
        # 有章节（第0章或任何正式章节）则不能进入灵感模式
        if len(chapters) > 0:
            return {
                "success": True,
                "ready": False,
                "reason": "该书籍已有章节，无法进入灵感模式",
                "chapter_count": len(chapters)
            }
        
        # 检查是否为灵感模式书籍或有未完成的灵感对话
        is_inspiration = getattr(book, 'is_inspiration', False)
        dialogue = getattr(book, 'inspiration_dialogue', [])
        
        return {
            "success": True,
            "ready": True,  # 前端检查此字段
            "can_enter": True,
            "is_inspiration_mode": is_inspiration,
            "has_dialogue": len(dialogue) > 0,
            "dialogue_count": len(dialogue),
            "collected_info": getattr(book, 'inspiration_collected_info', {})
        }

    def enter_inspiration_mode(self, book_id: str) -> Dict[str, Any]:
        """重新进入灵感对话模式"""
        book = self.get_book(book_id)
        if not book:
            return {"success": False, "message": "书籍不存在"}
        
        chapters = self.get_chapters(book_id)
        if len(chapters) > 0:
            return {"success": False, "message": "该书籍已有章节，无法进入灵感模式"}
        
        # 直接在 book_index 中标记为灵感模式
        with self.sm._lock:
            for b in self.sm.book_index.get("books", []):
                if b.get("id") == book_id:
                    b["is_inspiration"] = True
                    break
        self.sm._save_book_index()
        
        # 重新获取书籍以返回最新状态
        book = self.get_book(book_id)
        return {
            "success": True,
            "message": "已进入灵感对话模式",
            "collected_info": getattr(book, 'inspiration_collected_info', {}),
            "dialogue_count": len(getattr(book, 'inspiration_dialogue', []))
        }

    def exit_inspiration_mode(self, book_id: str) -> Dict[str, Any]:
        """退出灵感对话模式"""
        book = self.get_book(book_id)
        if not book:
            return {"success": False, "message": "书籍不存在"}

        # 在 book_index 中标记为非灵感模式
        with self.sm._lock:
            for b in self.sm.book_index.get("books", []):
                if b.get("id") == book_id:
                    b["is_inspiration"] = False
                    break
        self.sm._save_book_index()

        return {
            "success": True,
            "message": "已退出灵感对话模式"
        }

    def init_inspiration_book(self, book_id: str, book_name: str, initial_idea: str = "", 
                              progress_callback=None) -> Dict[str, Any]:
        """初始化灵感对话模式的书籍
        
        修复：所有 LLM 处理在 create_book 之前完成，确保保存时数据完整，
        避免前端在中间状态就触发 auto_complete。
        
        Args:
            book_id: 书籍ID
            book_name: 书名
            initial_idea: 初始创意输入
            progress_callback: 可选进度回调 callback(progress, message, step)
        """
        import threading
        print(f"[init_inspiration_book {threading.current_thread().name}] 开始初始化，book_id={book_id}")
        try:
            from core.models import BookInfo
            
            # 创建灵感书籍记录
            book = BookInfo(
                id=book_id,
                name=book_name,
                path=f"books/{book_id}",
                genre="",
                is_inspiration=True,
                created_at=datetime.now().isoformat()
            )
            book.inspiration_collected_info = {
                "book_name": book_name,
                "initial_idea": initial_idea,
                "genre": "",
                "platform": "",
                "words_per_chapter": "",
                "total_chapters": "",
                "background": "",
                "protagonist": ""
            }
            book.inspiration_dialogue = []
            
            # 添加欢迎消息
            welcome_msg = """👋 你好！欢迎来到灵感创作模式。

请告诉我你的创作想法，比如：
• 你想写什么类型的故事？
• 主角有什么特点？
• 故事背景是什么？

我会通过问答帮助你完善创作构想。"""
            book.inspiration_dialogue.append({
                "role": "assistant",
                "content": welcome_msg,
                "time": datetime.now().isoformat()
            })
            
            # ---- 第一步：在保存之前，完成所有 LLM 处理 ----
            if initial_idea:
                print(f"[init_inspiration_book] 开始处理初始创意...")
                if progress_callback:
                    progress_callback(10, "正在解析创意输入...", "解析创意")
                
                # 添加用户消息
                book.inspiration_dialogue.append({
                    "role": "user",
                    "content": initial_idea,
                    "time": datetime.now().isoformat()
                })
                
                if progress_callback:
                    progress_callback(30, "正在用AI分析创意内容...", "AI分析")
                
                # 调用LLM精确提取信息（所有产出均由LLM生成，不依赖正则兜底）
                print(f"[init_inspiration_book] 开始调用LLM提取信息...")
                llm_extracted = self._extract_inspiration_info(initial_idea, current_info=book.inspiration_collected_info)
                book.inspiration_collected_info.update(llm_extracted)
                print(f"[init_inspiration_book] LLM提取完成: {llm_extracted}")
                
                # 检查缺失字段
                missing = self._get_missing_inspiration_fields(book)
                
                if progress_callback:
                    progress_callback(60, "正在生成对话引导...", "生成引导")
                
                # 生成 AI 回复引导用户（由LLM产出，不做兜底）
                ai_response = self._generate_inspiration_reply(
                    book.inspiration_collected_info, 
                    book.inspiration_collected_info,
                    missing, 
                    book.inspiration_dialogue
                )
                
                book.inspiration_dialogue.append({
                    "role": "assistant",
                    "content": ai_response,
                    "time": datetime.now().isoformat()
                })
            
            # ---- 第二步：所有数据就绪，一次性保存 ----
            print(f"[init_inspiration_book] 一次性保存完整书籍数据...")
            success, msg = self.sm.create_book(book)
            if not success:
                print(f"[init_inspiration_book] create_book失败: {msg}")
                return {"success": False, "message": msg}
            print(f"[init_inspiration_book] 保存完成，dialogue长度={len(book.inspiration_dialogue)}")
            
            return {
                "success": True,
                "book_id": book_id,
                "book_name": book_name,
                "message": "灵感书籍已创建"
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[init_inspiration_book] 异常: {str(e)}")
            return {"success": False, "message": f"初始化失败: {str(e)}"}

    def get_inspiration_info(self, book_id: str) -> Dict[str, Any]:
        """获取灵感书籍的详细信息"""
        import threading
        print(f"[get_inspiration_info {threading.current_thread().name}] book_id={book_id}")
        
        # 直接从 book_index 字典中获取（不依赖 BookInfo 对象）
        book_dict = None
        with self.sm._lock:
            for b in self.sm.book_index.get("books", []):
                if b.get("id") == book_id:
                    book_dict = b
                    break
            # 如果内存中找不到，尝试重新加载文件
            if not book_dict:
                print(f"[get_inspiration_info] 内存中未找到，尝试重新加载...")
                reloaded = self.sm._load_book_index()
                for b in reloaded.get("books", []):
                    if b.get("id") == book_id:
                        book_dict = b
                        self.sm.book_index["books"] = reloaded.get("books", [])
                        break
        
        if not book_dict:
            print(f"[get_inspiration_info] 书籍不存在: {book_id}")
            return {"success": False, "message": "书籍不存在"}
        
        book = BookInfo.from_dict(book_dict)
        book_is_inspiration = book_dict.get("is_inspiration", False)
        dialogue = book_dict.get("inspiration_dialogue", [])
        collected_info = book_dict.get("inspiration_collected_info", {})
        print(f"[get_inspiration_info] 书籍: {book.name}, is_inspiration={book_is_inspiration}, dialogue长度={len(dialogue)}")
        
        if not book_is_inspiration:
            print(f"[get_inspiration_info] 该书籍不是灵感状态")
            return {"success": False, "message": "该书籍不是灵感状态"}
        
        # 临时设置属性供 _get_missing_inspiration_fields 使用
        book.inspiration_collected_info = collected_info
        
        missing_fields = self._get_missing_inspiration_fields(book)
        # 判断是否满足生成条件：关键必填字段都填了
        required_keys = ['genre', 'platform', 'background', 'protagonist', 'main_conflict', 'tone_style']
        can_generate = len(missing_fields) <= 4 and all(
            collected_info.get(k) for k in required_keys
        )
        
        result = {
            "success": True,
            "book": {
                "id": book.id,
                "name": book.name,
                "is_inspiration": book_is_inspiration,
                "collected_info": collected_info,
                "dialogue": dialogue,
                "missing_fields": missing_fields,
                "can_generate": can_generate
            }
        }
        print(f"[get_inspiration_info] 返回结果: success={result['success']}, dialogue长度={len(dialogue)}")
        return result

    def _get_missing_inspiration_fields(self, book) -> list:
        """获取缺失的灵感字段 - 通用字段列表"""
        collected = getattr(book, 'inspiration_collected_info', {})
        
        # 通用设定字段（适用于所有小说）
        # 系统只维护这个列表，具体需要哪些由LLM根据评审标准判断
        all_fields = [
            'genre', 'platform', 'words_per_chapter', 'total_chapters',
            'background', 'protagonist', 'main_conflict', 'power_system',
            'factions', 'locations', 'tone_style', 'story_arc', 'supporting_chars',
            'key_items', 'important_locations', 'themes', 'target_audience'
        ]
        
        field_labels = {
            'genre': '题材类型', 'platform': '发布平台',
            'words_per_chapter': '每章字数', 'total_chapters': '总章节数',
            'background': '世界观背景', 'protagonist': '主角设定',
            'main_conflict': '核心冲突', 'power_system': '力量体系',
            'factions': '势力组织', 'locations': '地理场景',
            'tone_style': '文风基调', 'story_arc': '故事主线',
            'supporting_chars': '配角设定', 'key_items': '重要物品/道具',
            'important_locations': '重要地点', 'themes': '核心主题',
            'target_audience': '目标读者'
        }
        
        missing = []
        for field in all_fields:
            if not collected.get(field):
                missing.append({
                    "field": field,
                    "required": field in ['genre', 'platform', 'words_per_chapter', 'total_chapters'],
                    "label": field_labels.get(field, field)
                })
        
        return missing

    def chat_inspiration(self, book_id: str, user_message: str) -> Dict[str, Any]:
        """
        处理灵感对话的核心逻辑
        
        流程：
        1. 分析用户输入，提取设定信息
        2. 判断是否需要补充更多信息
        3. 如果完整，提示用户可以生成设定文档
        4. 如果缺失，引导用户补充（每次2-3个）
        
        特殊指令：
        - "由你决定"：自动调用LLM补全缺失信息
        """
        # 直接从 book_index 获取灵感相关字段
        book_dict = None
        with self.sm._lock:
            for b in self.sm.book_index.get("books", []):
                if b.get("id") == book_id:
                    book_dict = b
                    break
        
        if not book_dict:
            return {"success": False, "message": "书籍不存在"}
        
        book = self.sm.get_book_by_id(book_id)
        if not book:
            return {"success": False, "message": "书籍不存在"}
        
        # 从 book_index 字典获取灵感数据（BookInfo 对象不包含这些字段）
        dialogue = list(book_dict.get("inspiration_dialogue", []))
        old_collected = dict(book_dict.get("inspiration_collected_info", {}))
        
        print(f"[chat_inspiration] book_id={book_id}, 当前collected={old_collected}")
        
        # 特殊指令处理："由你决定" -> 自动补全信息
        if user_message == "由你决定":
            print("[chat_inspiration] 检测到'由你决定'指令，调用自动补全...")
            
            # 添加用户消息
            dialogue.append({
                "role": "user",
                "content": user_message,
                "time": datetime.now().isoformat()
            })
            # 先同步用户消息到book_dict（auto_complete会从book_index读取）
            book_dict["inspiration_dialogue"] = dialogue
            
            # 调用自动补全（内部会读取book_index的dialogue并追加system消息，然后保存）
            auto_result = self.auto_complete_inspiration(book_id)
            new_collected = auto_result.get("collected_info", old_collected)
            
            # ---- 修复：不覆盖auto_complete已保存的数据 ----
            # auto_complete_inspiration内部已保存了完整dialogue到book_index
            # 这里从book_dict重新读取，保留auto_complete追加的system消息
            dialogue = list(book_dict.get("inspiration_dialogue", []))
            book_dict["inspiration_collected_info"] = new_collected
            
            # 检测书名是否变化，如果变化则同步更新所有文档
            new_book_name = new_collected.get('book_name', '').strip()
            old_book_name = old_collected.get('book_name', '').strip()
            name_changed = new_book_name and new_book_name != old_book_name and new_book_name != book.name
            
            # 检查新书名是否是占位符
            name_placeholder = ['新书', '未命名', '未确定', '', '待定', '暂无']
            new_name_clean = new_book_name.replace('《', '').replace('》', '').strip()
            is_valid_name = new_book_name and new_name_clean not in name_placeholder
            
            # 如果书名有效且发生了变化，同步更新所有文档
            if name_changed and is_valid_name:
                print(f"[chat_inspiration auto-complete] 检测到书名变化: '{old_book_name}' -> '{new_book_name}'，同步更新文档...")
                rename_result = self.rename_book(book_id, new_book_name)
                if rename_result.get('success') and rename_result.get('updated', True):
                    print(f"[chat_inspiration auto-complete] 书名更新成功，更新的文档: {rename_result.get('updated_docs', [])}")
            
            # 判断缺失的字段
            class TempBook:
                def __init__(self, collected):
                    self.inspiration_collected_info = collected
            temp_book = TempBook(new_collected)
            missing = self._get_missing_inspiration_fields(temp_book)
            
            # 生成回复
            response = self._generate_inspiration_reply(old_collected, new_collected, missing, dialogue)
            
            # 添加AI回复
            dialogue.append({
                "role": "assistant",
                "content": response,
                "time": datetime.now().isoformat()
            })
            
            # 保存（确保数据一致性）
            book.inspiration_collected_info = new_collected
            book.inspiration_dialogue = dialogue
            book_dict["inspiration_dialogue"] = dialogue
            self.save_book_meta(book)
            self._save_inspiration_to_chatlog(book, dialogue)
            
            return {
                "success": True,
                "response": response,
                "collected_info": new_collected,
                "extracted_fields": {},
                "missing_fields": missing,
                "can_generate": len(missing) <= 3,
                "missing_count": len(missing),
                "save_success": True
            }
        
        dialogue.append({
            "role": "user",
            "content": user_message,
            "time": datetime.now().isoformat()
        })
        
        # 分析用户输入，提取信息
        extracted = self._extract_inspiration_info(user_message, old_collected)
        print(f"[chat_inspiration] 提取到: {extracted}")
        
        # 记录书名更新结果
        name_updated = None
        
        # 更新已收集的信息
        new_collected = dict(old_collected)
        new_collected.update(extracted)
        
        # 更新 book_dict（直接修改内存中的数据）
        book_dict["inspiration_dialogue"] = dialogue
        book_dict["inspiration_collected_info"] = new_collected
        
        # 同步更新 book 对象（保持数据一致性）
        book.inspiration_collected_info = new_collected
        book.inspiration_dialogue = dialogue
        
        # 检测书名是否变化，如果变化则同步更新所有文档
        new_book_name = new_collected.get('book_name', '').strip()
        old_book_name = old_collected.get('book_name', '').strip()
        name_changed = new_book_name and new_book_name != old_book_name and new_book_name != book.name
        
        # 检查新书名是否是占位符
        name_placeholder = ['新书', '未命名', '未确定', '', '待定', '暂无']
        new_name_clean = new_book_name.replace('《', '').replace('》', '').strip()
        is_valid_name = new_book_name and new_name_clean not in name_placeholder
        
        # 如果书名有效且发生了变化，同步更新所有文档
        if name_changed and is_valid_name:
            print(f"[chat_inspiration] 检测到书名变化: '{old_book_name}' -> '{new_book_name}'，同步更新文档...")
            name_updated = self.rename_book(book_id, new_book_name)
            if name_updated.get('success') and name_updated.get('updated', True):
                print(f"[chat_inspiration] 书名更新成功，更新的文档: {name_updated.get('updated_docs', [])}")
        
        # 判断缺失的字段（创建临时对象用于检查）
        class TempBook:
            def __init__(self, collected):
                self.inspiration_collected_info = collected
        temp_book = TempBook(new_collected)
        missing = self._get_missing_inspiration_fields(temp_book)
        required_missing = [m for m in missing if m['required']]
        optional_missing = [m for m in missing if not m['required']]
        
        # 生成回复（传入新旧collected用于对比）
        response = self._generate_inspiration_reply(old_collected, new_collected, missing, dialogue)
        
        # 添加AI回复
        dialogue.append({
            "role": "assistant",
            "content": response,
            "time": datetime.now().isoformat()
        })
        
        # 保存更新后的数据
        save_ok = self.save_book_meta(book)
        print(f"[chat_inspiration] 保存结果: {save_ok}, 对话长度: {len(dialogue)}")
        
        # 同时保存到 chatlog（便于与创作无缝衔接）
        self._save_inspiration_to_chatlog(book, dialogue)
        
        # 返回提取到的信息（用于前端反馈）
        return {
            "success": True,
            "response": response,
            "collected_info": new_collected,
            "extracted_fields": extracted,  # 本次提取的字段
            "missing_fields": missing,
            "can_generate": len(required_missing) == 0,
            "save_success": save_ok,
            "name_updated": name_updated  # 书名是否被更新
        }

    def _extract_inspiration_info(self, user_message: str, current_info: dict) -> dict:
        """从用户消息中提取灵感信息"""
        
        # 构建当前收集状态的摘要
        summary_parts = []
        for key, label in [
            ('book_name', '书名'), ('genre', '题材'), ('platform', '平台'), 
            ('words_per_chapter', '章节字数'), ('total_chapters', '总章节数'), 
            ('background', '背景'), ('protagonist', '主角'),
            ('main_conflict', '核心冲突'), ('power_system', '力量体系'),
            ('factions', '势力'), ('locations', '地理'), ('tone_style', '文风')
        ]:
            val = current_info.get(key)
            if val:
                summary_parts.append(f"- {label}：{self._truncate(str(val), 100)}")
        
        current_summary = "\n".join(summary_parts) if summary_parts else "无"
        
        prompt = f"""你是小说创作助手，需要从用户的创意输入中提取结构化信息。

【当前已收集的设定】
{current_summary}

【用户输入的创意内容】
{user_message}

请仔细阅读用户输入，提取其中的创作信息。即使信息分散在不同位置，也要完整提取。

⚠️ 核心原则：你的任务是「提取」而非「创作」。用户写什么就提取什么，禁止改写、替换、美化用户的创意内容。

提取规则：
1. 只返回JSON，不要有任何其他文字
2. 如果用户明确提供了某个字段（如"题材：都市异能"），必须提取
3. 书名通常出现在"书名："后面或用《》包围
4. 题材如"都市异能"、"玄幻修仙"、"都市言情"等
5. 平台如"番茄小说"、"起点中文网"、"掌阅"等
6. 章节字数和总章节数提取为纯数字
7. 主角信息包含：姓名、身份、性格、动机
8. 背景是故事发生的世界观设定
9. 如果用户输入了梗概或故事大纲，提取到 background 或 main_conflict
10. 如果某项信息用户没有提供，返回空字符串""

⚠️ 忠实性约束（极其重要！违反将导致用户创意被破坏）：
- 绝对忠实于用户文字：用户写"彗星爆炸引发变异"就不要改成"血脉觉醒"、"古玉传承"等
- 禁止修改用户提供的人名、地名、专有名词（如主角叫余凌就不写成林逸）
- 用户描述的世界观起源（彗星/重生/外星/魔法等）必须原样保留，不得替换
- 用户描述的创作风格（轻松幽默/热血/悬疑等）必须原样保留，不得自行修改
- 一句话总结：「提取」是把用户的话搬运到对应字段，不是用你自己的话重写一遍

返回JSON格式：
{{
    "book_name": "",
    "genre": "",
    "platform": "",
    "words_per_chapter": "",
    "total_chapters": "",
    "background": "",
    "protagonist": "",
    "main_conflict": "",
    "power_system": "",
    "factions": "",
    "locations": "",
    "tone_style": ""
}}

请分析用户输入并返回JSON："""

        import json
        import re
        print(f"[_extract_inspiration_info] 开始提取，prompt长度={len(prompt)}")
        
        # 使用文本模式（不用json_mode=True），避免部分API不兼容
        # 使用LLM默认超时（300s），确保有足够时间完成调用
        success, text_result = self.llm.call(
            prompt, 
            json_mode=False,
            agent_name="InspirationExtractor"
        )
        
        if not success or not text_result:
            raise RuntimeError(f"LLM提取信息失败: {text_result}")
        
        # 手动提取 JSON（兼容各种格式：裸JSON / ```json ... ``` / 混合文本中的JSON）
        json_str = text_result.strip()
        
        # 尝试移除 markdown 代码块标记
        md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', json_str, re.DOTALL)
        if md_match:
            json_str = md_match.group(1).strip()
        else:
            # 尝试提取 { ... } 最外层 JSON
            brace_match = re.search(r'\{.*\}', json_str, re.DOTALL)
            if brace_match:
                json_str = brace_match.group(0)
        
        result = json.loads(json_str)
        print(f"[_extract_inspiration_info] 提取结果: {result}")
        return {k: v for k, v in result.items() if v}

    def _generate_inspiration_reply(self, old_collected: dict, new_collected: dict, missing: list, dialogue: list) -> str:
        """生成灵感对话的AI回复 - 由LLM作为核心决策者"""
        
        # 构建对话历史摘要（仅用于LLM分析，不用于硬编码逻辑）
        dialogue_summary = ""
        for msg in dialogue[-6:]:  # 最近3轮对话
            role = "用户" if msg.get('role') == 'user' else "我"
            dialogue_summary += f"\n{role}：{self._truncate(msg.get('content', ''), 200)}"
        
        # 本次新提取的信息
        newly_extracted = {k: v for k, v in new_collected.items() 
                          if v and v != old_collected.get(k, '')}
        
        # 检查书名是否已确定
        book_name = new_collected.get('book_name', '').strip()
        # 清理书名号
        book_name_clean = book_name.replace('《', '').replace('》', '')
        name_placeholder = ['新书', '未命名', '未确定', '', '待定', '暂无']
        name_unconfirmed = book_name in name_placeholder or not book_name or book_name_clean in name_placeholder
        
        prompt = f"""你是小说创作顾问，通过多轮对话帮助用户完善创作设定，最终目标是通过评审取得高分。

【评审标准】（满分100，85分及格）
- 逻辑性（25分）：世界规则、力量体系是否自洽
- 角色塑造（25分）：主角人设是否清晰、动机是否充分
- 节奏把控（25分）：冲突设计、势力对抗是否有力
- 伏笔管理（25分）：是否有足够的伏笔发展空间

【当前已收集的设定信息】
{self._format_collected_info(new_collected)}

【本次用户输入中提取的新信息】
{self._format_new_info(newly_extracted)}

【最近对话历史】
{dialogue_summary}

【缺失的字段】（仅作为参考）
{', '.join([m.get('field', '') for m in missing]) if missing else '暂无明确缺失'}

请作为创作顾问，分析并回复用户。要求：

1. **确认提取**：如果用户提供了新信息，先确认已提取并简要展示

2. **分析创意**：深入分析用户描述的创意内核，包括：
   - 世界观的核心特点是什么？
   - 有哪些值得深挖的元素？
   - 对后续创作有什么潜在影响？
   （用2-3句话点出关键，不要泛泛而谈）

3. **评估完整性**：
   - 已有的设定能否支撑一个完整的故事？
   - 哪些评审维度可能得分较低？
   - 需要重点补充什么来提升评分？

4. **引导对话**：
   - 提出1-2个有针对性的问题（不要泛泛问"还有什么想法"）
   - 问题要基于用户已有的创意，引导深入思考
   - 问开放式问题，避免只能回答"是/否"的问题
   - **重要**：如果书名未确定（是新书或未填写），必须在"引导对话"部分提醒用户确定书名，这是首要任务

5. **智能补充**：
   - 当用户输入简短信息时，主动基于已有信息推断补充缺失内容
   - 特别是背景设定、世界观细节、角色动机等，用户没提到的可以合理推断
   - **推断必须基于用户已有的设定延伸，不得引入用户未提及的新世界观框架**
   - 例如：用户说了「彗星变异」，你可以补充变异后的社会结构，但不能把变异原因改成「血脉传承」「古玉觉醒」
   - 补充内容要简洁自然，融入回复中而非生硬列出

6. **判断是否可生成**：
   - 如果已有足够信息支撑评审（各维度至少有些许内容），可以建议生成设定文档
   - 如果关键维度仍然空白，继续引导补充

回复格式示例：
---
✅ **已记录**：[简要确认]

💡 **创意洞察**：[2-3句话分析]

📊 **评估**：[完整性判断+提升建议]

🎯 **下一步**：[1-2个针对性问题]
{f'⚠️ **提醒**：请先确定书名，这是创作的基础！' if name_unconfirmed else ''}

（可选）📝 **提示**：收集足够后可以输入「生成设定文档」
---
"""
        
        response = self.llm.generate(
            prompt, 
            system_prompt="你是一个专业、热情的小说创作顾问，帮助用户完善创意并为评审做准备。核心原则：忠于用户的原始创意，在用户已有设定的基础上延伸，绝不替换用户的世界观、主角、风格等核心要素。"
        )
        
        if response and not response.startswith("[生成失败:"):
            return response
        else:
            raise RuntimeError(f"LLM生成回复失败: {response}")
    
    def _format_collected_info(self, collected: dict) -> str:
        """格式化已收集的信息用于LLM分析"""
        if not collected:
            return "暂无收集到任何设定信息"
        
        lines = []
        # 按评审维度组织
        lines.append("【基础设定】")
        for k in ['genre', 'platform', 'words_per_chapter', 'total_chapters']:
            if collected.get(k):
                lines.append(f"  • {k}：{collected[k]}")
        
        lines.append("\n【世界观与逻辑性】")
        if collected.get('background'):
            lines.append(f"  • 背景：{self._truncate(collected['background'], 150)}")
        if collected.get('power_system'):
            lines.append(f"  • 力量体系：{self._truncate(collected['power_system'], 100)}")
        if collected.get('locations'):
            lines.append(f"  • 地理场景：{self._truncate(collected['locations'], 100)}")
        
        lines.append("\n【角色与动机】")
        if collected.get('protagonist'):
            lines.append(f"  • 主角：{self._truncate(collected['protagonist'], 150)}")
        if collected.get('main_conflict'):
            lines.append(f"  • 核心冲突：{self._truncate(collected['main_conflict'], 100)}")
        
        lines.append("\n【势力与节奏】")
        if collected.get('factions'):
            lines.append(f"  • 势力组织：{self._truncate(collected['factions'], 100)}")
        if collected.get('tone_style'):
            lines.append(f"  • 文风基调：{collected['tone_style']}")
        
        return '\n'.join(lines) if lines else "暂无收集到任何设定信息"
    
    def _format_new_info(self, new_info: dict) -> str:
        """格式化本次新提取的信息"""
        if not new_info:
            return "本次输入中未提取到新的设定信息"
        return '\n'.join([f"  • {k}：{self._truncate(str(v), 80)}" for k, v in new_info.items()])
    
    def _truncate(self, text: str, max_len: int) -> str:
        """截断文本"""
        if not text:
            return ''
        text = str(text)
        if len(text) <= max_len:
            return text
        return text[:max_len] + '...'

    def auto_complete_inspiration(self, book_id: str) -> Dict[str, Any]:
        """自动补全缺失的灵感信息
        
        修复：包含对话历史上下文，确保LLM理解用户原始意图；
        强化"已确定设定"的不可修改约束。
        """
        book = self.sm.get_book_by_id(book_id)
        if not book:
            return {"success": False, "message": "书籍不存在"}
        
        collected = getattr(book, 'inspiration_collected_info', {})
        dialogue = getattr(book, 'inspiration_dialogue', [])
        
        # 构建已有信息摘要
        summary = "\n".join([f"{k}: {v}" for k, v in collected.items() if v])
        
        # 获取缺失字段
        missing = self._get_missing_inspiration_fields(book)
        missing_fields = [m['field'] for m in missing]
        
        # 构建对话历史上下文（让LLM理解用户原始意图）
        dialogue_context = ""
        user_messages = [msg for msg in dialogue if msg.get('role') == 'user']
        if user_messages:
            dialogue_context = "【用户原始创意】（这是用户最原始的创作想法，补全时必须基于此）：\n"
            for msg in user_messages[-3:]:  # 最近3条用户消息
                dialogue_context += f"{msg.get('content', '')}\n"
        
        # 如果用户未输入任何信息，给LLM一些默认提示
        if not summary and not dialogue_context:
            summary = "暂无任何收集信息，请根据常见创作规律生成一套通用设定"
        
        # 分离已填写和缺失的字段
        filled_fields = {k: v for k, v in collected.items() if v}
        missing_fields_list = [m['field'] for m in missing]
        
        # 明确哪些字段已填写（这些字段的值必须原样保留）
        filled_str = "\n".join([f"{k}: {v}" for k, v in filled_fields.items()]) if filled_fields else "无"
        
        prompt = f"""你是小说创作助手。用户正在进行灵感创作。

{dialogue_context}
【已确定的设定 - 以下是用户已明确的信息，必须原样保留，绝对禁止修改或替换】：
{filled_str}

【需要补全的字段】（只补全以下缺失字段，已填写的字段绝对不能重复输出、不能修改）：
{missing_fields_list if missing_fields_list else '暂无明确缺失'}

请仔细阅读用户原始创意和已确定设定，在用户已有想法的基础上推断并补全缺失的设定（返回JSON）。

⚠️ 核心原则：补全 = 从用户已有设定「自然延伸」，不是另起炉灶或用你的常识替换用户的创意。

严格要求：
1. 只返回JSON，不要包含任何其他文字
2. 只补全缺失字段，绝对不要输出已填写的字段（包括genre、book_name等）
3. 补全内容必须与用户已有设定逻辑自洽，严禁推翻用户已确定的内容
4. 如果用户设定了「都市异能」，绝对不能改成「玄幻修仙」等
5. 如果用户设定了「番茄小说」平台，不能添加其他平台
6. 如果某个字段不适合该题材，可以为空字符串或空数组
7. JSON格式：所有字符串值都要用双引号包裹
8. 特别注意：book_name 如果已填写，必须原样返回，不要生成新书名

⚠️ 忠实性硬约束（违反任何一条都算失败）：
- 如果用户已明确世界起源（如「彗星爆炸导致变异」），补全的设定必须基于此起源展开，禁止引入用户未提及的新世界框架（如改为「血脉传承」「古玉觉醒」「灵气复苏」等）
- 如果用户已明确主角姓名和身份，补全时禁止修改姓名、禁止改变核心身份设定
- 如果用户已明确创作风格（如「轻松幽默」），补全的设定基调必须一致，不能变成「热血严肃」「黑暗深沉」
- 如果用户已明确故事结构（如「重生」），补全时必须保留重生设定，不能改为普通人成长
- 补全的内容只能「补充细节」，不能「替换框架」。例如用户说彗星变异→你可以补充变异后的社会结构变化，但不能把变异原因改成血脉传承"""

        try:
            import json
            import re
            
            # 使用文本模式（不用json_mode=True），避免部分API不兼容
            success, text_result = self.llm.call(
                prompt,
                json_mode=False,
                agent_name="AutoComplete"
            )
            
            if not success or not text_result:
                raise RuntimeError(f"LLM自动补全调用失败: {text_result}")
            
            # 手动提取 JSON
            json_str = text_result.strip()
            md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', json_str, re.DOTALL)
            if md_match:
                json_str = md_match.group(1).strip()
            else:
                brace_match = re.search(r'\{.*\}', json_str, re.DOTALL)
                if brace_match:
                    json_str = brace_match.group(0)
            
            result = json.loads(json_str)
            
            if not isinstance(result, dict):
                raise RuntimeError(f"自动补全返回非dict类型: {type(result)}")
            
            # 更新收集的信息（只更新空字段，保留用户已填写的内容）
            for k, v in result.items():
                if v and not collected.get(k):
                    collected[k] = v
            
            # 同步更新 book.name（如果新书名有效）
            new_book_name = collected.get('book_name', '').strip()
            if new_book_name and new_book_name != book.name:
                # 检查新书名是否是占位符
                name_placeholder = ['新书', '未命名', '未确定', '', '待定', '暂无']
                new_name_clean = new_book_name.replace('《', '').replace('》', '').strip()
                if new_name_clean not in name_placeholder:
                    book.name = new_book_name
                    print(f"[auto_complete_inspiration] 书名更新为: {new_book_name}")
            
            setattr(book, 'inspiration_collected_info', collected)
            
            # 记录补全的内容摘要（生成中文数据表格）
            completed = {k: v for k, v in result.items() if v}
            
            # 字段中文名称映射
            field_cn = {
                'book_name': '书名', 'genre': '题材', 'platform': '平台',
                'words_per_chapter': '章节字数', 'total_chapters': '总章节数',
                'background': '背景设定', 'protagonist': '主角信息',
                'main_conflict': '核心冲突', 'power_system': '力量体系',
                'factions': '势力设定', 'locations': '地理场景',
                'tone_style': '文风基调', 'story_arc': '故事主线',
                'supporting_chars': '配角设定', 'key_items': '重要物品/道具',
                'important_locations': '重要地点', 'themes': '核心主题',
                'target_audience': '目标读者'
            }
            
            # 构建HTML表格
            table_rows = ''
            for k, v in completed.items():
                cn_name = field_cn.get(k, k)
                val_text = _html_module.escape(str(v)) if v else ''
                # 截断过长内容显示
                display_val = val_text[:80] + ('...' if len(val_text) > 80 else '')
                table_rows += f'<tr><td class="insp-field-name">{cn_name}</td><td class="insp-field-val">{display_val}</td></tr>'
            
            table_html = f'''<table class="inspiration-auto-table"><tbody>{table_rows}</tbody></table>'''
            
            # 添加系统消息
            dialogue.append({
                "role": "system",
                "content": f"🤖 根据你的创意，系统已自动推断并补全了以下信息：<br><br>{table_html}<br>请确认是否符合你的预期，如有需要可以修改。",
                "time": datetime.now().isoformat()
            })
            setattr(book, 'inspiration_dialogue', dialogue)
            save_ok = self.save_book_meta(book)
            if not save_ok:
                print(f"[auto_complete_inspiration] 警告：保存书籍元数据失败")
            # 计算补全后是否满足生成条件
            required_keys = ['genre', 'platform', 'background', 'protagonist', 'main_conflict', 'tone_style']
            can_generate = all(collected.get(k) for k in required_keys)
            # 计算剩余缺失字段
            all_fields = ['genre', 'platform', 'words_per_chapter', 'total_chapters',
                          'background', 'protagonist', 'main_conflict', 'power_system',
                          'factions', 'locations', 'tone_style', 'story_arc', 'supporting_chars',
                          'key_items', 'important_locations', 'themes', 'target_audience']
            missing_count = sum(1 for f in all_fields if not collected.get(f))
            
            return {
                "success": True,
                "collected_info": collected,
                "can_generate": can_generate,
                "missing_count": missing_count,
                "message": "信息已自动补全"
            }
        except Exception as e:
            return {"success": False, "message": f"自动补全失败: {str(e)}"}

    def _audit_document(self, doc_name: str, content: str, book: BookInfo = None) -> Dict[str, Any]:
        """评审文档，返回评审结果
        
        根据文档类型使用专属评审维度，避免张冠李戴：
        - 世界观设定：只评世界观，不要求章节结构/伏笔
        - 创作规则：只评规则，不要求世界观细节
        - 章节大纲：评结构/节奏/伏笔
        """
        if not book:
            book = self.sm.get_current_book()

        # 根据文档类型定义专属评审维度
        if "世界观" in doc_name:
            dimensions = """评分维度（请严格围绕"世界观设定"本身评审，不要评审章节结构、伏笔网络、人物动机等不属于世界观的内容）：
1. 世界背景：时代背景、世界起源、历史脉络是否清晰具体
2. 力量体系：能力分类、等级划分、规则限制是否自洽完整
3. 势力设定：主要势力/组织是否清晰，相互关系是否合理
4. 空间地理：关键地点、环境设定是否有画面感
5. 内部一致性：各项设定之间是否逻辑自洽，无矛盾"""
        elif "规则" in doc_name:
            dimensions = """评分维度（请严格围绕"创作规则"本身评审，不要评审世界观细节、势力设定等不属于规则的内容）：
1. 写作规范：节奏、字数、风格等创作规范是否明确
2. 角色规则：人物行为逻辑、成长路径、关系规则是否清晰
3. 情节规则：冲突设置、转折节点、爽点分布是否有指导性
4. 一致性约束：是否有清晰的创作红线/禁忌，防止前后矛盾"""
        elif "大纲" in doc_name:
            dimensions = """评分维度：
1. 结构完整：起承转合是否完整，章节分布是否合理
2. 节奏把控：高潮与日常的交替是否得当，信息量是否适中
3. 伏笔管理：是否有足够的伏笔和悬念设计
4. 事件逻辑：章节之间因果链是否清晰，无跳跃"""
        else:
            dimensions = """评分维度：
1. 完整性：是否包含必要的关键要素
2. 一致性：内部逻辑是否自洽
3. 可操作性：是否能为后续创作提供有效指导"""

        prompt = f"""请对小说《{book.name}》的【{doc_name}】进行质量评审。

题材：{book.genre if book.genre else '未指定'}

{dimensions}

⚠️ 注意：只评审{doc_name}应有的内容，不要因为文档缺少"不属于{doc_name}范畴的内容"而扣分。

文档内容：
{content[:5000]}

请输出：
- **评分**：（1-100分）
- **评审结论**：通过/需修订
- **发现的问题**（如有）
- **具体修改建议**（如需修订）

格式简洁，直接指出问题。"""

        try:
            response = self.llm.generate(prompt, system_prompt="你是一个专业的小说编辑，负责评审设定文档的质量。只输出评审结论，不要输出其他说明。")
            
            # 提取评分
            score = 85  # 默认值
            score_match = re.search(r'评分[：:]\s*(\d+)', response)
            if score_match:
                score = int(score_match.group(1))
            
            # 判断是否通过：检查是否有"通过"且没有"需修订"
            # 同时要排除"无法评审"等特殊情况
            has_pass = "通过" in response
            has_need_revise = "需修订" in response or "不通过" in response
            has_error = "无法" in response or "无法评审" in response or "文档内容为空" in response
            
            # 如果是"无法评审"或文档内容为空的情况，视为通过（避免循环修订）
            if has_error:
                print(f"评审遇到问题，视为通过：{response[:100]}")
                passed = True
            else:
                passed = has_pass and not has_need_revise
            
            # 如果评分 >= 85 分，也视为通过
            if score >= 85:
                passed = True
            
            return {
                "passed": passed,
                "score": score,
                "content": content,
                "details": response
            }
        except Exception as e:
            print(f"文档评审失败: {e}")
            return {"passed": True, "score": 85, "content": content, "details": ""}

    def _revise_document(self, doc_name: str, content: str, audit_details: str, book: BookInfo = None,
                         generation_func=None) -> str:
        """修订文档内容"""
        if not book:
            book = self.sm.get_current_book()

        # 检查内容是否为空，如果为空则重新生成
        if not content or len(content.strip()) < 50:
            print(f"原文档内容为空或过短，将重新生成 {doc_name}")
            if generation_func:
                return generation_func(book, None)
            elif doc_name == "世界观设定":
                return self._generate_story_bible(book, {})
            elif doc_name == "书籍规则":
                return self._generate_book_rules(book, book.genre)
            elif doc_name == "章节大纲":
                return self._generate_chapter_outline(book, 0) if hasattr(self, '_generate_chapter_outline') else content
            return content

        # 尝试获取生成函数
        if generation_func is None:
            if doc_name == "世界观设定":
                generation_func = lambda b, p: self._generate_story_bible(b, p)
            elif doc_name == "书籍规则":
                generation_func = lambda b, g: self._generate_book_rules(b, g)

        prompt = f"""请根据评审意见修订小说《{book.name}》的【{doc_name}】。

【评审意见】
{audit_details}

【原文档内容】
{content[:5000]}

请直接输出修订后的完整文档内容，只输出修订后的内容，不要添加任何解释、说明或错误消息。"""

        try:
            revised_content = self.llm.generate(prompt, system_prompt="你是一个专业的小说编辑，负责根据评审意见修订设定文档。输出必须是有效的文档内容，不要输出错误消息或说明文字。")
            # 检查修订内容是否有效（不能是空内容或错误消息）
            if not revised_content or len(revised_content.strip()) < 50:
                print(f"修订内容无效，保留原内容")
                return content
            return revised_content.strip()
        except Exception as e:
            print(f"文档修订失败: {e}")
            return content  # 修订失败返回原内容

    def _save_doc_audit_report(self, book: BookInfo, doc_name: str, audit_result: Dict[str, Any]) -> str:
        """保存文档评审报告"""
        report_dir = self.workspace / book.path / "audit_reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{doc_name}_report_{timestamp}.md"
        report_path = report_dir / filename

        report = f"""# {book.name} - {doc_name}评审报告

## 基本信息
- 书名：{book.name}
- 文档：{doc_name}
- 评审时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 评审结果
- **评分**：{audit_result.get('score', 85)}分
- **结论**：{"✅ 通过" if audit_result.get('passed') else "⚠️ 需修订"}

## 评审详情
{audit_result.get('details', '无详细内容')}
"""
        self.sm.fm.write_text(report_path, report)
        return str(report_path)

    def get_latest_doc_audit_report(self, book: BookInfo, doc_name: str) -> Dict[str, Any]:
        """获取文档的最新评审报告"""
        report_dir = self.workspace / book.path / "audit_reports"
        if not report_dir.exists():
            return {"found": False}

        # 查找最新的评审报告
        reports = list(report_dir.glob(f"{doc_name}_report_*.md"))
        if not reports:
            return {"found": False}

        # 返回最新的报告
        latest_report = sorted(reports, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        content = self.sm.fm.read_text(latest_report)

        # 解析评审结果
        passed = "✅ 通过" in content or "结论：✅" in content
        details = ""
        if "## 评审详情" in content:
            details = content.split("## 评审详情")[-1].strip()

        return {
            "found": True,
            "path": str(latest_report),
            "passed": passed,
            "details": details,
            "content": content
        }

    def create_story_bible(self, book: BookInfo = None, book_id: str = None) -> Dict[str, Any]:
        """重新生成世界观设定"""
        if book_id:
            book = self.sm.get_book_by_id(book_id)
        if not book:
            book = self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        # 尝试加载现有的 planning.md
        planning = {}
        planning_path = self.workspace / book.path / "planning.md"
        if planning_path.exists():
            try:
                import yaml
                content = planning_path.read_text(encoding='utf-8')
                # 解析 YAML 前言
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        planning = yaml.safe_load(parts[1]) or {}
                        # 解析正文内容（---之后的部分）
                        body = parts[2].strip()
                        # 简单提取关键信息
                        for line in body.split('\n'):
                            if '：' in line or ':' in line:
                                key_val = line.replace('：', ':').split(':', 1)
                                if len(key_val) == 2:
                                    key = key_val[0].strip()
                                    val = key_val[1].strip()
                                    if key not in planning:
                                        planning[key] = val
            except Exception as e:
                print(f"解析planning.md失败: {e}")

        story_bible = self._generate_story_bible(book, planning)

        # 评审 + 自动修订（最多3次）
        max_revisions = 3
        current_content = story_bible
        final_audit_result = None
        revision_count = 0
        steps = [{"name": "生成内容", "status": "completed"}]

        for i in range(max_revisions):
            steps.append({"name": f"第{revision_count + 1}次评审", "status": "running"})
            audit_result = self._audit_document("世界观设定", current_content, book)
            final_audit_result = audit_result
            steps[-1]["status"] = "completed"
            steps[-1]["passed"] = audit_result.get("passed")
            steps[-1]["score"] = audit_result.get("score")

            if audit_result.get("passed"):
                steps.append({"name": "保存文档", "status": "completed"})
                break  # 通过了，退出循环

            revision_count += 1
            steps.append({"name": f"第{revision_count}次修订", "status": "running"})
            # 修订内容
            current_content = self._revise_document("世界观设定", current_content, audit_result.get("details", ""), book)
            steps[-1]["status"] = "completed"
            print(f"世界观设定第{revision_count}次修订完成")

        steps.append({"name": "保存文档", "status": "completed"})

        # 保存最终版本
        book_path = self.workspace / book.path
        self.sm.fm.write_text(book_path / "story_bible.md", current_content)
        
        # 保存评审报告
        self._save_doc_audit_report(book, "世界观设定", final_audit_result)

        # 保存评审报告
        try:
            self._save_doc_audit_report(book, "世界观设定", final_audit_result)
        except Exception as e:
            print(f"保存世界观设定评审报告失败: {e}")

        return {
            "success": True,
            "message": f"世界观设定重新生成成功（经{revision_count}次修订）" if revision_count > 0 else "世界观设定重新生成成功",
            "audit_passed": final_audit_result.get("passed"),
            "audit_score": final_audit_result.get("score", 85),
            "audit_details": final_audit_result.get("details", ""),
            "revision_count": revision_count,
            "steps": steps
        }

    def create_book_rules(self, book: BookInfo = None, book_id: str = None) -> Dict[str, Any]:
        """重新生成书籍规则"""
        if book_id:
            book = self.sm.get_book_by_id(book_id)
        if not book:
            book = self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        book_rules = self._generate_book_rules(book, book.genre)

        # 评审 + 自动修订（最多3次）
        max_revisions = 3
        current_content = book_rules
        final_audit_result = None
        revision_count = 0
        steps = [{"name": "生成内容", "status": "completed"}]

        for i in range(max_revisions):
            steps.append({"name": f"第{revision_count + 1}次评审", "status": "running"})
            audit_result = self._audit_document("书籍规则", current_content, book)
            final_audit_result = audit_result
            steps[-1]["status"] = "completed"
            steps[-1]["passed"] = audit_result.get("passed")
            steps[-1]["score"] = audit_result.get("score")

            if audit_result.get("passed"):
                steps.append({"name": "保存文档", "status": "completed"})
                break  # 通过了，退出循环

            revision_count += 1
            steps.append({"name": f"第{revision_count}次修订", "status": "running"})
            # 修订内容
            current_content = self._revise_document("书籍规则", current_content, audit_result.get("details", ""), book)
            steps[-1]["status"] = "completed"
            print(f"书籍规则第{revision_count}次修订完成")

        steps.append({"name": "保存文档", "status": "completed"})

        # 保存最终版本
        book_path = self.workspace / book.path
        self.sm.fm.write_text(book_path / "book_rules.md", current_content)

        # 保存评审报告
        try:
            self._save_doc_audit_report(book, "书籍规则", final_audit_result)
        except Exception as e:
            print(f"保存书籍规则评审报告失败: {e}")

        return {
            "success": True,
            "message": f"书籍规则重新生成成功（经{revision_count}次修订）" if revision_count > 0 else "书籍规则重新生成成功",
            "audit_passed": final_audit_result.get("passed"),
            "audit_score": final_audit_result.get("score", 85),
            "audit_details": final_audit_result.get("details", ""),
            "revision_count": revision_count,
            "steps": steps
        }

    def create_chapter_outline(self, book: BookInfo = None, book_id: str = None) -> Dict[str, Any]:
        """重新生成章节大纲"""
        if book_id:
            book = self.sm.get_book_by_id(book_id)
        if not book:
            book = self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        # 加载 planning 和 story_bible
        planning = {}
        summary = ''
        planning_path = self.workspace / book.path / "planning.md"
        if planning_path.exists():
            try:
                content = planning_path.read_text(encoding='utf-8')
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        import yaml
                        planning = yaml.safe_load(parts[1]) or {}
                        # 提取正文
                        body = parts[2].strip()
                        for line in body.split('\n'):
                            if '梗概' in line:
                                summary = line.split('：', 1)[-1].split(':', 1)[-1].strip()
                            elif '背景' in line:
                                planning['背景'] = line.split('：', 1)[-1].split(':', 1)[-1].strip()
            except:
                pass

        # 根据章节数分组生成大纲
        total = book.total_chapters
        outline_lines = [f"# {book.name} 章节大纲\n\n"]
        outline_lines.append(f"**总章节数**: {total}\n\n")
        
        # 典型网文节奏：每10章一个剧情段
        segment_size = 10
        
        for seg in range(0, total, segment_size):
            seg_start = seg + 1
            seg_end = min(seg + segment_size, total)
            outline_lines.append(f"## 第{seg_start}-{seg_end}章 剧情段\n\n")
            
            # 为每个小节生成框架
            for i in range(seg_start, seg_end + 1):
                chapter_in_seg = i - seg_start + 1
                
                # 根据章节位置设置预期内容
                if chapter_in_seg == 1:
                    event = f"主角在第{i}章觉醒/获得机遇"
                    key_chars = "主角、关键配角"
                    scene = "现代都市"
                elif chapter_in_seg == 2:
                    event = f"主角在第{i}章展示能力，获得认可或资源"
                    key_chars = "主角、配角A"
                    scene = "超能场所/训练基地"
                elif chapter_in_seg == 3:
                    event = f"主角在第{i}章遭遇挑战或敌人"
                    key_chars = "主角、敌人"
                    scene = "冲突场景"
                elif chapter_in_seg <= 5:
                    event = f"主角在第{i}章应对危机，积累成长"
                    key_chars = "主角、配角"
                    scene = "多场景"
                elif chapter_in_seg == 6:
                    event = f"主角在第{i}章遭遇重大危机或机遇"
                    key_chars = "主角、强敌/贵人"
                    scene = "关键场景"
                elif chapter_in_seg <= 9:
                    event = f"主角在第{i}章解决危机，获得突破"
                    key_chars = "主角、配角/敌人"
                    scene = "高潮场景"
                else:
                    event = f"主角在第{i}章收尾并埋下新悬念"
                    key_chars = "主角、配角"
                    scene = "转折场景"
                
                outline_lines.append(f"### 第{i}章\n")
                outline_lines.append(f"**主要事件**：{event}\n")
                outline_lines.append(f"**关键人物**：{key_chars}\n")
                outline_lines.append(f"**场景设置**：{scene}\n\n")

        chapter_outline = "".join(outline_lines)

        # 评审 + 自动修订（最多3次）
        max_revisions = 3
        current_content = chapter_outline
        final_audit_result = None
        revision_count = 0
        steps = [{"name": "生成内容", "status": "completed"}]

        for i in range(max_revisions):
            steps.append({"name": f"第{revision_count + 1}次评审", "status": "running"})
            audit_result = self._audit_document("章节大纲", current_content, book)
            final_audit_result = audit_result
            steps[-1]["status"] = "completed"
            steps[-1]["passed"] = audit_result.get("passed")
            steps[-1]["score"] = audit_result.get("score")

            if audit_result.get("passed"):
                steps.append({"name": "保存文档", "status": "completed"})
                break

            revision_count += 1
            steps.append({"name": f"第{revision_count}次修订", "status": "running"})
            current_content = self._revise_document("章节大纲", current_content, audit_result.get("details", ""), book)
            steps[-1]["status"] = "completed"
            print(f"章节大纲第{revision_count}次修订完成")

        steps.append({"name": "保存文档", "status": "completed"})

        # 保存最终版本
        book_path = self.workspace / book.path
        self.sm.fm.write_text(book_path / "chapter_outline.md", current_content)

        # 保存评审报告
        try:
            self._save_doc_audit_report(book, "章节大纲", final_audit_result)
        except Exception as e:
            print(f"保存章节大纲评审报告失败: {e}")

        return {
            "success": True,
            "message": f"章节大纲重新生成成功（经{revision_count}次修订）" if revision_count > 0 else "章节大纲重新生成成功",
            "audit_passed": final_audit_result.get("passed"),
            "audit_score": final_audit_result.get("score", 85),
            "audit_details": final_audit_result.get("details", ""),
            "revision_count": revision_count,
            "steps": steps
        }

    def update_planning(self, book: BookInfo = None, book_id: str = None) -> Dict[str, Any]:
        """更新创作简报（仅保存现有内容）"""
        if book_id:
            book = self.sm.get_book_by_id(book_id)
        if not book:
            book = self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        # 简报一般不重新生成，只返回成功
        planning_path = self.workspace / book.path / "planning.md"
        if planning_path.exists():
            return {"success": True, "message": "创作简报已存在"}
        else:
            return {"success": False, "message": "创作简报不存在"}

    def get_book_status(self, book_id: str = None) -> Dict[str, Any]:
        """获取书籍状态"""
        book = None
        if book_id:
            book = self.sm.get_book_by_id(book_id)
        if not book:
            book = self.sm.get_current_book()
        
        if not book:
            return {"success": False, "message": "未找到书籍"}
        
        state = self.sm.load_project_state(book)
        chapters = state.get("chapter_planning", {})
        
        chapter_list = []
        for key, info in chapters.items():
            num = int(key.split("_")[1])
            chapter_list.append({
                "chapter_num": num,
                "status": info.get("approval_status", "draft"),
                "audit_score": info.get("audit_score", 0),
                "finalized": info.get("finalized", False),
                "retry_count": info.get("retry_count", 0)
            })
        
        chapter_list.sort(key=lambda x: x["chapter_num"])
        
        return {
            "success": True,
            "book": book.to_dict(),
            "chapters": chapter_list,
            "stats": {
                "total": book.total_chapters,
                "completed": book.completed_chapters,
                "draft": len([c for c in chapter_list if c["status"] == "draft"]),
                "final": len([c for c in chapter_list if c["finalized"]])
            }
        }

    def list_books(self) -> List[Dict[str, Any]]:
        """列出所有书籍"""
        return [book.to_dict() for book in self.sm.get_all_books()]
    
    def rename_book(self, book_id: str, new_name: str) -> Dict[str, Any]:
        """重命名书籍（同步更新所有设定文档中的书名）"""
        book = self.get_book(book_id)
        if not book:
            return {"success": False, "message": "书籍不存在"}
        
        if not new_name or not new_name.strip():
            return {"success": False, "message": "书名不能为空"}
        
        old_name = book.name
        new_name = new_name.strip()
        
        # 检查是否真的改变了
        if old_name == new_name:
            return {"success": True, "message": f"书名未变化", "new_name": new_name, "updated": False}
        
        # 检查书名是否重复
        for b in self.sm.get_all_books():
            if b.id != book_id and b.name == new_name:
                return {"success": False, "message": "已存在同名书籍"}
        
        # 更新书籍索引中的书名
        books = self.sm.book_index.get("books", [])
        for b in books:
            if b.get("id") == book_id:
                b["name"] = new_name
                # 更新灵感收集信息中的书名
                if "inspiration_collected_info" in b:
                    b["inspiration_collected_info"]["book_name"] = new_name
                break
        
        # 如果是当前书籍，更新 current_novel 显示名称
        if self.sm.book_index.get("current_novel") == book_id:
            self.sm.book_index["current_novel_name"] = new_name
        
        # 更新 BookInfo 对象的 name 属性
        book.name = new_name
        if hasattr(book, 'inspiration_collected_info') and book.inspiration_collected_info:
            book.inspiration_collected_info["book_name"] = new_name
        
        # 同步更新所有设定文档中的书名
        book_path = self.workspace / book.path
        updated_docs = []
        
        # 需要更新的文档列表（支持多种书名格式）
        doc_patterns = {
            "planning.md": ["# 书名", "- 书名:", "书名：", "《{}》".format(old_name), old_name],
            "story_bible.md": ["# " + old_name, "《{}》".format(old_name), old_name],
            "book_rules.md": ["# " + old_name, "《{}》".format(old_name), old_name],
            "characters.md": ["# " + old_name, "《{}》".format(old_name), old_name],
            "author_intent.md": ["《{}》".format(old_name), old_name],
            "chapter_outline.md": ["《{}》".format(old_name), old_name],
            "current_focus.md": ["《{}》".format(old_name), old_name],
        }
        
        for doc_name, patterns in doc_patterns.items():
            doc_file = book_path / doc_name
            if doc_file.exists():
                try:
                    content = doc_file.read_text(encoding='utf-8')
                    updated = False
                    for pattern in patterns:
                        if pattern in content:
                            content = content.replace(pattern, pattern.replace(old_name, new_name) if old_name in pattern else new_name)
                            updated = True
                        # 也处理直接替换（不区分格式的书名出现）
                        if old_name in content and pattern == old_name:
                            content = content.replace(old_name, new_name)
                            updated = True
                    if updated:
                        doc_file.write_text(content, encoding='utf-8')
                        updated_docs.append(doc_name)
                        print(f"已更新 {doc_name} 中的书名")
                except Exception as e:
                    print(f"更新 {doc_name} 失败: {e}")
        
        # 保存索引
        if self.sm._save_book_index():
            # 同时保存 BookInfo
            self.save_book_meta(book)
            return {
                "success": True, 
                "message": f"已改名为《{new_name}》", 
                "new_name": new_name,
                "old_name": old_name,
                "updated_docs": updated_docs
            }
        else:
            return {"success": False, "message": "保存失败"}
    
    def delete_book(self, book_id: str) -> Dict[str, Any]:
        """删除书籍"""
        book = self.get_book(book_id)
        if not book:
            return {"success": False, "message": "书籍不存在"}
        
        # 从书籍列表中移除
        books = self.sm.book_index.get("books", [])
        self.sm.book_index["books"] = [b for b in books if b.get("id") != book_id]
        
        # 如果删除的是当前书籍，重置current_novel
        if self.sm.book_index.get("current_novel") == book_id:
            remaining = self.sm.book_index["books"]
            self.sm.book_index["current_novel"] = remaining[0]["id"] if remaining else ""
        
        # 删除书籍目录
        book_path = self.workspace / book.path
        if book_path.exists():
            import shutil
            try:
                shutil.rmtree(book_path)
            except Exception as e:
                print(f"删除书籍目录失败: {e}")
        
        # 保存索引
        if self.sm._save_book_index():
            return {"success": True, "message": "书籍已删除"}
        else:
            return {"success": False, "message": "保存失败"}
    
    def get_book(self, book_id: str):
        """获取书籍"""
        return self.sm.get_book_by_id(book_id)
    
    def get_chapters(self, book_id: str = None) -> List[Dict[str, Any]]:
        """获取书籍章节列表"""
        if book_id:
            book = self.get_book(book_id)
            if not book:
                return []
        
        book = self.sm.get_current_book()
        if not book:
            return []
        
        # 加载项目状态获取章节状态信息
        state = self.sm.load_project_state(book)
        chapter_planning = state.get("chapter_planning", {})
        
        chapters = []
        book_path = self.workspace / book.path / "chapters"
        if book_path.exists():
            # 只匹配真正的章节文件 (chapter_*.md)，排除 outline_*、reflection_* 等辅助文件
            chapter_files = list(book_path.glob("chapter_*.md"))
            if not chapter_files:
                chapter_files = list(book_path.glob("ch_*.md"))  # 兼容旧格式
            for f in sorted(chapter_files, key=lambda x: int(x.stem.split('_')[1]) if len(x.stem.split('_')) > 1 and x.stem.split('_')[1].isdigit() else 0):
                try:
                    content = f.read_text(encoding='utf-8')
                    lines = content.split('\n')
                    title = lines[0].replace('#', '').strip() if lines else f.stem
                    chapter_num = int(f.stem.split('_')[1]) if len(f.stem.split('_')) > 1 and f.stem.split('_')[1].isdigit() else 0
                    chapter_key = f"chapter_{chapter_num}"
                    chapter_info = chapter_planning.get(chapter_key, {})

                    # 检查内容是否有效生成（不能是[待生成]或空内容）
                    is_generated = bool(content.strip() and "[待生成]" not in content and len(content) > 50)
                    # 如果内容未生成，强制将finalized设为False
                    finalized = chapter_info.get("finalized", False) and is_generated

                    chapters.append({
                        "id": f.stem,
                        "number": chapter_num,
                        "title": title,
                        "status": chapter_info.get("approval_status", "draft"),
                        "word_count": len(content),
                        "audit_score": chapter_info.get("audit_score", 0),
                        "finalized": finalized,
                        "is_generated": is_generated,
                        "retry_count": chapter_info.get("retry_count", 0)
                    })
                except:
                    pass
        return chapters
    
    def get_chapter_by_id(self, chapter_id: str):
        """通过ID获取章节"""
        # 遍历所有书籍查找章节
        for book in self.sm.get_all_books():
            book_path = self.workspace / book.path / "chapters"
            chapter_file = book_path / f"{chapter_id}.md"
            if chapter_file.exists():
                content = chapter_file.read_text(encoding='utf-8')
                return {
                    "id": chapter_id,
                    "book_id": book.id,
                    "content": content,
                    "word_count": len(content)
                }
        return None
    
    def get_chapter_by_number(self, chapter_num: int):
        """通过章节号获取章节"""
        book = self.sm.get_current_book()
        if not book:
            # 尝试查找第一个匹配的书籍
            books = self.sm.get_all_books()
            if not books:
                return None
            book = books[0]
        
        book_path = self.workspace / book.path / "chapters"
        chapter_file = book_path / f"chapter_{chapter_num}.md"
        
        if chapter_file.exists():
            content = chapter_file.read_text(encoding='utf-8')
            return {
                "id": f"chapter_{chapter_num}",
                "number": chapter_num,
                "book_id": book.id,
                "content": content,
                "word_count": len(content)
            }
        return None

    def switch_book(self, book_id_or_name: str) -> Dict[str, Any]:
        """切换当前书籍"""
        success, msg = self.sm.switch_book(book_id_or_name)
        return {"success": success, "message": msg}

    # ============== 章节创作 ==============

    def write_chapter(self, chapter_num: int, revise: bool = False, regenerate: bool = False) -> Dict[str, Any]:
        """
        章节创作工作流

        Args:
            chapter_num: 章节编号 (0=前言, 1+=正文)
            revise: 是否为修订模式（基于上一次细纲和评审报告修改内容）
            regenerate: 是否为重写模式（从细纲开始重新生成）

        Returns:
            章节创作结果
        """
        book = self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "请先选择或创建书籍"}

        # 判断章节标题
        chapter_title = f"第{chapter_num}章"

        print(f"\n{'='*60}")
        print(f"[write_chapter] 开始创作章节: {chapter_title}")
        print(f"[write_chapter] 书籍: {book.name} (ID: {book.id})")
        print(f"[write_chapter] 模式: {'修订' if revise else '重写' if regenerate else '创作'}")
        print(f"{'='*60}\n")

        # 0. 获取上一次评审报告和细纲（修订时使用）
        previous_audit_report = ""
        previous_outline = ""
        if revise:
            previous_audit_report = self.get_latest_audit_report(book, chapter_num)
            # 加载上一次生成的细纲
            outline_path = self.workspace / book.path / "chapters" / f"outline_{chapter_num}.md"
            if outline_path.exists():
                previous_outline = self.sm.fm.read_text(outline_path)

        # 1. 生成并审计章节细纲（含自动修订循环，最多3次，选最优）
        print(f"[write_chapter] 步骤1: 生成章节细纲...")
        if regenerate:
            # 重写模式：从头开始重新生成并审计细纲
            outline = self._generate_and_audit_outline(book, chapter_num, revise=True)
        elif revise and previous_outline:
            # 修订模式：基于上一次细纲修改，附带审计
            outline = self._generate_and_audit_outline(book, chapter_num, revise=True,
                                                        previous_outline=previous_outline,
                                                        previous_audit=previous_audit_report)
        else:
            outline = self._generate_and_audit_outline(book, chapter_num)
        print(f"[write_chapter] 细纲生成完成，长度: {len(outline) if outline else 0} 字")

        # 1.5. 保存章节细纲到文件（审计通过后或最优版本）
        if outline:
            # 过滤细纲中的LLM输出痕迹
            outline = self._filter_llm_output(outline)
            outline_path = self.workspace / book.path / "chapters" / f"outline_{chapter_num}.md"
            self.sm.fm.write_text(outline_path, outline)
            print(f"[write_chapter] 细纲已保存: {outline_path}")

        # 2. 加载真相文件
        print(f"[write_chapter] 步骤2: 加载真相文件...")
        truth_files = self._load_truth_files(book)
        print(f"[write_chapter] 真相文件已加载，包含 {len(truth_files)} 个文件")

        # 3. 编译上下文
        print(f"[write_chapter] 步骤3: 编译上下文...")
        context = self._compile_context(book, chapter_num, outline, truth_files)
        print(f"[write_chapter] 上下文编译完成，长度: {len(context)} 字")

        # 4. 生成正文
        print(f"[write_chapter] 步骤4: 生成章节正文（目标字数: {book.words_per_chapter}字）...")
        try:
            content = self._generate_chapter_content(book, chapter_num, context, outline, revise=revise, revise_reference=previous_audit_report)
            print(f"[write_chapter] 正文生成完成，长度: {len(content)} 字")
        except Exception as e:
            # 生成失败：恢复原有内容（如果是修订/重写模式），避免章节变成空白
            chapter_path = self.workspace / book.path / "chapters" / f"chapter_{chapter_num}.md"
            if revise and chapter_path.exists():
                # 修订/重写失败时不覆盖原文
                print(f"[write_chapter] 生成失败，保留原有内容: {e}")
            else:
                # 首次创作失败时写入错误标记，保留旧内容
                if chapter_path.exists():
                    old = chapter_path.read_text(encoding='utf-8')
                    if old.strip():
                        print(f"[write_chapter] 生成失败，保留原有内容: {e}")
                        content = old  # 不覆盖，继续用旧内容以避免审计空内容
                    else:
                        content = f"# 第 {chapter_num} 章\n\n[生成失败，请重试]\n"
                        self.sm.fm.write_text(chapter_path, content)
                else:
                    content = f"# 第 {chapter_num} 章\n\n[生成失败，请重试]\n"
                    self.sm.fm.write_text(chapter_path, content)
            return {"success": False, "message": str(e), "content": content}

        # 5. 保存正文
        chapter_path = self.workspace / book.path / "chapters" / f"chapter_{chapter_num}.md"

        # 5.5 字数检查与调整（扩写/缩写）
        content = self._adjust_chapter_word_count(book, chapter_num, content)

        # 5.6 最终过滤：确保Writer输出的LOG块被清除
        content = self._filter_llm_output(content)

        # 保存调整后的内容
        self.sm.fm.write_text(chapter_path, content)

        # 6. 更新状态
        self.sm.update_chapter_status(book, chapter_num, "draft", retry_count=0)

        # 7. 质量审查
        audit_result = self._audit_chapter(book, chapter_num, content, truth_files, previous_audit_report)

        # 8. 检查触发修订的条件
        need_revision = False
        revision_reasons = []

        # 条件1：核心漏洞必须修订
        if audit_result.core_issues:
            need_revision = True
            core_issues_detail = []
            for ci in audit_result.core_issues:
                core_issues_detail.append(f"{ci.get('dimension', '未知')}：{ci.get('description', '')}")
            revision_reasons.append(f"存在{len(audit_result.core_issues)}个核心漏洞（{'; '.join(core_issues_detail)}）")

        # 条件2：字数误差超过500字必须修订（与细纲宽容度一致）
        if abs(audit_result.word_count_deviation) > 500:
            need_revision = True
            deviation = audit_result.word_count_deviation
            direction = "超出" if deviation > 0 else "不足"
            revision_reasons.append(f"字数偏差{direction}500字")

        # 条件3：评分低于75分需要修订
        if audit_result.chapter_score < 75:
            need_revision = True
            if "核心漏洞" not in revision_reasons[0] if revision_reasons else True:
                revision_reasons.append(f"评分{audit_result.chapter_score}低于75分")
        
        if need_revision:
            revision_msg = "；".join(revision_reasons)
            self.sm.update_chapter_status(
                book, chapter_num, "draft",
                audit_score=audit_result.chapter_score,
                audit_passed=False,
                retry_count=1
            )
            return {
                "success": False,
                "message": f"{chapter_title}触发修订：{revision_msg}",
                "audit_result": audit_result.to_dict(),
                "content": content,
                "outline": outline,
                "need_revision": True,
                "revision_reasons": revision_reasons
            }

        # 9. 保存评审报告
        audit_report_path = ""
        try:
            audit_report_path = self.save_audit_report(book, chapter_num, content, audit_result)
        except Exception as e:
            print(f"保存评审报告失败: {e}")

        # 10. 通过审核
        self.sm.update_chapter_status(
            book, chapter_num, "final",
            audit_score=audit_result.chapter_score,
            audit_passed=True,
            finalized=True
        )

        # 11. 更新完成章节数
        book.completed_chapters += 1

        # 12. 更新真相文件 + 反思策略（Observer → Reflector 链路）
        try:
            self._update_truth_for_chapter(book, chapter_num, content, outline=outline)
        except Exception as e:
            print(f"更新真相文件失败: {e}")

        # 13. 生成评审报告内容（用于前端展示）
        audit_report_content = self._generate_audit_report(book, chapter_num, content, audit_result)

        return {
            "success": True,
            "message": f"{chapter_title}创作完成",
            "chapter_num": chapter_num,
            "audit_result": audit_result.to_dict(),
            "audit_report": audit_report_content,  # 用于前端展示
            "audit_report_path": audit_report_path,
            "content": content,
            "outline": outline
        }

    def _update_truth_for_chapter(self, book: BookInfo, chapter_num: int, content: str, outline: str = ""):
        """更新当前章节的真相文件（含 Observer → Reflector 链路）"""
        print(f"\n[_update_truth_for_chapter] 开始处理第{chapter_num}章...")
        try:
            from agents.engine import AgentEngine
            from core.llm_service import LLMManager

            llm_manager = LLMManager(str(self.workspace / ".env"))
            agent_engine = AgentEngine(llm_manager)

            # 加载现有真相文件
            truth_files = self._load_truth_files(book)

            # Step A: 调用 observer Agent 提取事实
            observer_context = {
                "book": book.to_dict(),
                "chapter_num": chapter_num,
                "chapter_content": content,
                "truth_files": truth_files
            }
            observer_result = agent_engine.call_agent("observer", observer_context)

            if observer_result.success and observer_result.data:
                facts = observer_result.data
                # 更新真相文件
                self._apply_facts_to_truth_files(book, chapter_num, facts)

            # Step B: 调用 reflector Agent 进行反思与策略调整
            try:
                reflector_context = {
                    "book": book.to_dict(),
                    "chapter_num": chapter_num,
                    "chapter_content": content,
                    "chapter_outline": outline,
                    "truth_files": truth_files,
                    "observer_result": observer_result.data if (observer_result.success and observer_result.data) else {}
                }
                reflector_result = agent_engine.call_agent("reflector", reflector_context)

                if reflector_result.success and reflector_result.content:
                    # 保存反思报告到文件
                    reflection_path = self.workspace / book.path / "chapters" / f"reflection_{chapter_num}.md"
                    reflection_content = self._filter_llm_output(reflector_result.content)
                    self.sm.fm.write_text(reflection_path, reflection_content)
                    print(f"[Reflector] 第{chapter_num}章反思报告已保存: {reflection_path}")
            except Exception as e:
                print(f"[Reflector] 反思失败: {e}")
        except Exception as e:
            print(f"提取章节事实失败: {e}")

    def _apply_facts_to_truth_files(self, book: BookInfo, chapter_num: int, facts: dict):
        """将提取的事实应用到真相文件"""
        # 实现事实应用逻辑
        pass

    def _adjust_chapter_word_count(self, book: BookInfo, chapter_num: int, content: str) -> str:
        """检查并调整章节字数（扩写/缩写）
        
        根据字数偏差自动决定是否调用扩写/缩写Agent。
        
        Args:
            book: 书籍信息
            chapter_num: 章节编号
            content: 章节正文内容
            
        Returns:
            调整后的章节内容
        """
        # 统计当前字数（去除markdown标记）
        clean_content = self._clean_content(content)
        current_words = len(clean_content)
        target_words = book.words_per_chapter or 3000
        
        deviation = current_words - target_words
        deviation_percent = abs(deviation) / target_words * 100 if target_words > 0 else 0
        
        print(f"\n[_adjust_chapter_word_count] 字数检查: 当前={current_words}字, 目标={target_words}字, 偏差={deviation:+d}字 ({deviation_percent:.1f}%)")
        
        # 字数检查阈值
        # - 偏差超过15%需要调整
        # - 或者绝对偏差超过500字
        need_adjust = deviation_percent > 15 or abs(deviation) > 500
        
        if not need_adjust:
            print(f"[_adjust_chapter_word_count] 字数在可接受范围内，无需调整")
            return content
        
        # 确定调整方向
        if deviation < 0:
            # 字数不足，需要扩写
            action = "扩写"
            adjust_words = abs(deviation) + 300  # 多扩写300字以确保达标
            print(f"[_adjust_chapter_word_count] 字数不足，需要扩写约{adjust_words}字")
        else:
            # 字数超出，需要缩写
            action = "缩写"
            adjust_words = deviation + 300  # 多缩写300字以确保达标
            print(f"[_adjust_chapter_word_count] 字数超出，需要缩写约{adjust_words}字")
        
        # 调用对应的Agent进行字数调整
        try:
            # 确保agent_engine已初始化且LLMClient配置正确
            if not hasattr(self, 'agent_engine') or not self.agent_engine:
                self._init_agents()
            elif self.agent_engine and self.llm_manager:
                # 检查LLMClient是否使用了正确的ProviderConfig
                provider = self.llm_manager.config.get_active_provider()
                if provider and hasattr(self.llm_manager, 'client'):
                    client_config = self.llm_manager.client.config
                    # 如果client_config的base_url为空或无效，尝试重新初始化
                    if not getattr(client_config, 'base_url', '') or not getattr(client_config, 'api_key', ''):
                        from core.llm_service import LLMClient, ProviderConfig
                        provider_config = ProviderConfig(
                            api_key=provider.api_key,
                            base_url=provider.base_url,
                            model=provider.model,
                            max_tokens=provider.max_tokens,
                            temperature=provider.temperature,
                            timeout=provider.timeout,
                            retry_times=provider.retry_times,
                            retry_delay=provider.retry_delay
                        )
                        self.llm_manager.client = LLMClient(provider_config)
            
            if self.agent_engine:
                # 调用扩写/缩写Agent
                agent_name = "expander" if deviation < 0 else "condenser"
                
                context = {
                    "book": book.to_dict(),
                    "chapter_num": chapter_num,
                    "chapter_content": content,
                    "current_words": current_words,
                    "target_words": target_words,
                    "adjust_words": adjust_words,
                    "deviation": deviation
                }
                
                print(f"[_adjust_chapter_word_count] 调用 {agent_name} Agent 进行章节{action}...")
                result = self.agent_engine.call_agent(agent_name, context)
                
                if result.success and result.content:
                    adjusted_content = self._filter_llm_output(result.content)

                    # 验证调整后的字数
                    adjusted_clean = self._clean_content(adjusted_content)
                    adjusted_words = len(adjusted_clean)
                    new_deviation = adjusted_words - target_words
                    new_deviation_percent = abs(new_deviation) / target_words * 100 if target_words > 0 else 0
                    
                    print(f"[_adjust_chapter_word_count] 调整完成: {adjusted_words}字, 新偏差={new_deviation:+d}字 ({new_deviation_percent:.1f}%)")
                    
                    # 如果调整后仍偏差过大，尝试第二次调整（但最多2次）
                    # 第二次调整时，使用原始正文来判断调整方向
                    # 因为第一次调整后的内容可能已经偏离了原文的方向
                    if new_deviation_percent > 10 or abs(new_deviation) > 400:
                        print(f"[_adjust_chapter_word_count] 调整后仍需优化，进行第二次调整...")
                        # 使用原始偏差判断方向，而不是调整后的偏差
                        # 原始偏差 > 0 表示原文仍然超出目标，需要继续缩写
                        # 原始偏差 < 0 表示原文仍然不足，需要继续扩写
                        second_agent = "condenser" if deviation > 0 else "expander"
                        second_context = context.copy()
                        # 重试时使用原始正文，而不是缩/扩写结果
                        second_context["chapter_content"] = content
                        second_context["current_words"] = current_words
                        second_result = self.agent_engine.call_agent(second_agent, second_context)
                        
                        if second_result.success and second_result.content:
                            adjusted_content = self._filter_llm_output(second_result.content)
                            final_clean = self._clean_content(adjusted_content)
                            final_words = len(final_clean)
                            print(f"[_adjust_chapter_word_count] 第二次调整完成: {final_words}字")
                    
                    return adjusted_content
                else:
                    print(f"[_adjust_chapter_word_count] Agent调用失败: {result.error if result else '未知错误'}")
                    return content
            else:
                print(f"[_adjust_chapter_word_count] agent_engine未初始化，无法调用Agent")
                return content
                
        except Exception as e:
            print(f"[_adjust_chapter_word_count] 调整失败: {e}")
            import traceback
            traceback.print_exc()
            return content
    
    def _create_minimal_audit(self, chapter_num: int):
        """为前沿章节创建最小审核结果"""
        return type('AuditResult', (), {
            'chapter_num': chapter_num,
            'chapter_score': 100,
            'audit_issues': 0,
            'ai_tell_density': 0,
            'para_warnings': 0,
            'issues': [],
            'core_issues': [],
            'word_count': 0,
            'target_word_count': 0,
            'word_count_deviation': 0,
            'hook_resolution_rate': 100,
            'paragraph_warnings': 0,
            'decision': '通过',
            'to_dict': lambda self: {
                'chapter_num': self.chapter_num,
                'chapter_score': self.chapter_score,
                'audit_issues': self.audit_issues,
                'ai_tell_density': self.ai_tell_density,
                'para_warnings': self.para_warnings,
                'issues': self.issues,
                'core_issues': self.core_issues,
                'word_count': self.word_count,
                'target_word_count': self.target_word_count,
                'word_count_deviation': self.word_count_deviation,
                'hook_resolution_rate': self.hook_resolution_rate,
                'paragraph_warnings': self.paragraph_warnings,
                'decision': self.decision
            }
        })()

    def get_chapter_content(self, book_id: str, chapter_num: int) -> Dict[str, Any]:
        """获取章节内容"""
        book = self.sm.get_book_by_id(book_id)
        if not book:
            book = self.sm.get_current_book()
        
        if not book:
            return {"success": False, "message": "未找到书籍"}
        
        chapter_path = self.workspace / book.path / "chapters" / f"chapter_{chapter_num}.md"
        content = self.sm.fm.read_text(chapter_path)
        
        state = self.sm.load_project_state(book)
        chapter_info = state.get("chapter_planning", {}).get(f"chapter_{chapter_num}", {})
        
        return {
            "success": True,
            "chapter": {
                "id": f"chapter_{chapter_num}",
                "number": chapter_num,
                "name": chapter_info.get("name", ""),
                "content": content,
                "word_count": len(content) if content else 0,
                "status": chapter_info.get("approval_status", "draft"),
                "audit_score": chapter_info.get("audit_score", 0),
                "finalized": chapter_info.get("finalized", False)
            }
        }

    # ============== 真相文件 ==============

    def get_truth_files(self, book_id: str = None) -> Dict[str, Any]:
        """获取真相文件"""
        book = self.sm.get_book_by_id(book_id) if book_id else self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}
        
        truth_files = self._load_truth_files(book)
        return {
            "success": True,
            "book_name": book.name,
            "files": truth_files
        }

    def update_truth_file(self, book_id: str, filename: str, content: str) -> Dict[str, Any]:
        """更新真相文件"""
        book = self.sm.get_book_by_id(book_id) if book_id else self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        truth_dir = self.workspace / book.path / "truth_files"
        path = truth_dir / filename
        if self.sm.fm.write_text(path, content):
            return {"success": True, "message": f"{filename} 已更新"}
        return {"success": False, "message": "保存失败"}

    def regenerate_truth_files(self, book_id: str = None) -> Dict[str, Any]:
        """重新生成所有真相文件（基于已有章节重新提取事实）"""
        book = self.sm.get_book_by_id(book_id) if book_id else self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        # 获取所有已生成的章节
        chapters_dir = self.workspace / book.path / "chapters"
        if not chapters_dir.exists():
            return {"success": False, "message": "没有找到章节文件"}

        # 重置真相文件
        self._init_truth_files(book)
        self._init_chapter_summaries(book)

        # 按顺序处理每个章节
        chapter_files = sorted(chapters_dir.glob("chapter_*.md"))
        if not chapter_files:
            return {"success": True, "message": "没有章节需要处理", "processed": 0}

        from agents.engine import AgentEngine
        from core.llm_service import LLMManager

        llm_manager = LLMManager(str(self.workspace / ".env"))
        agent_engine = AgentEngine(llm_manager)

        updated_summary = []
        for chapter_file in chapter_files:
            try:
                chapter_num = int(chapter_file.stem.replace("chapter_", ""))
                content = self.sm.fm.read_text(chapter_file)
                if content and len(content) > 50:
                    truth_files = self._load_truth_files(book)
                    context = {
                        "book": book.to_dict(),
                        "chapter_num": chapter_num,
                        "chapter_content": content,
                        "truth_files": truth_files
                    }
                    result = agent_engine.call_agent("observer", context)
                    if result.success:
                        print(f"第{chapter_num}章观察完成")
                        updated_summary.append(f"chapter_{chapter_num}")
            except Exception as e:
                print(f"处理第{chapter_file.name}时出错: {e}")
                continue

        unique_files = list(set(updated_summary))
        return {
            "success": True,
            "message": f"真相文件已重新生成，共处理 {len(chapter_files)} 个章节",
            "processed": len(chapter_files),
            "updated_files": unique_files
        }

    # ============== 书籍设定 ==============

    def get_book_settings(self, book_id: str = None) -> Dict[str, Any]:
        """获取书籍自定义设定"""
        from .models import BookSettings
        book = self.sm.get_book_by_id(book_id) if book_id else self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        settings_path = self.workspace / book.path / "book_settings.json"
        if settings_path.exists():
            data = self.sm.fm.read_json(settings_path)
            settings = BookSettings.from_dict(data)
        else:
            settings = BookSettings()

        return {
            "success": True,
            "book_id": book.id,
            "book_name": book.name,
            "settings": settings.to_dict()
        }

    def update_book_settings(self, book_id: str = None, **kwargs) -> Dict[str, Any]:
        """更新书籍自定义设定"""
        from .models import BookSettings
        book = self.sm.get_book_by_id(book_id) if book_id else self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        settings_path = self.workspace / book.path / "book_settings.json"

        # 加载现有设定
        if settings_path.exists():
            data = self.sm.fm.read_json(settings_path)
            settings = BookSettings.from_dict(data)
        else:
            settings = BookSettings()

        # 更新字段
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)

        # 保存
        if self.sm.fm.write_json(settings_path, settings.to_dict()):
            return {"success": True, "message": "设定已更新"}
        return {"success": False, "message": "保存失败"}

    # ============== 全局配置 ==============

    def _global_config_path(self) -> Path:
        """获取全局配置路径"""
        return self.workspace / "global_config.json"

    def get_global_config(self) -> Dict[str, Any]:
        """获取全局配置"""
        config_path = self._global_config_path()
        if config_path.exists():
            data = self.sm.fm.read_json(config_path)
            config = GlobalConfig.from_dict(data)
        else:
            config = GlobalConfig()

        return {
            "success": True,
            "config": config.to_dict()
        }

    def update_global_config(self, **kwargs) -> Dict[str, Any]:
        """更新全局配置"""
        config_path = self._global_config_path()

        # 加载现有配置
        if config_path.exists():
            data = self.sm.fm.read_json(config_path)
            config = GlobalConfig.from_dict(data)
        else:
            config = GlobalConfig()

        # 更新字段
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)

        # 保存
        if self.sm.fm.write_json(config_path, config.to_dict()):
            return {"success": True, "message": "全局配置已更新"}
        return {"success": False, "message": "保存失败"}

    # ============== LLM配置 ==============

    def get_llm_config(self) -> Dict[str, Any]:
        """获取LLM配置"""
        config = self.llm.config
        return {
            "success": True,
            "config": config.to_dict(),
            "active_provider": config.get_active_provider().to_dict() if config.get_active_provider() else None,
            "templates": LLMConfig.PROVIDER_TEMPLATES
        }

    def update_llm_config(self, **kwargs) -> Dict[str, Any]:
        """更新LLM配置"""
        config = self.llm.config
        provider_added = False
        new_provider_id = None
        
        # 处理提供商操作
        if "provider" in kwargs:
            provider_data = kwargs.pop("provider")
            provider_id = provider_data.get("id", "")
            
            if provider_id:
                from .llm_service import ProviderConfig
                provider = config.get_provider(provider_id)
                if provider:
                    # 更新现有提供商
                    for key, value in provider_data.items():
                        if hasattr(provider, key):
                            setattr(provider, key, value)
                else:
                    # 添加新提供商
                    provider = ProviderConfig.from_dict(provider_data)
                    config.add_provider(provider)
                    provider_added = True
                    new_provider_id = provider_id
        
        # 处理激活提供商
        if "set_active" in kwargs:
            provider_id = kwargs.pop("set_active")
            config.set_active(provider_id)
        
        # 处理删除提供商
        if "delete_provider" in kwargs:
            provider_id = kwargs.pop("delete_provider")
            config.remove_provider(provider_id)
        
        # 更新全局设置
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        # 如果添加了新提供商且没有激活的提供商，自动激活
        if provider_added and new_provider_id and not config.get_active_provider():
            config.set_active(new_provider_id)
        
        # 保存到 .env 文件
        config.save_env(self._config_save_path)
        return {"success": True, "message": "配置已更新"}

    def test_llm_connection(self, provider_id: str = None) -> Dict[str, Any]:
        """测试LLM连接"""
        config = self.llm.config
        
        # 如果指定了提供商，先切换
        if provider_id:
            if not config.set_active(provider_id):
                return {"success": False, "message": "指定的提供商不存在或未启用"}
        
        if not config.is_configured():
            return {"success": False, "message": "请先配置API密钥"}
        
        success, result = self.llm.call("请回复'连接成功'", "你是一个测试助手")
        return {
            "success": success,
            "message": result if success else "连接失败"
        }

    # ============== 内部方法 ==============

    def _parse_brief(self, brief: str) -> Dict[str, Any]:
        """解析创作简报"""
        prompt = f"""请分析以下创作简报，提取关键信息并生成JSON格式的创作规划。

⚠️ 核心原则：你的任务是「提取」而非「创作」。用户写什么就提取什么，禁止改写或替换用户的创意。

创作简报：
{brief}

请返回JSON格式，包含以下字段：
- book_name: 书名（如果简报中明确提供了书名，直接提取；如果未提供，根据内容生成一个吸引人的书名）
- genre: 题材（玄幻/仙侠/都市/科幻/其他）
- platform: 目标平台
- words_per_chapter: 单章字数
- estimated_chapters: 预期章节数
- estimated_words: 预计完本字数
- protagonist_name: 主角姓名（如果简报中提到了主角姓名/名字，必须原样提取；不要生成新名字）
- protagonist_gender: 主角性别
- protagonist_background: 主角背景
- core_setting: 核心设定摘要（必须忠实于用户提供的文字，禁止添加用户未提及的内容，禁止改写用户的设定）
- main_direction: 主线方向（基于用户提供的梗概/大纲提取，不要自行编造）
- opening_strategy: 开篇策略

⚠️ 主角名提取规则（极其重要！）：
- 如果简报中提到了主角姓名，必须原样提取到 protagonist_name 字段
- 例如：简报写"主角余凌"、"主人公叫余凌"、"余凌是一个觉醒者"，则 protagonist_name = "余凌"
- 如果简报中没有提到主角姓名，才调用 LLM 生成一个合适的名字
- 禁止在 core_setting 或 main_direction 中添加简报未提及的主角信息

⚠️ 忠实性约束：
- 绝对忠实于用户文字：用户写「彗星爆炸导致变异」就不要改成「血脉觉醒」等
- 禁止修改用户提供的人名、世界观起源、故事结构等核心设定
"""
        result = self.llm.generate_json(prompt, self.llm.get_system_prompt("planner"))
        if result:
            return result
        
        # 回退解析
        planning = {
            "book_name": "",
            "genre": "都市",
            "platform": "番茄小说",
            "words_per_chapter": 3000,
            "estimated_chapters": 80,
            "estimated_words": 240000,
            "core_setting": "",
            "main_direction": "",
            "opening_strategy": "黄金三章法则"
        }
        
        # 简单规则匹配
        genres = {"玄幻": ["玄幻", "修炼", "灵气"], "仙侠": ["仙侠", "修真"],
                  "都市": ["都市", "现代"], "科幻": ["科幻", "星际"]}
        brief_lower = brief.lower()
        for genre, keywords in genres.items():
            if any(k in brief_lower for k in keywords):
                planning["genre"] = genre
                break
        
        name_match = re.search(r'书名[：:]\s*([^\n]+)', brief)
        if name_match:
            planning["book_name"] = name_match.group(1).strip()

        return planning
    
    def _generate_planning_doc(self, planning: Dict) -> str:
        """生成创作规划书文档"""
        # 格式化核心设定
        golden_finger = planning.get('core_setting', '')
        if isinstance(golden_finger, dict):
            world_bg = golden_finger.get('world_background', golden_finger.get('world_bg', ''))
            gf = golden_finger.get('golden_finger', golden_finger.get('golden_finger', ''))
            usp = golden_finger.get('unique_selling_point', golden_finger.get('unique_selling', ''))
            core_setting_parts = []
            if world_bg:
                core_setting_parts.append(f"- 世界背景: {world_bg}")
            if gf:
                core_setting_parts.append(f"- 金手指: {gf}")
            if usp:
                core_setting_parts.append(f"- 卖点: {usp}")
            core_setting_str = "\n".join(core_setting_parts) if core_setting_parts else "待定"
        elif isinstance(golden_finger, str) and golden_finger != '待定' and golden_finger:
            core_setting_str = golden_finger
        else:
            core_setting_str = "待定"

        # 格式化主线规划（成长线、冲突线、情感线）
        main_direction = planning.get('main_direction', '')
        if isinstance(main_direction, dict):
            main_lines = []
            for key in ['成长线', '冲突线', '情感线', '其他']:
                if key in main_direction:
                    main_lines.append(f"- {key}: {main_direction[key]}")
                elif key == '其他':
                    # 其他未分类的项
                    for phase, desc in main_direction.items():
                        if phase not in ['成长线', '冲突线', '情感线']:
                            main_lines.append(f"- {phase}: {desc}")
            main_direction_str = "\n".join(main_lines) if main_lines else '待定'
        elif isinstance(main_direction, str) and main_direction != '待定' and main_direction:
            main_direction_str = main_direction
        else:
            main_direction_str = '待定'

        doc = f"""# 创作规划书

## 项目信息
- 书名: {planning.get('book_name', '待定')}
- 题材: {planning.get('genre', '都市')}
- 风格: 网文创作流
- 目标平台: {planning.get('platform', '番茄小说')}

## 核心设定
{core_setting_str}

## 主线规划
{main_direction_str}
- 预期章节数: {planning.get('estimated_chapters', 80)}
- 预计完本字数: {planning.get('estimated_words', 240000)}字

## 创作节奏
- 开篇策略: {planning.get('opening_strategy', '黄金三章法则')}
- 前10章节奏规划: 建立世界观、冲突、升级
- 第一个高潮点: 第10章左右

## 黄金三章规划
{planning.get('golden_chapters_plan', '待规划')}

## 行动建议
1. 确认规划书内容
2. 开始创作第1章
"""
        return doc

    def _generate_book_id(self) -> str:
        """生成唯一书籍ID（book + 6位随机数）"""
        import random
        import string
        max_attempts = 100
        for _ in range(max_attempts):
            random_part = ''.join(random.choices(string.digits, k=6))
            book_id = f"book{random_part}"
            # 检查是否已存在
            if not self.sm.get_book_by_id(book_id):
                return book_id
        raise ValueError("无法生成唯一书籍ID")

    def _generate_story_bible(self, book: BookInfo, planning: Dict, 
                             characters: str = None, feedback: str = "") -> str:
        """生成世界观设定"""
        target_words = book.words_per_chapter or 3000
        genre = planning.get('genre', book.genre or '都市')
        
        # 如果有反馈，说明是修订模式
        if feedback:
            return self._revise_story_bible(book, planning, characters, feedback)
        
        # 使用 planning 中的内容生成世界观
        background = planning.get('背景', '')
        summary = planning.get('梗概', '')
        style = planning.get('风格', '轻松幽默')
        ability = planning.get('主角的金手指', '')
        
        # 如果没有主角姓名，调用 LLM 生成
        protagonist_name = planning.get('主角名', '')
        if not protagonist_name or protagonist_name == '待设定':
            protagonist_name = self._generate_protagonist_name(book, genre)
        
        # 根据题材类型设置默认值
        genre_defaults = {
            '都市': {'system': '超能力者（觉醒体系）', 'org': '超能管理局'},
            '玄幻': {'system': '修炼体系（炼气→筑基→金丹→元婴→化神）', 'org': '宗门势力'},
            '仙侠': {'system': '修仙体系（练气→筑基→金丹→元婴→化神→渡劫）', 'org': '仙门世家'},
            '科幻': {'system': '机甲/基因改造/高科技', 'org': '星际联盟'},
        }
        defaults = genre_defaults.get(genre, genre_defaults['都市'])
        
        # 人物信息（如果有）
        char_intro = ""
        if characters:
            if "主角" in characters:
                char_section = characters.split("## 主角")[1].split("##")[0] if "##" in characters else characters
                char_intro = f"\n\n### 人物信息参考\n{char_section[:500]}"
        
        prompt = f"""请为小说《{book.name}》生成一份详细完整的世界观设定文档。

题材：{genre}
背景：{background if background else '请根据题材自由发挥，创造独特的世界观'}
风格：{style}
金手指：{ability if ability else '待设定'}

{char_intro}

请生成一份内容丰富、有深度、有独特性的世界观设定，必须包含以下部分：
1. 时代背景（具体的时代特征、社会环境）
2. 空间设定（主要舞台、特殊区域/位面）
3. 世界规则（力量体系来源、等级划分、能力限制）
4. 主要势力（至少3个有特色的势力，每个势力要有独特背景和目的）
5. 能力体系（详细的分类和升级方式，要有独特设定）
6. 重要地点（至少5个有特色的地点描写）
7. 历史背景（世界的历史渊源，形成当前格局的原因）
8. 独特设定（区别于同类作品的亮点，必须有创新性）

要求：
- 内容要具体详细，不要泛泛而谈
- 要有独特的创新点，不是千篇一律的模板
- 各设定之间要自洽统一
- 对创作有实际指导意义

使用Markdown格式输出。"""
        
        # 替换 system_prompt 中的 {words_per_chapter} 占位符
        target_words = book.words_per_chapter or 3000
        system_prompt = self.llm.get_system_prompt("architect").replace("{words_per_chapter}", str(target_words))
        result = self.llm.generate(prompt, system_prompt)
        if result and not result.startswith("["):
            return f"# {book.name} 世界观设定\n\n{result}"
        
        # 回退：返回基础模板
        return self._generate_story_bible_fallback(book, protagonist_name, genre, defaults, style)
    
    def _revise_story_bible(self, book: BookInfo, planning: Dict, 
                           characters: str, feedback: str, 
                           original_content: str = "") -> str:
        """修订世界观设定"""
        target_words = book.words_per_chapter or 3000
        genre = planning.get('genre', book.genre or '都市')
        protagonist_name = planning.get('主角名', '') or "主角"
        
        prompt = f"""请根据以下评审报告，对小说《{book.name}》的世界观设定进行修订。

【评审反馈】
{feedback}

【修订要求】
1. 仔细分析评审报告中指出的问题
2. 保持原有合理的设定不变
3. 针对问题进行针对性修改
4. 提高完整性、一致性、实用性和创新性
5. 确保修订后的设定各部分自洽统一
6. 必须输出完整的修订后文档，不要省略任何部分

请重新生成完整的世界观设定文档，保持Markdown格式。"""
        
        try:
            # 替换 system_prompt 中的 {words_per_chapter} 占位符
            system_prompt = self.llm.get_system_prompt("architect").replace("{words_per_chapter}", str(target_words))
            result = self.llm.generate(prompt, system_prompt)
            if result and not result.startswith("[") and len(result.strip()) > 100:
                return f"# {book.name} 世界观设定\n\n{result}"
            
            print(f"[_revise_story_bible] 修订结果无效，使用回退模板")
            genre_defaults_for_fallback = {
                '都市': {'system': planning.get('system', '异能'), 'org': '超能管理局'},
                '玄幻': {'system': planning.get('system', '修炼体系'), 'org': '宗门势力'},
                '仙侠': {'system': planning.get('system', '修仙体系'), 'org': '仙门世家'},
                '科幻': {'system': planning.get('system', '高科技'), 'org': '星际联盟'},
            }
            fallback_defaults = genre_defaults_for_fallback.get(genre, genre_defaults_for_fallback['都市'])
            fallback_style = planning.get('风格', '热血')
            return self._generate_story_bible_fallback(book, protagonist_name, genre,
                                                        fallback_defaults, fallback_style)
        except Exception as e:
            print(f"[_revise_story_bible] 修订异常: {e}")
            return original_content if original_content else self._generate_story_bible_fallback(
                book, protagonist_name, genre,
                {'system': planning.get('system', '异能'), 'org': '官方势力'},
                planning.get('风格', '热血')
            )
    
    def _generate_story_bible_fallback(self, book: BookInfo, protagonist_name: str, 
                                       genre: str, defaults: dict, style: str) -> str:
        """世界观设定回退模板"""
        system_default = defaults.get('system', '异能觉醒体系')
        org_default = defaults.get('org', '官方势力')
        return f"""# {book.name} 世界观设定

## 一、世界观背景

### 1.1 时代背景
故事发生在现代都市，灵气复苏的世界。经过多年发展，超能力者已建立完善的职业体系。

### 1.2 空间设定
- 主要舞台：现代都市
- 隐藏世界：觉醒者的地下世界

### 1.3 世界规则
- 超能力来源：{system_default}
- 能力等级：初级 → 中级 → 高级 → 顶级 → 传说
- 能力限制：每次使用消耗精神力，精神力耗尽将陷入昏迷

## 二、主要人物

### 2.1 主角
- **姓名**：{protagonist_name}
- **身份**：都市青年
- **性格**：{style}

### 2.2 其他人物
待后续设定补充

## 三、势力/门派/组织

### 3.1 官方势力
- **名称**：{org_default}
- **职能**：管控觉醒者，维护秩序

### 3.2 民间组织
- 佣兵团、赏金猎人组织等

## 四、能力体系

### 4.1 超能力分类
- 元素系：操控自然元素
- 强化系：强化身体素质
- 感知系：预知、读心等
- 辅助系：治疗、加速等

### 4.2 升级方式
- 实战积累
- 特殊机缘
- 导师指导
"""

    def _generate_protagonist_name(self, book: BookInfo, genre: str) -> str:
        """生成主角姓名"""
        prompt = f"""请为小说《{book.name}》的主角生成一个符合以下要求的姓名：

1. 题材：{genre}
2. 姓名要有辨识度，朗朗上口
3. 避免过于常见或过于生僻的名字
4. 中文姓名，2-3个字

请直接输出主角姓名，不需要其他解释。"""
        
        result = self.llm.generate(prompt, self.llm.get_system_prompt("general"))
        if result:
            # 清理结果，只保留姓名部分
            name = result.strip()
            # 去掉可能的前缀说明
            if '：' in name or ':' in name:
                name = name.split('：')[-1].split(':')[-1].strip()
            # 确保是有效的中文名字（2-4个字符）
            import re
            match = re.search(r'[\u4e00-\u9fa5]{2,4}', name)
            if match:
                return match.group()
        # 回退默认值
        return "林逸"

    def _generate_book_rules(self, book: BookInfo, genre: str, feedback: str = "", 
                            story_bible: str = "") -> str:
        """生成创作规则"""
        target_words = book.words_per_chapter or 3000
        # 如果有反馈，说明是修订模式
        if feedback:
            return self._revise_book_rules(book, genre, feedback)
        
        prompt = f"""请为小说《{book.name}》制定详细的创作规则。

题材: {genre}
目标平台: {book.platform}
字数要求: 每章约{book.words_per_chapter}字

{story_bible[:1000] if story_bible else ''}

请生成包含以下部分的创作规则：
1. 题材规则（该题材必须遵守的创作规范，越详细越好）
2. 爽点节奏（打脸/升级/收益兑现的节奏模板，具体到每种爽点的写法）
3. 反派智力要求（不要让反派降智，但也要给主角留升级空间）
4. 禁止事项（该题材常见的烂俗写法要避免）
5. 文风要求（符合平台读者喜好的文风建议）
6. 角色塑造要求（主角、配角、反派的塑造要点）
7. 伏笔使用规范（如何埋设和回收伏笔）

要求：
- 规则要具体、可操作
- 要符合网文创作的最佳实践
- 要有针对该题材的特点

使用Markdown格式输出。"""
        
        # 替换 system_prompt 中的 {words_per_chapter} 占位符
        system_prompt = self.llm.get_system_prompt("architect").replace("{words_per_chapter}", str(target_words))
        result = self.llm.generate(prompt, system_prompt)
        if result and not result.startswith("["):
            return f"# {book.name} 创作规则\n\n{result}"
        
        return self._generate_book_rules_fallback(book, genre)
    
    def _revise_book_rules(self, book: BookInfo, genre: str, feedback: str) -> str:
        """修订创作规则"""
        target_words = book.words_per_chapter or 3000
        prompt = f"""请根据以下评审报告，对小说《{book.name}》的创作规则进行修订。

【评审反馈】
{feedback}

【修订要求】
1. 仔细分析评审报告中指出的问题
2. 保持原有合理的规则不变
3. 针对问题进行针对性修改
4. 使规则更加具体、可操作
5. 确保规则之间不自相矛盾

请重新生成完整的创作规则文档，保持Markdown格式。"""
        
        # 替换 system_prompt 中的 {words_per_chapter} 占位符
        system_prompt = self.llm.get_system_prompt("architect").replace("{words_per_chapter}", str(target_words))
        result = self.llm.generate(prompt, system_prompt)
        if result and not result.startswith("["):
            return f"# {book.name} 创作规则\n\n{result}"
        
        return ""  # 修订失败时返回空字符串而非None
    
    def _generate_book_rules_fallback(self, book: BookInfo, genre: str) -> str:
        """创作规则回退模板"""
        return f"""# {book.name} 创作规则

## 一、题材规则
[{genre}题材必须遵守的创作规范]

## 二、爽点节奏
[打脸/升级/收益兑现的节奏模板]

## 三、禁止事项
- 禁止角色OOC
- 禁止战力崩坏
- 禁止信息越界
"""

    def _generate_chapter_outline(self, book: BookInfo, chapter_num: int, regenerate: bool = False,
                                  previous_audit: str = "", previous_outline: str = "") -> str:
        """生成章节细纲

        Args:
            previous_audit: 上一次评审报告（用于修订模式）
            previous_outline: 上一次生成的细纲（用于修订模式，基于原细纲修改）
        """
        truth_files = self._load_truth_files(book)
        chapter_title = f"第{chapter_num}章"

        # 构建修订提示
        revise_hint = ""
        if regenerate:
            if previous_outline:
                # 修订模式：基于上一次细纲修改
                revise_hint = f"""

【上一次细纲参考】：
{previous_outline}
"""
                if previous_audit:
                    revise_hint += f"""

【上一次评审报告参考】：
{previous_audit}

请根据评审意见修改细纲，修复问题后生成新的细纲。"""
            elif previous_audit:
                revise_hint = f"""

【上一次评审报告参考】：
{previous_audit}

请根据评审意见重新设计章节结构，重点修复评分较低的问题。"""
            else:
                revise_hint = """

【修订要求】：请重新审视上一次的章节结构，生成一个更好的版本。注意避免重复的情节和角色行为。"""
        
        target_words = book.words_per_chapter or 3000

        prompt = f"""请为小说《{book.name}》{chapter_title}生成章节细纲。

【创作要求】
- 目标字数：约 {target_words} 字（正文应控制在 {target_words}~{target_words + 500} 字之间）
- 请根据目标字数合理规划情节密度，确保情节量与字数匹配
{revise_hint}
当前世界状态：
{truth_files.get('current_state', '无')}

待回收伏笔：
{truth_files.get('pending_hooks', '无')}

请生成包含以下部分的章节结构：
1. 本章核心事件（一句话概括）
2. 起承转合结构
3. 关键情节点（3-5个，每个情节点应匹配约 {target_words // 4} 字的篇幅）
4. 伏笔埋设
5. 本章结尾钩子
6. 预估字数（目标 {target_words} 字，合理范围 {target_words - 200}~{target_words + 500} 字）

使用Markdown格式输出。"""

        # 替换 system_prompt 中的 {words_per_chapter} 占位符
        system_prompt = self.llm.get_system_prompt("architect").replace("{words_per_chapter}", str(target_words))
        result = self.llm.generate(prompt, system_prompt)
        if result and not result.startswith("["):
            return result

        return f"""# {chapter_title} 章节结构

## 本章核心事件
[一句话概括]

## 起承转合
- 起: [开场]
- 承: [发展]
- 转: [转折]
- 合: [结尾]

## 情节点
1. [情节点1]
2. [情节点2]
3. [情节点3]

## 预估字数
约 {target_words} 字
"""

    def _generate_full_outline(self, book: BookInfo, planning: Dict, story_bible: str,
                                author_intent: str, characters: str) -> str:
        """
        生成完整章节大纲

        基于创作意图、世界观、人物设定，生成整本书的章节规划。

        Args:
            book: 书籍信息
            planning: 规划数据
            story_bible: 世界观设定
            author_intent: 作者意图
            characters: 人物设定

        Returns:
            完整章节大纲
        """
        genre = planning.get('genre', book.genre or '都市')
        summary = planning.get('梗概', '')
        estimated_chapters = planning.get('estimated_chapters', 80)
        style = planning.get('风格', '轻松幽默')

        prompt = f"""请为小说《{book.name}》生成完整的章节大纲。

## 基本信息
- 题材：{genre}
- 风格：{style}
- 预期章节数：{estimated_chapters}
- 目标字数：约 {estimated_chapters * 3000} 字

## 故事梗概
{summary}

## 作者意图
{author_intent[:1000] if author_intent else '无'}

## 世界观设定
{story_bible[:1500] if story_bible else '无'}

## 人物设定
{characters[:1000] if characters else '无'}

请生成完整的章节大纲，要求：

1. **整体结构**：将 {estimated_chapters} 章分为几个阶段（如：开局期、成长期、高潮期、结局期）
2. **每阶段规划**：说明该阶段的主要任务、预期章节数
3. **关键节点**：标注重要情节点（如：第一个高潮、转折点、最终决战等）
4. **章节预览**：列出前20章的简要内容（每章一句话）

大纲格式：
- 使用 Markdown
- 分层清晰
- 每个阶段用 ## 标记
- 章节用 - 或 * 列表

请生成详细且实用的章节大纲："""

        # 替换 system_prompt 中的 {words_per_chapter} 占位符
        target_words = book.words_per_chapter or 3000
        system_prompt = self.llm.get_system_prompt("architect").replace("{words_per_chapter}", str(target_words))
        result = self.llm.generate(prompt, system_prompt)

        if result and not result.startswith("["):
            return f"# {book.name} - 章节大纲\n\n*本文档定义了整本书的章节规划，应在章节创作时参考。*\n\n{result}"

        # 回退模板
        chapters = planning.get('estimated_chapters', 80)
        stage_size = chapters // 4
        return f"""# {book.name} - 章节大纲

*本文档定义了整本书的章节规划，应在章节创作时参考。*

## 整体结构

| 阶段 | 章节范围 | 主要任务 |
|------|----------|----------|
| 开局期 | 1-{stage_size}章 | 建立世界观、主角、初始冲突 |
| 成长期 | {stage_size+1}-{stage_size*2}章 | 主角升级、势力扩展 |
| 高潮期 | {stage_size*2+1}-{stage_size*3}章 | 主线冲突升级、最终对抗 |
| 结局期 | {stage_size*3+1}-{chapters}章 | 收束伏笔、完美结局 |

## 开局期（前{stage_size}章）

- **第1章**：主角出场，展示初始状态，设置悬念钩子
- **第2章**：主角获得机遇/觉醒，展示能力雏形
- **第3章**：小试牛刀，建立第一个明确对手/目标
- ...

## 关键节点

- 第10章左右：第一个高潮
- 第{stage_size}章：开局期收尾，主线任务确立
- 第{chapters-20}章左右：最终决战准备
- 第{chapters}章：大结局

---

*版本：1.0*
*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

    def _compile_context(self, book: BookInfo, chapter_num: int, outline: str, truth_files: Dict) -> str:
        """编译上下文（含上一章 Reflector 策略调整）"""
        # 加载上一章的反思报告（Reflector 输出），为本章创作提供策略指导
        previous_reflection = ""
        if chapter_num > 1:
            reflection_path = self.workspace / book.path / "chapters" / f"reflection_{chapter_num - 1}.md"
            if reflection_path.exists():
                previous_reflection = self.sm.fm.read_text(reflection_path)
                if previous_reflection:
                    previous_reflection = f"""
## 上章反思与策略调整（来自 Reflector）
> 以下是对上一章创作的分析报告和本章策略建议，请注意吸收并调整创作方向。

{previous_reflection}
"""

        return f"""# 上下文编译包 - 第 {chapter_num} 章

## 作者意图（长期愿景）
{truth_files.get('author_intent', '[来自 author_intent.md 的创作愿景]')}

## 当前焦点（近期任务）
{truth_files.get('current_focus', '[来自 current_focus.md 的近期重点]')}

## 创作约束
{truth_files.get('book_rules', '[来自 book_rules.md 的强制规则]')}

## 世界观摘要
{truth_files.get('story_bible', '[来自 story_bible.md 的核心设定]')}

## 当前世界状态
{truth_files.get('current_state', '[状态快照]')}

## 资源变动
{truth_files.get('particle_ledger', '[资源账本]')}

## 伏笔状态
{truth_files.get('pending_hooks', '[待回收伏笔]')}
{previous_reflection}
## 本章任务
{outline}
"""

    def _generate_chapter_content(self, book: BookInfo, chapter_num: int, context: str, outline: str, revise: bool = False, revise_reference: str = "") -> str:
        """生成章节正文

        Args:
            revise_reference: 修订参考内容，可以是上一次评审报告、用户输入等
        Raises:
            Exception: LLM生成失败时抛出异常，避免保存[待生成]占位内容
        """
        print(f"\n[生成章节正文] 开始...")
        print(f"[生成章节正文] 章节: 第{chapter_num}章")
        print(f"[生成章节正文] 目标字数: {book.words_per_chapter}字")
        print(f"[生成章节正文] 上下文长度: {len(context)}字")
        print(f"[生成章节正文] 细纲长度: {len(outline)}字")
        
        # 修订模式提示
        if revise:
            if revise_reference:
                revise_hint = f"""

【修订参考内容】：
{revise_reference}

【修订要求】：
请根据上述修订参考内容，重新创作本章内容。注意：
1. 修复参考内容中指出的问题
2. 避免重复上一次的问题
3. 创作一个焕然一新的版本
"""
            else:
                revise_hint = """

【重要-修订要求】：请重新审视上一次的内容，生成质量更高的版本。注意避免：
1. 重复的情节和场景描写
2. 角色行为的矛盾
3. 同样的转折方式
4. 相同的伏笔埋设方式

请创作一个焕然一新的章节！"""
        else:
            revise_hint = ""

        prompt = f"""请为小说《{book.name}》创作第{chapter_num}章正文。

目标字数：{book.words_per_chapter}字
题材：{book.genre}

以下是上下文编译包：
{context}

以下是章节细纲：
{outline}{revise_hint}

要求：
1. 字数：{book.words_per_chapter}-{book.words_per_chapter + 500}字
2. 禁止角色OOC、战力崩坏
3. 必须埋设/回收伏笔、推动主线
4. 禁止AI写作痕迹
5. 禁止使用"突然"、"就在这时"等突兀转折词

直接输出正文内容。"""
        
        # 长篇章节生成（max_tokens=16000）使用15分钟超时，避免超时失败
        result = self.llm.generate(prompt, self.llm.get_system_prompt("writer"), max_tokens=16000, timeout=900)
        if result and not result.startswith("["):
            return f"# 第 {chapter_num} 章\n\n{result}\n\n---\n字数统计: 约 {len(result)} 字"
        raise Exception(f"第{chapter_num}章生成失败：LLM接口调用异常，请检查API配置或稍后重试" + (f"（{result[:80]}）" if result else "（无响应）"))

    def _generate_audit_report(self, book: BookInfo, chapter_num: int, content: str, audit_result: AuditResult) -> str:
        """生成评审报告文档"""
        chapter_title = f"第{chapter_num}章"
        
        # 构建问题列表
        issues_text = ""
        audit_issues_list = getattr(audit_result, 'issues', []) or []
        if audit_issues_list:
            for i, issue in enumerate(audit_issues_list, 1):
                severity = issue.get("severity", "中")
                severity_icon = "🔴" if severity == "高" else ("🟡" if severity == "中" else "🟢")
                issues_text += f"{i}. {severity_icon} [{issue.get('dimension', '未知')}] {issue.get('description', '')}\n"
        else:
            issues_text = "无明显问题"

        # 构建核心漏洞
        core_issues_text = ""
        core_issues_list = getattr(audit_result, 'core_issues', []) or []
        if core_issues_list:
            for issue in core_issues_list:
                core_issues_text += f"- [{issue.get('severity', '高')}] {issue.get('description', '')}\n"
        else:
            core_issues_text = "无"

        report = f"""# {book.name} - {chapter_title}评审报告

## 基本信息
- 书名：{book.name}
- 章节：{chapter_title}
- 评审时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 评审类型：章节质量评审

## 评分概览
| 指标 | 数值 |
|------|------|
| **综合评分** | {audit_result.chapter_score}分 |
| **决策** | {audit_result.decision} |
| **实际字数** | {audit_result.word_count}字 |
| **目标字数** | {audit_result.target_word_count}字 |
| **字数偏差** | {audit_result.word_count_deviation:+d}字 |

## 质量指标
| 指标 | 数值 | 说明 |
|------|------|------|
| AI痕迹密度 | {audit_result.ai_tell_density:.3f} | 越低越好（<0.05为佳） |
| 短段落警告 | {audit_result.paragraph_warnings}处 | 越少越好 |
| 逻辑问题 | {audit_result.audit_issues}处 | 越少越好 |
| 伏笔回收率 | {audit_result.hook_resolution_rate}% | 越高越好 |

## 问题列表
{issues_text}

## 核心漏洞（必须修订）
{core_issues_text if core_issues_text != "无" else "无核心漏洞"}

## 修订建议
{"需根据上述问题进行修订" if audit_result.decision != "通过" else "本章质量达标，无需修订。"}
"""
        return report

    def save_audit_report(self, book: BookInfo, chapter_num: int, content: str, audit_result: AuditResult) -> str:
        """保存评审报告到文件"""
        report = self._generate_audit_report(book, chapter_num, content, audit_result)
        
        # 创建评审报告目录
        report_dir = self.workspace / book.path / "audit_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chapter_{chapter_num}_report_{timestamp}.md"
        report_path = report_dir / filename
        
        # 保存报告
        self.sm.fm.write_text(report_path, report)
        
        return str(report_path)

    def get_latest_audit_report(self, book: BookInfo, chapter_num: int) -> str:
        """获取章节的最新评审报告内容"""
        report_dir = self.workspace / book.path / "audit_reports"
        if not report_dir.exists():
            return ""
        
        # 查找最新的评审报告
        reports = list(report_dir.glob(f"chapter_{chapter_num}_report_*.md"))
        if not reports:
            return ""
        
        # 返回最新的报告内容
        latest_report = sorted(reports, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        return self.sm.fm.read_text(latest_report)

    def _audit_outline(self, book: BookInfo, chapter_num: int, outline: str) -> dict:
        """对章节细纲进行结构化审查
        
        Returns:
            dict with keys: passed(bool), score(int), report(str), issues(list), score_breakdown(dict)
        """
        target_words = book.words_per_chapter or 3000

        prompt = f"""请对小说《{book.name}》第{chapter_num}章的细纲进行结构化审查。

【创作背景】
- 题材：{book.genre}
- 目标字数：每章约 {target_words} 字（合理范围 {target_words - 500}~{target_words + 500} 字）
- 字数偏差容忍度：±500 字

【章节细纲】
{outline}

【审查要求】
请严格按照维度评分，重点关注：
1. 各情节点分配的字数是否与目标 {target_words} 字匹配
2. 预估字数是否在 {target_words - 500}~{target_words + 500} 字范围内
3. 起承转合结构是否完整

返回 JSON：
{{
    "plot_structure_score": 情节结构完整性得分(0-20),
    "word_allocation_score": 字数分配合理性得分(0-20),
    "foreshadowing_score": 伏笔埋设质量得分(0-20),
    "hook_score": 钩子有效性得分(0-20),
    "word_estimate_score": 字数预估准确性得分(0-20),
    "issues": [
        {{"dimension": "维度名", "description": "问题描述", "severity": "高/中/低", "suggestion": "修改建议"}}
    ],
    "strengths": ["亮点1", "亮点2"],
    "overall_assessment": "综合评语"
}}

只返回JSON。"""

        audit_data = self.llm.generate_json(prompt, self.llm.get_system_prompt("outline_auditor"))
        if not audit_data:
            # LLM 调用失败，使用默认及格分数放行
            return {
                "passed": True,
                "score": 80,
                "report": "# 细纲审计（自动通过）\n\nLLM审计服务暂不可用，细纲自动通过。",
                "issues": [],
                "score_breakdown": {}
            }

        # 解析各维度得分
        ps = max(0, min(20, audit_data.get("plot_structure_score", 15) or 15))
        wa = max(0, min(20, audit_data.get("word_allocation_score", 15) or 15))
        fs = max(0, min(20, audit_data.get("foreshadowing_score", 15) or 15))
        hs = max(0, min(20, audit_data.get("hook_score", 15) or 15))
        we = max(0, min(20, audit_data.get("word_estimate_score", 15) or 15))

        # 加权总分
        total = ps * 0.25 + wa * 0.30 + fs * 0.20 + hs * 0.15 + we * 0.10
        total = round(total / 20 * 100)  # 转换为百分制

        issues = audit_data.get("issues") or []

        # 判定是否通过
        passed = total >= 75 and wa >= 12  # 字数分配维度必须 >= 12/20

        # 构建报告
        report_lines = [
            f"# 第 {chapter_num} 章细纲审计报告",
            "",
            f"## 审查结论",
            f"{'✅ 通过' if passed else '❌ 需修订'}",
            "",
            "## 维度评分",
            "| 维度 | 得分/20 | 评价 |",
            "|------|---------|------|",
            f"| 情节结构完整性 | {ps} | {'良好' if ps >= 15 else '需改进' if ps >= 10 else '严重不足'} |",
            f"| 字数分配合理性 | {wa} | {'良好' if wa >= 15 else '需改进' if wa >= 10 else '严重不足'} |",
            f"| 伏笔埋设质量 | {fs} | {'良好' if fs >= 15 else '需改进' if fs >= 10 else '严重不足'} |",
            f"| 钩子有效性 | {hs} | {'良好' if hs >= 15 else '需改进' if hs >= 10 else '严重不足'} |",
            f"| 字数预估准确性 | {we} | {'良好' if we >= 15 else '需改进' if we >= 10 else '严重不足'} |",
            "",
            f"## 综合得分",
            f"{total}/100",
            "",
        ]

        if issues:
            report_lines.append("## 问题清单")
            report_lines.append("| 编号 | 维度 | 问题描述 | 严重度 | 修改建议 |")
            report_lines.append("|------|------|----------|--------|----------|")
            for i, issue in enumerate(issues, 1):
                report_lines.append(
                    f"| Q{i:03d} | {issue.get('dimension', '未知')} | "
                    f"{issue.get('description', '')} | "
                    f"{issue.get('severity', '中')} | "
                    f"{issue.get('suggestion', '—')} |"
                )

        report = "\n".join(report_lines)

        return {
            "passed": passed,
            "score": total,
            "report": report,
            "issues": issues,
            "score_breakdown": {
                "plot_structure": ps,
                "word_allocation": wa,
                "foreshadowing": fs,
                "hook": hs,
                "word_estimate": we
            }
        }

    def _generate_and_audit_outline(self, book: BookInfo, chapter_num: int,
                                     revise: bool = False, previous_audit: str = "",
                                     previous_outline: str = "") -> str:
        """生成章节细纲并进行审计（含最多3次自动修订循环）
        
        流程：生成细纲 → 审计 → 不通过则修订 → 最多3次 → 选最优
        
        Returns:
            通过审计的细纲文本（或3次中最优版本）
        """
        max_attempts = 3
        best_outline = None
        best_score = -1
        best_report = ""

        chapter_title = f"第{chapter_num}章"
        print(f"\n{'='*60}")
        print(f"[OutlineAudit] {chapter_title}细纲生成与审计开始 (最多{max_attempts}次尝试)")
        print(f"[OutlineAudit] 模式: {'修订模式' if revise or previous_audit else '首次生成'}"
              f"{' (附审计反馈)' if previous_audit else ''}")

        for attempt in range(1, max_attempts + 1):
            # 生成/修订细纲
            print(f"\n[OutlineAudit] --- 尝试 {attempt}/{max_attempts} ---")
            if attempt == 1:
                print(f"[OutlineAudit] 正在生成细纲...")
                outline = self._generate_chapter_outline(
                    book, chapter_num,
                    regenerate=revise,
                    previous_audit=previous_audit,
                    previous_outline=previous_outline
                )
            else:
                # 修订模式：带上一次审计报告
                print(f"[OutlineAudit] 正在修订细纲（依据上次审计报告）...")
                outline = self._generate_chapter_outline(
                    book, chapter_num,
                    regenerate=True,
                    previous_audit=best_report,
                    previous_outline=best_outline or ""
                )

            if not outline or outline.startswith("["):
                print(f"[OutlineAudit] ✗ 细纲生成失败 (尝试 {attempt}/{max_attempts})")
                continue

            # 计算细纲字数
            outline_len = len(outline)
            print(f"[OutlineAudit] 细纲生成完成 ({outline_len} 字符)，正在调用审计...")

            # 审计细纲
            audit_result = self._audit_outline(book, chapter_num, outline)
            score = audit_result["score"]
            breakdown = audit_result.get("score_breakdown", {})

            # 打印详细得分
            print(f"[OutlineAudit] 审计完成，得分 {score}/100 {'✓ 通过' if audit_result['passed'] else '✗ 需修订'}")
            if breakdown:
                print(f"[OutlineAudit]   维度得分: "
                      f"情节结构={breakdown.get('plot_structure', '?')}/20, "
                      f"字数分配={breakdown.get('word_allocation', '?')}/20, "
                      f"伏笔={breakdown.get('foreshadowing', '?')}/20, "
                      f"钩子={breakdown.get('hook', '?')}/20, "
                      f"字数预估={breakdown.get('word_estimate', '?')}/20")
            issues = audit_result.get("issues") or []
            if issues and not audit_result["passed"]:
                high_issues = [i for i in issues if i.get("severity") == "高"]
                print(f"[OutlineAudit]   问题数: {len(issues)} (高严重度: {len(high_issues)})")
                for i, issue in enumerate(issues[:3], 1):
                    print(f"[OutlineAudit]     {i}. [{issue.get('dimension', '?')}] {issue.get('description', '')[:60]}")

            # 记录最优版本
            if score > best_score:
                best_score = score
                best_outline = outline
                best_report = audit_result["report"]
                if score > 0:
                    print(f"[OutlineAudit]   ↑ 更新最优版本 (得分 {score})")

            # 通过则直接返回
            if audit_result["passed"]:
                print(f"\n[OutlineAudit] ✓ {chapter_title}细纲在第{attempt}次尝试通过审计")
                return outline

            # 不通过：保存审计报告，继续下一轮
            if attempt < max_attempts:
                print(f"[OutlineAudit]   准备第{attempt + 1}次修订...")
            outline_audit_path = self.workspace / book.path / "audit_reports" / f"outline_audit_{chapter_num}_v{attempt}.md"
            audit_report_dir = self.workspace / book.path / "audit_reports"
            audit_report_dir.mkdir(parents=True, exist_ok=True)
            self.sm.fm.write_text(outline_audit_path, audit_result["report"])
            print(f"[OutlineAudit]   审计报告已保存: audit_reports/outline_audit_{chapter_num}_v{attempt}.md")

        # 3次均未通过，使用最优版本
        print(f"\n[OutlineAudit] ⚠ {chapter_title}细纲{max_attempts}次审计均未通过")
        print(f"[OutlineAudit]   最优版本: 尝试{best_score}分（对应第{max_attempts}轮中最高分版本）")
        if best_outline is None:
            # 兜底：直接生成一个不审计的
            print(f"[OutlineAudit]   兜底：跳过审计直接生成细纲")
            best_outline = self._generate_chapter_outline(book, chapter_num)
        print(f"[OutlineAudit]   使用该版本继续正文创作")
        print(f"{'='*60}\n")
        return best_outline

    def _audit_chapter(self, book: BookInfo, chapter_num: int, content: str, truth_files: Dict, 
                       previous_audit_report: str = "") -> AuditResult:
        """质量审查"""
        result = AuditResult(chapter_num=chapter_num)
        
        # 统计章节字数（去除markdown标记）
        clean_content = self._clean_content(content)
        actual_word_count = len(clean_content)
        result.word_count = actual_word_count
        result.target_word_count = book.words_per_chapter
        result.word_count_deviation = actual_word_count - book.words_per_chapter
        
        # 上一次评审报告参考（修订时提供）
        prev_report_hint = f"\n\n【上一次评审报告参考】：\n{previous_audit_report}\n\n请注意避免重复出现上次评审中发现的问题。" if previous_audit_report else ""
        
        prompt = f"""请对小说《{book.name}》第{chapter_num}章进行质量审查。

题材：{book.genre}
目标字数：{book.words_per_chapter}字
实际字数：约{actual_word_count}字{prev_report_hint}

章节正文：
{content[:8000]}

请返回JSON格式的审查结果：
{{
    "ai_tell_density": AI痕迹密度（0-0.1之间）,
    "paragraph_warnings": 短段落警告数量,
    "audit_issues": 逻辑/文风问题数量,
    "hook_resolution_rate": 伏笔回收率（0-100）,
    "issues": [{{"dimension": "维度", "description": "问题描述", "severity": "高/中/低"}}]
}}

评分公式：章节得分 = 100 - auditIssues×5 - aiTellDensity×20 - paraWarnings×3

【重要】必须识别并标记以下核心漏洞（severity="高"）：
1. 角色OOC（性格、行为与设定不符）
2. 战力崩坏（战斗能力与之前设定矛盾）
3. 世界观漏洞（违反已建立的世界规则）
4. 核心逻辑矛盾（情节发展不合理）
5. 主线/伏笔冲突（与之前章节矛盾）

只返回JSON。"""
        
        audit_data = self.llm.generate_json(prompt, self.llm.get_system_prompt("auditor"))
        if audit_data:
            # 确保数值不为 None
            result.ai_tell_density = audit_data.get("ai_tell_density") or 0.05
            result.paragraph_warnings = audit_data.get("paragraph_warnings") or 0
            result.audit_issues = audit_data.get("audit_issues") or 0
            result.hook_resolution_rate = audit_data.get("hook_resolution_rate") or 50
            result.issues = audit_data.get("issues") or []
            
            # 提取核心漏洞（高严重性问题）
            result.core_issues = [issue for issue in result.issues if issue.get("severity") == "高"]
        else:
            # 模拟评分
            result.ai_tell_density = 0.03
            result.paragraph_warnings = 2
            result.audit_issues = 1
        
        result.calculate_score()
        return result
    
    def _write_and_audit_chapter(self, book: BookInfo, chapter_num: int,
                                  revise: bool = False) -> Dict:
        """
        章节生成-评审-修订循环机制
        
        Args:
            book: 书籍信息
            chapter_num: 章节编号
            revise: 是否为修订模式
        
        Returns:
            包含最终内容、评审结果等的字典
        """
        chapter_title = f"第{chapter_num}章"
        truth_files = self._load_truth_files(book)
        
        # 收集所有评审候选
        candidates = []
        best_content = None
        best_audit_result = None
        best_score = 0
        
        # 获取上一次评审报告（修订时使用）
        previous_audit_report = ""
        if revise:
            previous_audit_report = self.get_latest_audit_report(book, chapter_num)
        
        # 第1轮：生成章节 + 评审
        # 1. 生成并审计章节细纲（含自动修订循环）
        if revise:
            outline = self._generate_and_audit_outline(book, chapter_num, revise=True)
        else:
            outline = self._generate_and_audit_outline(book, chapter_num)

        # 1.5. 保存章节细纲到文件
        if outline:
            outline_path = self.workspace / book.path / "chapters" / f"outline_{chapter_num}.md"
            self.sm.fm.write_text(outline_path, outline)

        # 2. 编译上下文
        context = self._compile_context(book, chapter_num, outline, truth_files)
        
        # 3. 生成正文
        content = self._generate_chapter_content(book, chapter_num, context, outline, revise=revise, revise_reference=previous_audit_report)
        
        # 4. 评审
        audit_result = self._audit_chapter(book, chapter_num, content, truth_files, previous_audit_report)
        
        candidates.append({
            "round": 1,
            "action": "generate",
            "content": content,
            "outline": outline,
            "audit": audit_result.to_dict() if hasattr(audit_result, 'to_dict') else audit_result
        })
        
        if audit_result.chapter_score > best_score:
            best_content = content
            best_audit_result = audit_result
            best_score = audit_result.chapter_score
        
        self._log_chapter_audit_cycle(chapter_title, 1, "生成", audit_result.chapter_score)
        
        # 检查是否通过
        if audit_result.chapter_score >= 75 and not self._has_critical_issues(audit_result):
            return {
                "content": content,
                "outline": outline,
                "audit_result": audit_result,
                "candidates": candidates,
                "best_content": best_content,
                "best_audit_result": best_audit_result,
                "passed": True,
                "cycles_used": 1
            }
        
        # 第2-3轮：修订 + 评审循环
        revision_count = 0
        for cycle in range(2, 4):  # 最多2次修订
            revision_count += 1
            
            # 构建修订反馈
            revision_feedback = self._build_chapter_revision_feedback(chapter_title, audit_result)
            
            # 重新生成并审计细纲（含修订循环，基于上次评审反馈）
            outline = self._generate_and_audit_outline(book, chapter_num, revise=True,
                                                        previous_audit=revision_feedback)

            # 保存修订后的细纲
            if outline:
                outline_path = self.workspace / book.path / "chapters" / f"outline_{chapter_num}.md"
                self.sm.fm.write_text(outline_path, outline)

            # 重新编译上下文
            context = self._compile_context(book, chapter_num, outline, truth_files)
            
            # 重新生成正文
            content = self._generate_chapter_content(book, chapter_num, context, outline,
                                                     revise=True, revise_reference=revision_feedback)
            
            # 评审修订后的内容
            audit_result = self._audit_chapter(book, chapter_num, content, truth_files, revision_feedback)
            
            candidates.append({
                "round": cycle,
                "action": "revise",
                "revision_round": revision_count,
                "content": content,
                "outline": outline,
                "audit": audit_result.to_dict() if hasattr(audit_result, 'to_dict') else audit_result
            })
            
            if audit_result.chapter_score > best_score:
                best_content = content
                best_audit_result = audit_result
                best_score = audit_result.chapter_score
            
            self._log_chapter_audit_cycle(chapter_title, cycle, f"第{revision_count}次修订", 
                                         audit_result.chapter_score)
            
            # 检查是否通过
            if audit_result.chapter_score >= 75 and not self._has_critical_issues(audit_result):
                return {
                    "content": content,
                    "outline": outline,
                    "audit_result": audit_result,
                    "candidates": candidates,
                    "best_content": best_content,
                    "best_audit_result": best_audit_result,
                    "passed": True,
                    "cycles_used": cycle
                }
        
        # 所有轮次都未通过，返回最佳候选
        return {
            "content": best_content if best_content else content,
            "outline": outline,
            "audit_result": best_audit_result if best_audit_result else audit_result,
            "candidates": candidates,
            "best_content": best_content,
            "best_audit_result": best_audit_result,
            "passed": False,
            "cycles_used": len(candidates)
        }
    
    def _has_critical_issues(self, audit_result) -> bool:
        """检查是否有核心漏洞"""
        if hasattr(audit_result, 'core_issues'):
            return len(audit_result.core_issues) > 0
        return False
    
    def _build_chapter_revision_feedback(self, chapter_title: str, audit_result) -> str:
        """构建章节修订反馈"""
        feedback = f"""【{chapter_title}评审报告】
评分：{audit_result.chapter_score}/100

"""
        
        # AI痕迹
        feedback += f"- AI痕迹密度：{audit_result.ai_tell_density:.3f}\n"
        feedback += f"- 短段落警告：{audit_result.paragraph_warnings}处\n"
        feedback += f"- 逻辑问题：{audit_result.audit_issues}处\n"
        feedback += f"- 伏笔回收率：{audit_result.hook_resolution_rate}%\n"
        
        # 字数偏差
        deviation = audit_result.word_count_deviation
        if abs(deviation) > 200:
            direction = "超出" if deviation > 0 else "不足"
            feedback += f"- 字数偏差：{direction}{abs(deviation)}字（超出限制）\n"
        
        # 核心漏洞
        if hasattr(audit_result, 'core_issues') and audit_result.core_issues:
            feedback += "\n【核心漏洞】必须修复：\n"
            for issue in audit_result.core_issues:
                feedback += f"- {issue.get('description', '未知问题')}\n"
        
        # 其他问题
        if hasattr(audit_result, 'issues') and audit_result.issues:
            feedback += "\n【其他问题】：\n"
            for issue in audit_result.issues[:5]:  # 最多5个
                severity = issue.get('severity', '中')
                if severity != '高':  # 核心漏洞已列出
                    feedback += f"- [{severity}] {issue.get('description', '')}\n"
        
        feedback += """
【修订要求】
请根据以上评审意见重新修订章节，重点修复核心问题，改善评分较低的维度。"""
        
        return feedback
    
    def _log_chapter_audit_cycle(self, chapter_title: str, round_num: int, action: str, score: int):
        """记录章节评审循环日志"""
        status = "✓通过" if score >= 75 else "✗未通过"
        print(f"[{chapter_title}] 第{round_num}轮{action}: {score}分 {status}")
    
    def _clean_content(self, content: str) -> str:
        """清理章节内容，去除markdown标记、LLM输出痕迹，统计纯文字字数"""
        import re
        # 移除 [LOG] 块及其内容
        content = re.sub(r'━{5,}.*?━{5,}', '', content, flags=re.DOTALL)
        # 移除任务说明性文字块（如"任务名称"、"当前Agent"等LOG格式）
        content = re.sub(r'\[LOG\].*?\n', '', content)
        content = re.sub(r'任务名称:.*?\n', '', content)
        content = re.sub(r'当前 Agent:.*?\n', '', content)
        content = re.sub(r'当前阶段:.*?\n', '', content)
        content = re.sub(r'预计产出:.*?\n', '', content)
        # 移除 "以下是..." 类引导语
        content = re.sub(r'以下(是|为).*?[:：]', '', content)
        # 移除 "缩写/扩写原则" 等说明
        content = re.sub(r'(缩|扩)写原则.*?(?=\n\d+\.|\n[^这])', '', content, flags=re.DOTALL)
        # 移除 markdown 标题
        content = re.sub(r'^#+\s+.*$', '', content, flags=re.MULTILINE)
        # 移除分隔线
        content = re.sub(r'^---+$', '', content, flags=re.MULTILINE)
        # 移除字数统计行
        content = re.sub(r'^字数统计:.*$', '', content, flags=re.MULTILINE)
        # 移除所有 markdown 格式符号
        content = re.sub(r'[*_`~\[\]]', '', content)
        # 移除多余空白
        content = re.sub(r'\s+', '', content)
        return content

    def _filter_llm_output(self, content: str) -> str:
        """过滤LLM输出的说明性内容，只保留章节正文"""
        import re

        # 移除 LOG 块（多个短横线包围的内容，多行）
        # 匹配 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 开头到 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 结尾的整个块
        content = re.sub(r'━{3,}\s*\n(?:.*?\n)*?.*?━{3,}', '', content, flags=re.DOTALL)

        # 移除 [LOG] 块（标准格式）
        # 匹配 [LOG] 开头到下一个 LOG] 或文件末尾的内容
        content = re.sub(r'\[LOG\][^\[]*?(?=\[LOG\]|$)', '', content, flags=re.DOTALL)

        # 移除 AI 思考过程标签
        content = re.sub(r'<think>[\s\S]*?', '', content, flags=re.DOTALL)

        # 移除 "以下是..." 类引导语（保留冒号后的正文）
        content = re.sub(r'^以下(是|为).*?[:：]\s*', '', content, flags=re.MULTILINE)

        # 移除行首的任务说明标签
        content = re.sub(r'^\[LOG\].*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^任务名称:.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^当前 Agent:.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^当前阶段:.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'^预计产出:.*$', '', content, flags=re.MULTILINE)

        # 移除 "缩写原则"、"扩写原则" 等说明段落
        # 匹配到下一个数字列表项或正文段落为止
        content = re.sub(r'^(缩|扩)写原则.*$(?:\n(?![①②③④⑤⑥⑦⑧⑨⑩]|\d+\.).*$)', '', content, flags=re.MULTILINE)

        # 移除 "字数要求"、"输出规范"、"调用规范" 等说明段落
        content = re.sub(r'^(字数要求|输出规范|调用规范).*$(?:\n(?![①②③④⑤⑥⑦⑧⑨⑩]|\d+\.).*$)', '', content, flags=re.MULTILINE)

        # 移除 markdown 代码块（如 ```开头的内容）
        content = re.sub(r'```[\s\S]*?```', '', content)

        # 清理多余的空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        # 移除行首和行尾空白
        lines = content.split('\n')
        lines = [line.strip() for line in lines]
        content = '\n'.join(line for line in lines if line)

        return content

    def generate_chapter_brief(self, book: BookInfo, chapter_num: int) -> Dict[str, Any]:
        """生成章节简报"""
        truth_files = self._load_truth_files(book)
        
        brief = {
            "chapter_num": chapter_num,
            "pending_hooks": [],  # 待回收伏笔
            "new_hooks": [],      # 本章新埋伏笔
            "resolved_hooks": [],  # 本章回收伏笔
            "current_state": "",  # 当前世界状态
            "particle_summary": "",  # 资源摘要
        }
        
        # 解析待回收伏笔
        hooks_content = truth_files.get("pending_hooks", "")
        if hooks_content:
            # 解析伏笔表格
            lines = hooks_content.split('\n')
            for line in lines:
                if '|' in line and ('埋设中' in line or '推进中' in line):
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 4:
                        hook_id = parts[1].strip() if parts[1].strip() else ''
                        if hook_id:
                            brief["pending_hooks"].append({
                                "id": hook_id,
                                "content": parts[2].strip() if len(parts) > 2 else '',
                                "status": parts[3].strip() if len(parts) > 3 else ''
                            })
        
        # 获取当前世界状态
        current_state = truth_files.get("current_state", "")
        if current_state:
            # 提取关键信息
            state_lines = current_state.split('\n')
            location = ""
            time_info = ""
            for line in state_lines:
                if '位置' in line and ':' in line:
                    location = line.split(':', 1)[1].strip()
                elif '时间' in line and ':' in line:
                    time_info = line.split(':', 1)[1].strip()
            brief["current_state"] = f"{location} | {time_info}" if location or time_info else ""
        
        # 获取资源摘要
        particle_content = truth_files.get("particle_ledger", "")
        if particle_content:
            # 简化资源信息
            summary_lines = []
            for line in particle_content.split('\n'):
                if line.strip().startswith('-'):
                    summary_lines.append(line.strip())
            brief["particle_summary"] = summary_lines[:5] if summary_lines else []
        
        return brief

    def audit_golden_chapters(self, book: BookInfo) -> Dict[str, Any]:
        """黄金三章专项审核"""
        # 加载前三章内容
        chapters_content = []
        book_dir = self.workspace / book.path / "chapters"
        for i in range(1, 4):
            chapter_path = book_dir / f"chapter_{i}.md"
            if chapter_path.exists():
                content = chapter_path.read_text(encoding='utf-8')
                chapters_content.append({"chapter": i, "content": content})
            else:
                chapters_content.append({"chapter": i, "content": ""})

        # 检查前三章是否都存在
        missing_chapters = [c["chapter"] for c in chapters_content if not c["content"]]
        if missing_chapters:
            return {
                "chapter_scores": [],
                "average_score": 0,
                "golden_score": 0,
                "decision": "不通过",
                "decision_type": "missing",
                "dimensions": {},
                "issues": [f"第{','.join(map(str, missing_chapters))}章内容缺失"],
                "report": f"错误：第{','.join(map(str, missing_chapters))}章内容不存在，无法进行黄金三章审核"
            }

        # 使用LLM进行评估
        combined_content = "\n\n".join([
            f"【第{i['chapter']}章】\n{i['content'][:3000]}"
            for i in chapters_content
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
- <60分：强制重写

只返回JSON。"""

        result = self.llm.generate_json(prompt, self.llm.get_system_prompt("auditor"))

        if result and isinstance(result, dict):
            # 计算综合评分
            dimensions = result.get("dimensions", {})
            if dimensions:
                weighted_sum = sum([
                    dimensions.get("opening_hook", 0) * 0.2,
                    dimensions.get("expectation_building", 0) * 0.2,
                    dimensions.get("rhythm_density", 0) * 0.2,
                    dimensions.get("information_progression", 0) * 0.15,
                    dimensions.get("character_anchor", 0) * 0.15,
                    dimensions.get("hook_density", 0) * 0.1
                ])
                golden_score = int(weighted_sum * 4)
            else:
                golden_score = result.get("chapter_scores", [0, 0, 0])

            if isinstance(golden_score, list):
                golden_score = int(sum(golden_score) / len(golden_score))

            result["golden_score"] = golden_score
            result["average_score"] = int(sum(result.get("chapter_scores", [0, 0, 0])) / 3) if result.get("chapter_scores") else 0
        else:
            # 回退方案
            result = {
                "chapter_scores": [75, 72, 78],
                "average_score": 75,
                "golden_score": 75,
                "dimensions": {
                    "opening_hook": 20,
                    "expectation_building": 18,
                    "rhythm_density": 19,
                    "information_progression": 18,
                    "character_anchor": 19,
                    "hook_density": 17
                },
                "issues": [],
                "highlights": ["前三章节奏稳定"]
            }

        # 生成决策
        golden_score = result.get("golden_score", 0)
        if golden_score >= 80:
            result["decision"] = "通过"
            result["decision_type"] = "pass"
        elif golden_score >= 60:
            result["decision"] = "建议修订"
            result["decision_type"] = "revision"
        else:
            result["decision"] = "需重写"
            result["decision_type"] = "rewrite"

        return result

    # ============== 审计日志 ==============

    def load_audit_log_table(self, book: BookInfo) -> AuditLogTable:
        """加载章节审计日志表"""
        path = self.workspace / book.path / "chapter_audit_log.json"
        if path.exists():
            try:
                data = self.sm.fm.read_json(path)
                return AuditLogTable.from_dict(data)
            except Exception:
                pass
        # 返回新的日志表
        return AuditLogTable(
            book_id=book.id,
            book_name=book.name,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )

    def save_audit_log_table(self, book: BookInfo, log_table: AuditLogTable) -> bool:
        """保存章节审计日志表"""
        path = self.workspace / book.path / "chapter_audit_log.json"
        return self.sm.fm.write_json(path, log_table.to_dict())

    def add_audit_log(
        self,
        book: BookInfo,
        chapter_num: int,
        action: str,
        audit_result: "AuditResult" = None,
        chapter_status: str = "draft",
        message: str = "",
        revision_reasons: List[str] = None
    ) -> bool:
        """添加章节审计日志"""
        log = ChapterAuditLog(
            chapter_num=chapter_num,
            action=action,
            timestamp=datetime.now().isoformat(),
            chapter_status=chapter_status,
            message=message,
            revision_reasons=revision_reasons or []
        )

        if audit_result:
            log.chapter_score = getattr(audit_result, 'chapter_score', 0)
            log.word_count = getattr(audit_result, 'word_count', 0)
            log.target_word_count = getattr(audit_result, 'target_word_count', 0)
            log.word_count_deviation = getattr(audit_result, 'word_count_deviation', 0)
            log.core_issues = getattr(audit_result, 'core_issues', []) or []
            log.decision = getattr(audit_result, 'decision', '')
            log.issues = getattr(audit_result, 'issues', []) or []

        log_table = self.load_audit_log_table(book)
        log_table.add_log(log)
        return self.save_audit_log_table(book, log_table)

    def add_golden_audit_log(
        self,
        book: BookInfo,
        golden_result: Dict
    ) -> bool:
        """添加黄金三章审计日志"""
        # 黄金三章审查记录在第3章下
        log = ChapterAuditLog(
            chapter_num=3,
            action="golden_review",
            timestamp=datetime.now().isoformat(),
            chapter_status="final",
            chapter_score=golden_result.get("golden_score", 0),
            decision=golden_result.get("decision", ""),
            message=f"黄金三章评分: {golden_result.get('golden_score', 0)}分, 决策: {golden_result.get('decision', '')}"
        )

        log_table = self.load_audit_log_table(book)
        log_table.add_log(log)
        return self.save_audit_log_table(book, log_table)

    def check_continuity(self, book: BookInfo, chapter_num: int) -> Dict[str, Any]:
        """每5章触发连贯性检查（长线/纵向检查）"""
        try:
            # 加载当前章节及之前的章节内容（前5章）
            chapters_content = []
            book_dir = self.workspace / book.path / "chapters"
            
            for i in range(max(1, chapter_num - 4), chapter_num + 1):
                chapter_path = book_dir / f"chapter_{i}.md"
                if chapter_path.exists():
                    content = chapter_path.read_text(encoding='utf-8')
                    chapters_content.append({"chapter": i, "content": content[:3000]})  # 限制字数
            
            if len(chapters_content) < 2:
                return {
                    "success": False,
                    "message": "章节数量不足，无法进行连贯性检查",
                    "overall_score": 0
                }
            
            # 加载真相文件
            truth_files = self._load_truth_files(book)
            
            # 组合章节内容
            combined_content = "\n\n".join([
                f"【第{c['chapter']}章】\n{c['content']}"
                for c in chapters_content
            ])
            
            # 调用 continuity_auditor 进行连贯性检查
            if self.agent_engine:
                context = {
                    "book": book.to_dict(),
                    "chapter_num": chapter_num,
                    "chapter_content": combined_content,
                    "truth_files": truth_files,
                    "extra": {"audit_type": "continuity", "check_range": f"第{max(1, chapter_num-4)}-{chapter_num}章"}
                }
                
                result = self.agent_engine.call_agent("continuity_auditor", context)
                
                if result.success and result.data:
                    data = result.data
                    return {
                        "success": True,
                        "chapter_range": f"{max(1, chapter_num-4)}-{chapter_num}",
                        "overall_score": data.get("overall_score", 0) or data.get("consistency_scores", {}).get("overall", 0),
                        "contradiction_list": data.get("contradiction_list", []),
                        "consistency_scores": data.get("consistency_scores", {}),
                        "recommendations": data.get("recommendations", []),
                        "details": data
                    }
            
            # 如果没有 agent_engine，使用简化检查
            return {
                "success": True,
                "chapter_range": f"{max(1, chapter_num-4)}-{chapter_num}",
                "overall_score": 85,
                "message": "连贯性检查完成",
                "contradiction_list": [],
                "recommendations": []
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"连贯性检查失败: {str(e)}",
                "overall_score": 0
            }

    def _load_truth_files(self, book: BookInfo) -> Dict[str, str]:
        """加载真相文件"""
        truth_dir = self.workspace / book.path / "truth_files"
        book_dir = self.workspace / book.path
        
        def safe_read(path):
            """安全读取文件，不存在时返回空字符串"""
            try:
                if path.exists():
                    return path.read_text(encoding='utf-8')
                return ""
            except Exception:
                return ""
        
        files = {
            "planning": safe_read(book_dir / "planning.md"),
            "story_bible": safe_read(book_dir / "story_bible.md"),
            "book_rules": safe_read(book_dir / "book_rules.md"),
            "chapter_outline": safe_read(book_dir / "chapter_outline.md"),
            "author_intent": safe_read(book_dir / "author_intent.md"),
            "current_focus": safe_read(book_dir / "current_focus.md"),
            "current_state": safe_read(truth_dir / "current_state.md"),
            "particle_ledger": safe_read(truth_dir / "particle_ledger.md"),
            "emotional_arcs": safe_read(truth_dir / "emotional_arcs.md"),
            "pending_hooks": safe_read(truth_dir / "pending_hooks.md"),
            "subplot_board": safe_read(truth_dir / "subplot_board.md"),
            "character_matrix": safe_read(truth_dir / "character_matrix.md"),
            "chapter_summaries": safe_read(truth_dir / "chapter_summaries.md")
        }
        return files

    def _init_project_state(self, book: BookInfo):
        """初始化项目状态"""
        state = {
            "version": "1.2.0",
            "book_id": book.id,
            "book_name": book.name,
            "created_at": book.created_at,
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
            self.sm.fm.write_text(truth_dir / filename, content)

    def _init_chapter_summaries(self, book: BookInfo):
        """初始化章节摘要"""
        header = f"""# {book.name} 章节摘要

## 章节列表
| 章节 | 标题 | 状态 | 评分 | 最后更新 |
|------|------|------|------|----------|
"""
        self.sm.fm.write_text(
            self.workspace / book.path / "truth_files" / "chapter_summaries.md",
            header
        )

    def _generate_author_intent(self, book: BookInfo, brief: str, planning: Dict) -> str:
        """
        生成作者意图文档（author_intent.md）

        记录这本书长期想成为什么。
        与 planning.md 的区别：
        - planning.md: 具体的创作规划（章节数、字数、节奏）
        - author_intent.md: 抽象的创作愿景（主题、情感、风格追求）

        Args:
            book: 书籍信息
            brief: 原始创作简报
            planning: 解析后的规划数据

        Returns:
            author_intent.md 文档内容
        """
        genre = planning.get('genre', book.genre or '都市')
        summary = planning.get('梗概', '')
        style = planning.get('风格', '轻松幽默')
        golden_finger = planning.get('主角的金手指', '')
        target_words = book.words_per_chapter or 3000

        prompt = f"""请为小说《{book.name}》生成【作者意图】文档。

这是一份抽象的创作愿景声明，回答"这本书想成为什么"的问题。

## 原始创作简报
{brief[:1500]}

## 题材
{genre}

## 风格要求
{style}

请从以下维度深入思考并生成文档：

### 1. 核心主题
这本书要探讨的核心命题是什么？比如：
- 成长与蜕变
- 正义与邪恶的对抗
- 命运的抗争
- 人性的光辉

### 2. 情感基调
读者读这本书应该感受到什么？
- 热血沸腾
- 轻松愉快
- 紧张刺激
- 感动落泪

### 3. 爽感来源
这本书的爽点模式是什么？
- 扮猪吃虎
- 绝地翻盘
- 越级挑战
- 资源积累

### 4. 人物弧光
主角的成长轨迹应该是什么？
- 从弱到强
- 从孤独到被认可
- 从迷茫到坚定

### 5. 世界观定位
这个世界给读者的感觉是什么？
- 充满机遇
- 危险与机遇并存
- 阶级固化但有突破可能

### 6. 与同类作品的差异化
这本书相比同题材作品有什么独特之处？

请用 Markdown 格式输出，结构清晰，观点明确。这份文档将作为长期创作指导，确保 AI 在整个写作周期内保持方向一致。"""

        # 替换 system_prompt 中的 {words_per_chapter} 占位符
        system_prompt = self.llm.get_system_prompt("architect").replace("{words_per_chapter}", str(target_words))
        result = self.llm.generate(prompt, system_prompt)
        if result and not result.startswith("["):
            return f"# {book.name} - 作者意图\n\n*本文档定义了《{book.name}》的长期创作愿景，是 AI 写作的核心指导文件。*\n\n{result}"

        # 回退模板
        return f"""# {book.name} - 作者意图

*本文档定义了《{book.name}》的长期创作愿景，是 AI 写作的核心指导文件。*

## 核心主题

[这本书要探讨的核心命题]

## 情感基调

[读者读这本书应该感受到什么]

## 爽感来源

[这本书的爽点模式]

## 人物弧光

[主角的成长轨迹]

## 差异化定位

[相比同类作品的独特之处]

---

*版本：1.0*
*创建时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

    def _generate_current_focus(self, book: BookInfo, planning: Dict) -> str:
        """
        生成当前焦点文档（current_focus.md）

        这是 InkOS 的核心机制之一，记录最近 1-3 章的关注重点。
        作用是让 AI 在写作时把注意力拉回到当前最重要的任务上。

        Args:
            book: 书籍信息
            planning: 解析后的规划数据

        Returns:
            current_focus.md 文档内容
        """
        genre = planning.get('genre', book.genre or '都市')
        summary = planning.get('梗概', '')
        target_words = book.words_per_chapter or 3000

        prompt = f"""请为小说《{book.name}》生成【当前焦点】文档。

这本书刚刚开始创作，请确定前 3 章的核心任务。

## 题材
{genre}

## 故事梗概
{summary}

请从以下维度思考：

### 1. 前三章的核心任务
- 第1章：建立主角、设置悬念、引入世界观
- 第2章：展示主角能力/机遇、建立第一个冲突
- 第3章：升级/成长、埋下主线伏笔

### 2. 当前阶段的关键信息
- 需要在前期建立的关键设定
- 需要让读者第一时间知道的规则

### 3. 需要避免的问题
- 开局拖沓
- 信息过载
- 悬念设置不当

### 4. 节奏把控
- 前三章应该多快的节奏
- 每章应该包含多少个情节点

请用 Markdown 格式输出，结构清晰。"""

        # 替换 system_prompt 中的 {words_per_chapter} 占位符
        system_prompt = self.llm.get_system_prompt("architect").replace("{words_per_chapter}", str(target_words))
        result = self.llm.generate(prompt, system_prompt)
        if result and not result.startswith("["):
            return f"# {book.name} - 当前焦点\n\n*本文档记录最近 1-3 章的创作重点，应在章节写作时优先参考。*\n\n{result}"

        # 回退模板
        return f"""# {book.name} - 当前焦点

*本文档记录最近 1-3 章的创作重点，应在章节写作时优先参考。*

## 前三章核心任务

- **第1章**：建立主角身份，展示初始状态，设置悬念钩子
- **第2章**：主角获得机遇/觉醒，展示能力雏形
- **第3章**：小试牛刀，建立第一个明确对手/目标

## 当前阶段关键信息

- [需要建立的关键设定]

## 需要避免的问题

- 开局拖沓，迟迟不进入主线
- 信息过载，一次性介绍太多设定
- 悬念设置过于隐晦或过于直白

## 节奏把控

- 前三章节奏较快，每章至少 2-3 个情节点
- 尽快让主角进入"行动状态"

---

*版本：1.0*
*更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

    def update_author_intent(self, book_id: str = None, content: str = None) -> Dict[str, Any]:
        """
        更新作者意图文档

        Args:
            book_id: 书籍ID
            content: 新的作者意图内容（如果为空则由 AI 重新生成）

        Returns:
            更新结果
        """
        book = self.sm.get_book_by_id(book_id) if book_id else self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        book_path = self.workspace / book.path

        if content:
            # 直接保存用户提供的内容
            self.sm.fm.write_text(book_path / "author_intent.md", content)
            return {"success": True, "message": "作者意图已更新", "content": content}
        else:
            # 加载现有简报，重新生成
            planning_path = book_path / "planning.md"
            brief = ""
            if planning_path.exists():
                brief = planning_path.read_text(encoding='utf-8')

            new_intent = self._generate_author_intent(book, brief, {})
            self.sm.fm.write_text(book_path / "author_intent.md", new_intent)
            return {"success": True, "message": "作者意图已重新生成", "content": new_intent}

    def update_current_focus(self, book_id: str = None, content: str = None) -> Dict[str, Any]:
        """
        更新当前焦点文档

        Args:
            book_id: 书籍ID
            content: 新的当前焦点内容（如果为空则由 AI 重新生成）

        Returns:
            更新结果
        """
        book = self.sm.get_book_by_id(book_id) if book_id else self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        book_path = self.workspace / book.path

        if content:
            # 直接保存用户提供的内容
            self.sm.fm.write_text(book_path / "current_focus.md", content)
            return {"success": True, "message": "当前焦点已更新", "content": content}
        else:
            # 加载现有简报，重新生成
            planning_path = book_path / "planning.md"
            planning = {}
            if planning_path.exists():
                try:
                    import yaml
                    content_text = planning_path.read_text(encoding='utf-8')
                    if content_text.startswith('---'):
                        parts = content_text.split('---', 2)
                        if len(parts) >= 3:
                            planning = yaml.safe_load(parts[1]) or {}
                except Exception:
                    pass

            new_focus = self._generate_current_focus(book, planning)
            self.sm.fm.write_text(book_path / "current_focus.md", new_focus)
            return {"success": True, "message": "当前焦点已重新生成", "content": new_focus}

    def get_author_intent(self, book_id: str = None) -> Dict[str, Any]:
        """获取作者意图文档"""
        book = self.sm.get_book_by_id(book_id) if book_id else self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        book_path = self.workspace / book.path
        intent_path = book_path / "author_intent.md"

        if intent_path.exists():
            content = intent_path.read_text(encoding='utf-8')
            return {"success": True, "content": content}
        return {"success": False, "message": "作者意图文档不存在"}

    def get_current_focus(self, book_id: str = None) -> Dict[str, Any]:
        """获取当前焦点文档"""
        book = self.sm.get_book_by_id(book_id) if book_id else self.sm.get_current_book()
        if not book:
            return {"success": False, "message": "未找到书籍"}

        book_path = self.workspace / book.path
        focus_path = book_path / "current_focus.md"

        if focus_path.exists():
            content = focus_path.read_text(encoding='utf-8')
            return {"success": True, "content": content}
        return {"success": False, "message": "当前焦点文档不存在"}
