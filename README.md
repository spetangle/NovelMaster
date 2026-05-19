# NovelMaster

AI 驱动的多 Agent 小说创作引擎，专注于长篇网络小说的自动化生成与质量控制。

本项目为根据Inkos项目vibe coding的Python实现，由AI编写代码。

目录：【小说家skill工作流】中存放的是由Inkos提取的AI工作流文档（markdown格式）。

## 致谢

> **本项目灵感和大部分工作流来自 [Inkos](https://github.com/Narcooo/inkos) 项目（[https://github.com/Narcooo/inkos](https://github.com/Narcooo/inkos "https://github.com/Narcooo/inkos")），感谢大佬的开源！**

## 特性

- **多 Agent 协作**: 11 个专业 Agent 协同工作，覆盖从世界观构建到章节审核的全流程
- **真相文件体系**: 维护角色关系、伏笔状态、世界观演进等核心文档
- **质量门禁**: 自动评分与重写机制，确保章节质量
- **伏笔管理**: 全生命周期伏笔追踪与回收提醒
- **多后端支持**: 支持 OpenAI、DeepSeek、Qwen 等多种 LLM 提供商

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                      NovelMaster Engine                       │
├──────────────────────────────────────────────────────────────┤
│  Planner │ Architect │ Compiler │ Writer │ Observer │ Auditor│
│  Controller │ Reflector │ HookManager │ ContinuityAuditor    │
└──────────────────────────────────────────────────────────────┘
```

### Agent 职责

| Agent             | 名称       | 职责                         |
| ----------------- | ---------- | ---------------------------- |
| Planner           | 规划师     | 解析创作简报，生成规范规划书 |
| Architect         | 建筑师     | 构建世界观、生成章节细纲     |
| Compiler          | 编译器     | 整合上下文与真相文件         |
| Writer            | 作家       | 生成章节正文                 |
| Observer          | 观察者     | 提取事实，更新真相文件       |
| Reflector         | 反思者     | 分析偏差，调整创作策略       |
| Controller        | 控制器     | 质量门禁，流程控制           |
| Auditor           | 审计师     | 质量审查，评分               |
| HookManager       | 伏笔管理   | 伏笔生命周期管理             |
| ContinuityAuditor | 连贯性审计 | 跨章节一致性检查             |

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

## 快速开始

### 1. WebUI 界面

```bash
python app.py
```

访问 http://localhost:13567

### 2. 命令行使用

```bash
# 创建新书
python novel_master.py create "书名: 都市超能 题材: 都市异能"

# 创作章节
python novel_master.py write 1

# 批量创作
python novel_master.py batch-write 1 10

# 查看状态
python novel_master.py status

# 黄金三章审核
python novel_master.py audit
```

### 3. API 调用

```bash
# 启动 API 服务
python -c "from app import main; main()"

# 创建书籍
curl -X POST http://localhost:13567/api/books \
  -H "Content-Type: application/json" \
  -d '{"brief": "书名: 测试小说\n题材: 都市\n"}'

# 创作章节
curl -X POST http://localhost:13567/api/chapters/write \
  -H "Content-Type: application/json" \
  -d '{"chapter_num": 1}'
```

## 项目结构

```
novelmaster/
├── app.py                 # WebUI 入口
├── novel_master.py        # 工作流引擎 & CLI
├── requirements.txt       # 依赖
├── .env.example          # 环境变量模板
│
├── api/                   # API 路由
│   ├── routes.py
│   └── task_manager.py
│
├── core/                  # 核心模块
│   ├── novel_engine.py    # 引擎实现
│   ├── models.py          # 数据模型
│   └── llm_service.py     # LLM 服务
│
├── web/                   # 前端资源
│   ├── index.html
│   └── static/
│
└── workspace/             # 工作目录 (数据存储)
    └── books/
        └── {book_id}/    # 书籍文件夹 (ID: 字母+数字)
            ├── story_bible.md      # 世界观设定
            ├── book_rules.md       # 创作规则
            ├── chapter_outline.md  # 章节大纲
            ├── planning.md         # 规划书
            ├── project_state.json  # 项目状态
            ├── chapters/           # 章节正文
            │   └── chapter_*.md
            └── truth_files/        # 真相文件
                ├── current_state.md      # 世界状态
                ├── particle_ledger.md    # 资源账本
                ├── pending_hooks.md      # 伏笔总表
                ├── character_matrix.md    # 角色矩阵
                ├── emotional_arcs.md     # 情感弧线
                ├── subplot_board.md      # 支线进度
                └── chapter_summaries.md  # 章节摘要
```

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

## 评分机制

章节综合分 = 100 - auditIssues×5 - aiTellDensity×20 - paraWarnings×3

| 分数  | 决策          |
| ----- | ------------- |
| ≥75  | 通过          |
| 60-74 | 修订后通过    |
| <60   | 不通过 (重写) |

单章重写上限 3 次，超过后暂停等待人工介入。

## 章节状态流转

```
draft → reviewing → approved → final
         ↑____________↓ (评分<75时退回)
```

## License

MIT License
