# InkOS 业务逻辑文档

> 版本: 1.0 | 来源: InkOS 代码库分析 | 整理日期: 2026-05-12

---

## 一、InkOS 系统概述

### 1.1 系统定位

InkOS 是一款基于 Node.js 的多 Agent 小说创作系统，通过多个专业 Agent 的协作实现自动化的长篇小说创作流程。

### 1.2 核心架构

```
┌─────────────────────────────────────┐
│           InkOS Core               │
│  ┌─────────────────────────────┐   │
│  │     Multi-Agent Pipeline    │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐  │   │
│  │  │Radar│→│Plan │→│Arch │  │   │
│  │  └─────┘ └─────┘ └─────┘  │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐  │   │
│  │  │Comp │→│Write│→│Obser│  │   │
│  │  └─────┘ └─────┘ └─────┘  │   │
│  │  ┌─────┐ ┌─────┐ ┌─────┐  │   │
│  │  │Refl │→│Audi │→│Ctrl │  │   │
│  │  └─────┘ └─────┘ └─────┘  │   │
│  └─────────────────────────────┘   │
│  ┌─────────────────────────────┐   │
│  │   World State Manager       │   │
│  │  - story_bible              │   │
│  │  - chapter_summaries        │   │
│  │  - hook_manager             │   │
│  │  - project_state            │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

### 1.3 版本信息

- 当前版本: 1.3.10
- 安装路径: `/home/admin/.local/lib/node_modules/@actalk/inkos`
- 依赖: Node.js v20+

---

## 二、Agent 管线详解（10 Agent）

### 2.1 Agent 01 - Radar（市场调研）

**职能:** 扫描小说市场趋势，为创作决策提供数据支撑。

**输入:** 用户创作需求（可选）

**输出:** 市场调研报告（题材热度、流行元素、平台适配）

**调用时机:** 新书创建前（可选）

---

### 2.2 Agent 02 - Planner（规划师）

**职能:** 制定全书规划与章节计划。

**输入:** 创作简报 / story_bible.md

**输出:** 全书规划书 / 章节计划

**关键逻辑:**
- 识别用户需求中的题材类型
- 调用对应题材规则集
- 生成章节大纲

---

### 2.3 Agent 03 - Architect（建筑师）

**职能:** 设计完整的小说世界观与章节结构。

**输入:** 创作简报 / 章节计划

**输出:**
- 模式A: `story_bible.md` + `book_rules.md`
- 模式B: 章节细纲

**核心输出物:**

| 文件 | 用途 |
|------|------|
| story_bible.md | 世界观、人物、势力、地理、时间线设定 |
| book_rules.md | 创作规则、禁止事项、文风要求 |
| chapter_outline.md | 章节起承转合结构 |

---

### 2.4 Agent 04 - Compiler（编译师）

**职能:** 编译与管理创作规则集。

**输入:** Architect 输出的规则文档

**输出:** 结构化的规则索引（供 Writer 快速调用）

**规则类型:**
- 题材规则（玄幻/仙侠/都市/科幻）
- 爽点节奏规则
- 战力系统规则
- 禁止规则

---

### 2.5 Agent 05 - Writer（执笔者）

**职能:** 执行章节正文创作。

**输入:**
- 章节细纲（来自 Architect）
- 角色设定（来自 story_bible）
- 上文剧情（来自 chapter_summaries）
- 伏笔任务（来自 hook_manager）

**输出:** 章节正文（`chapter_content.md`）

**关键逻辑:**
- 按细纲结构执笔
- 埋设指定伏笔
- 回应指定悬念
- 控制字数节奏

---

### 2.6 Agent 06 - Observer（观察者）

**职能:** 章节初审，识别表层问题。

**审核维度:**
- 错别字、病句
- 格式规范
- 基础逻辑（时间、地点是否矛盾）

**输出:** 观察报告 + 问题列表

---

### 2.7 Agent 07 - Reflector（反思者）

**职能:** 章节深度反思，识别深层问题。

**审核维度:**
- 逻辑一致性（情节推进是否合理）
- 角色行为动机（是否 OOC）
- 信息节奏（密度是否适当）
- 情感节奏（张力是否到位）

**评分标准:**

| 维度 | 分值 |
|------|------|
| 逻辑性 | 25分 |
| 角色塑造 | 25分 |
| 节奏把控 | 25分 |
| 伏笔管理 | 25分 |
| **总分** | **100分** |

**判定:** 总分 ≥ 75 → 通过；总分 < 75 → 退回重写

---

### 2.8 Agent 08 - Controller（终审）

**职能:** 最终审核，拥有最终裁量权。

**审核清单:**
- 政治敏感内容检测
- 色情/血腥过度描写检测
- 抄袭/融梗检测
- 错别字/病句抽检
- 章节结尾钩子检查

**判定:** 全部通过 → 终审通过；存在问题 → 退回

---

### 2.9 Agent 09 - Auditor（审计员）

**职能:** 章节质量审计，辅助 Controller 决策。

**审核维度:**
- 战力系统一致性（玄幻/仙侠题材）
- 能力使用衰减计算
- 规则体系执行检查

**输出:** 审计报告 + 评分

---

### 2.10 Agent 10 - Continuity Auditor（伏笔审计）

**职能:** 伏笔连续性管理。

**任务:**
1. 追踪伏笔池状态
2. 核对伏笔回收节点
3. 识别伏笔冲突
4. 标记逾期伏笔

**伏笔状态:**
- 待回收
- 部分回收
- 已回收
- 逾期

---

## 三、核心工作流

### 3.1 book create 工作流

```
[用户] 提供创作简报
    │
    ▼
[Agent 01] Radar 市场调研（可选）
    │
    ▼
[Agent 03] Architect 识别题材，调用规则集
    │
    ▼
