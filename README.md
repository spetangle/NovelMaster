# NovelMaster

AI 驱动的多 Agent 小说创作引擎，专注于长篇网络小说的自动化生成与质量控制。

本项目为根据 [Inkos](https://github.com/Narcooo/inkos) 项目 vibe coding 的 Python 实现，由 AI 编写代码。

> **致谢**: 本项目灵感和大部分工作流来自 [Inkos](https://github.com/Narcooo/inkos) 开源项目，感谢大佬的贡献！

---

## 特性

- **多 Agent 协作**: 13+ 专业 Agent 协同工作，覆盖从世界观构建到章节审核的全流程
- **职责驱动架构**: Agent 职责通过 YAML 文件定义，与调用逻辑分离
- **真相文件体系**: 维护角色关系、伏笔状态、世界观演进等核心文档
- **质量门禁**: 自动评分与重写机制，确保章节质量
- **伏笔管理**: 全生命周期伏笔追踪与回收提醒
- **多后端支持**: 支持 OpenAI、DeepSeek、Qwen 等多种 LLM 提供商

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        NovelMaster Engine                         │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────┐  ┌────────┐  │
│  │ Planner │→ │ Architect│→ │Compiler │→ │Writer│→ │Auditor │  │
│  └─────────┘  └──────────┘  └─────────┘  └──────┘  └────────┘  │
│  ┌──────────┐  ┌───────────┐  ┌─────────┐  ┌─────────────────┐ │
│  │ Observer │  │ Reflector │  │Controller│  │ ContinuityAuditor│ │
│  └──────────┘  └───────────┘  └─────────┘  └─────────────────┘ │
│  ┌───────────┐  ┌────────┐  ┌──────────┐  ┌──────────────┐     │
│  │HookManager│  │ Radar  │  │GlobalEditor│ │ References  │     │
│  └───────────┘  └────────┘  └──────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### Agent 职责

| Agent | 名称 | 职责 |
|-------|------|------|
| Planner | 规划师 | 解读用户创作需求，生成创作规划书 |
| Architect | 建筑师 | 构建世界观、生成章节细纲 |
| Compiler | 编译器 | 整合多源信息，编译标准化上下文包 |
| Writer | 作家 | 生成章节正文 |
| Observer | 观察者 | 提取事实，更新真相文件 |
| Reflector | 反思者 | 分析偏差，计算 Delta，调整策略 |
| Controller | 控制器 | 质量门禁，流程控制 |
| Auditor | 审计师 | 质量审查与评分 |
| HookManager | 伏笔管理 | 伏笔全生命周期管控 |
| ContinuityAuditor | 连贯性审计 | 跨章节一致性检查 |
| GlobalEditor | 全局修正 | 全书级别内容修正 |
| Radar | 市场调研 | 趋势捕捉与创作建议 |
| References | 参考库 | 创作资料索引 |

---

## 目录结构

```
novelmaster/
├── app.py                      # Web UI 入口
├── main.py                     # CLI 入口
├── requirements.txt            # 依赖
│
├── core/                       # 核心模块
│   ├── __init__.py
│   ├── models.py               # 数据模型
│   ├── llm_service.py           # LLM 服务
│   ├── state_manager.py         # 状态管理
│   ├── file_manager.py          # 文件管理
│   └── novel_engine.py          # 核心引擎
│
├── agents/                     # Agent 系统（职责驱动）
│   ├── __init__.py
│   ├── base.py                 # 通用 Agent 基类
│   ├── engine.py                # Agent 引擎
│   ├── loader.py               # 职责加载器
│   └── roles/                  # Agent 职责定义 (YAML)
│       ├── planner.yaml
│       ├── architect.yaml
│       ├── compiler.yaml
│       ├── writer.yaml
│       ├── observer.yaml
│       ├── reflector.yaml
│       ├── controller.yaml
│       ├── auditor.yaml
│       ├── hook_manager.yaml
│       ├── continuity_auditor.yaml
│       ├── global_editor.yaml
│       ├── radar.yaml
│       └── references.yaml
│
├── workflows/                  # 工作流编排
│   ├── __init__.py
│   ├── book_creation.py        # 书籍创建工作流
│   ├── chapter_writing.py       # 章节创作工作流
│   └── audit.py                # 审核工作流
│
├── api/                        # API 路由
│   ├── __init__.py
│   ├── routes.py
│   └── task_manager.py
│
├── web/                        # 前端资源
│   └── static/
│
└── workspace/                 # 工作目录
    └── books/
        └── {book_id}/
            ├── story_bible.md       # 世界观设定
            ├── book_rules.md        # 创作规则
            ├── chapter_outline.md   # 章节大纲
            ├── planning.md          # 规划书
            ├── characters.md        # 人物设定
            ├── author_intent.md     # 作者意图
            ├── current_focus.md     # 当前焦点
            ├── project_state.json   # 项目状态
            ├── chapters/            # 章节正文
            │   └── chapter_*.md
            └── truth_files/         # 真相文件
                ├── current_state.md       # 世界状态
                ├── pending_hooks.md       # 伏笔总表
                ├── character_matrix.md    # 角色矩阵
                └── chapter_summaries.md   # 章节摘要
```

---

## 安装

```bash
# 克隆项目
git clone https://github.com/yourusername/novelmaster.git
cd novelmaster

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 添加 LLM API Key
```

---

## 快速开始

### 1. Web UI 界面

```bash
python app.py
```

访问 http://localhost:13567

### 2. 命令行使用

```bash
# 创建新书
python main.py create "书名: 都市超能\n题材: 都市异能\n平台: 番茄小说"

# 创作章节
python main.py write 1

# 查看状态
python main.py status

# 列出所有书籍
python main.py list

# 黄金三章审核
python main.py audit --golden
```

### 3. API 调用

```bash
# 启动 API 服务
python app.py

# 创建书籍
curl -X POST http://localhost:13567/api/books \
  -H "Content-Type: application/json" \
  -d '{"brief": "书名: 测试小说\n题材: 都市\n章节字数: 3000"}'

# 创作章节
curl -X POST http://localhost:13567/api/write/execute \
  -H "Content-Type: application/json" \
  -d '{"book_id": "xxx", "chapter_num": 1}'
```

---

## 配置说明

编辑 `.env` 文件：

```env
# LLM 提供商配置
LLM_PROVIDER=openai        # openai / deepseek / qwen / ollama / 自定义
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1

# 或使用硅基流动
LLM_PROVIDER=custom
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=your-key
```

---

## Agent 职责文件

Agent 职责通过 YAML 文件定义，位于 `agents/roles/` 目录。

### 文件格式

```yaml
# agents/roles/planner.yaml
name: planner
name_cn: 规划师
description: 解读用户创作需求，生成创作规划书

system_prompt: |
  你是一位专业的小说创作规划师...

dimensions:
  - name: 题材识别
    weight: 0.2
    description: 能否准确识别并验证题材类型

output_format: json
required_fields:
  - book_name
  - genre
  - platform

workflows:
  - book_creation
```

### 动态占位符

系统支持在职责文件中使用占位符，运行时自动替换：

| 占位符 | 说明 | 来源 |
|--------|------|------|
| `{words_per_chapter}` | 每章字数 | 书籍配置 |
| `{book_id}` | 书籍ID | 书籍配置 |
| `{book_name}` | 书名 | 书籍配置 |
| `{genre}` | 题材 | 书籍配置 |
| `{platform}` | 平台 | 书籍配置 |

---

## 评分机制

章节综合分 = 100 - auditIssues×5 - aiTellDensity×20 - paraWarnings×3

| 分数 | 决策 |
|------|------|
| ≥75 | 通过 |
| 60-74 | 修订后通过 |
| <60 | 不通过（重写） |

单章重写上限 3 次，超过后暂停等待人工介入。

---

## 章节状态流转

```
draft → reviewing → approved → finalized
         ↑____________↓ (评分<75时退回重写)
```

---

## 工作流

### 书籍创建工作流

1. **Planner** 解析创作简报，生成规划书
2. **Architect** 构建世界观 (story_bible.md)
3. **Architect** 生成创作规则 (book_rules.md)
4. 系统初始化真相文件和章节摘要

### 章节创作工作流

1. **Compiler** 编译上下文包
2. **Architect** 生成章节细纲
3. **Writer** 创作正文
4. **Controller** 质量校验
5. **Auditor** 审核评分
6. **HookManager** 伏笔管理
7. **Observer** 更新真相文件

---

## 灵感对话模式

NovelMaster 支持通过对话收集创作灵感：

1. 创建灵感书籍（无章节）
2. 通过多轮对话完善创作设定
3. 设定收集完整后，生成设定文档

---

## 开发

### 添加新 Agent

1. 在 `agents/roles/` 创建 `{agent_name}.yaml`
2. 定义 system_prompt、dimensions、workflows
3. 在对应工作流中引用

### 修改工作流

编辑 `workflows/` 目录下的工作流文件，调整 Agent 调用顺序和参数。

---

## License

MIT License