[Agent 03] 输出 story_bible.md + book_rules.md
    │
    ▼
[Agent 02] Planner 制定全书写纲
    │
    ▼
[Agent 10] Continuity Auditor 初始化伏笔池
    │
    ▼
[Agent 05] Writer 开始第一章创作
    │
    ▼
[Agent 06] Observer 初审
    │
    ▼
[Agent 07] Reflector 深度反思
    │
    ▼
[Agent 09] Auditor 质量审计
    │
    ▼
[Agent 08] Controller 终审
    │
    ▼
终审通过 → 状态 final → 发布
```

---

### 3.2 write next 工作流

```
[Agent 02] Planner 加载当前章节号，读取上文
    │
    ▼
[Agent 03] Architect 生成章节细纲
    │
    ▼
[Agent 10] Continuity Auditor 加载伏笔池，分配回收任务
    │
    ▼
[Agent 05] Writer 基于细纲+伏笔任务创作正文
    │
    ▼
[Agent 06] Observer 初审
    │
    ▼
[Agent 07] Reflector 深度反思
    │
    ▼
[Agent 09] Auditor 质量审计
    │
    ▼
[Agent 08] Controller 终审
    │
    ▼
通过 → 发布 | 失败 → 退回重写（最多3次）
```

---

## 四、世界状态管理

### 4.1 状态文件结构

```
books/
└── {book_id}/
    ├── meta.json              # 书籍元数据
    ├── story_bible.md         # 世界观设定
    ├── book_rules.md          # 创作规则
    ├── outline.md             # 全书大纲
    ├── hook_manager/
    │   ├── config.json        # 伏笔配置
    │   └── records.md         # 伏笔记录
    ├── chapters/
    │   ├── ch01/
    │   │   ├── meta.json      # 章节元数据
    │   │   ├── outline.md     # 章节细纲
    │   │   └── content.md    # 章节正文
    │   └── ...
    └── summaries/
        └── chapter_summaries.md  # 章节摘要汇总
```

### 4.2 project_state.json 字段

```json
{
  "current_book_id": "string",
  "current_chapter": "number",
  "chapter_status": "draft|reviewing|approved|final",
  "last_agent": "string",
  "auto_rewrite_count": "number",
  "last_update": "ISO datetime"
}
```

### 4.3 章节状态链

```
draft → reviewing → approved → final
         ↓            ↓
      [重写]       [终审失败]
         ↓            ↓
       draft         draft
```

---

## 五、7 真相文件

| 编号 | 文件名 | 用途 | 关键内容 |
|------|--------|------|----------|
| 1 | story_bible.md | 世界观设定 | 背景、人物、势力、地理 |
| 2 | book_rules.md | 创作规则 | 题材规则、禁止事项 |
| 3 | outline.md | 全书大纲 | 章节规划、主线走向 |
| 4 | chapter_outline.md | 章节细纲 | 起承转合、情节点 |
| 5 | hook_manager/records.md | 伏笔记录 | 伏笔池、回收状态 |
| 6 | chapter_summaries.md | 章节摘要 | 剧情概要、关键信息 |
| 7 | project_state.json | 项目状态 | 当前章节、审核状态 |

---

## 六、33 维审计体系

### 6.1 Observer 维度（10维）

1. 错别字检测
2. 病句检测
3. 标点规范
4. 格式规范
5. 称呼一致性
6. 时间线一致性
7. 地点一致性
8. 视角一致性
9. 人称一致性
10. 段落连贯性

### 6.2 Reflector 维度（10维）

1. 逻辑合理性
2. 情节推进逻辑
3. 角色行为动机
4. 角色语言风格
5. 决策合理性
6. 信息密度
7. 情感节奏
8. 冲突张力
9. 伏笔埋设
10. 悬念设置

### 6.3 Auditor 维度（8维）

1. 战力数值一致性
2. 战力提升节奏
3. 能力使用衰减
4. 规则体系执行
5. 禁止规则遵守
6. 金手指使用合理性
7. 资源消耗合理性
8. 因果逻辑一致性

### 6.4 Controller 维度（5维）

1. 政治敏感内容
2. 色情/血腥过度
3. 抄袭/融梗
4. 错别字/病句抽检
5. 章节钩子检查

---

## 七、InkOS 与「小说家」skill 的能力映射

| InkOS 功能 | 「小说家」skill 覆盖方式 | 差异说明 |
|------------|--------------------------|----------|
| 10 Agent 协作 | 各 Agent 独立 AGENT.md | InkOS 自动调度，skill 需手动触发 |
| 规则集编译 | references/类型系统_题材规则集.md | 功能覆盖，手动调用 |
| 工作流自动化 | workflow 文档 + 状态管理 | InkOS 自动 Pipeline，skill 需人工确认 |
| 33 维审计 | 各 Agent AGENT.md 内置审核逻辑 | 功能覆盖，执行方式不同 |
| 7 真相文件 | books/{book_id}/ 目录结构 | 功能覆盖，格式略有差异 |
| 伏笔管理 | 09_hook_manager + 10_continuity_auditor | 功能覆盖，实现方式不同 |
| 超时控制 | 上下文量控制（本项目已解决） | 根因已修复 |

---

## 八、超时问题根因分析（已解决）

### 8.1 问题现象

`book create` 命令执行时，首次 LLM 调用超时。

### 8.2 根因定位

首次 LLM 调用加载了 5 份大型文档 + Foundation Review 重试，导致上下文量过大。

### 8.3 解决方案

- 文档分批加载，避免单次调用加载全部上下文
- Foundation Review 流程优化，减少重试次数
- 上下文量监控，超阈值时主动拆分

---

*文档版本: 1.0 | 整理日期: 2026-05-12 | 来源: InkOS 代码库分析*