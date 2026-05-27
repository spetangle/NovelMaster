# InkOS 小说创作系统 - 入口 Skill

> 版本: 1.1.0 | 定位: 多 Agent 协作调度器
> 核心更新: v1.1 → 章节状态流转机制 / 自动完成标记

---

## 触发条件

用户请求进行小说创作时触发，包含但不限于：
- 创作新书 / 新章节
- 修改已有书籍内容
- 查询创作进度
- 其他与小说创作相关的需求

---

## 初始化：获取当前小说（必须执行）

每次涉及小说状态的操作，**必须先执行以下流程获取当前小说**：

1. 读取 `{workspace}/book_index.json`
2. 从 `current_novel` 字段获取项目ID
3. 在 `books` 数组中定位完整项目信息
4. 如需详细状态，读取 `{workspace}/{path}/project_state.json`

**禁止跳过**：严禁在未读取 book_index.json 的情况下直接读取某一项目的 project_state.json。

**参考文档**：`workflow-current-novel.md`

---

## 章节状态流转机制（v1.1 新增）

### 状态定义

每个章节维护独立状态，状态值定义于 `project_state.json` 的 `chapter_status_schema`：

```
draft → reviewing → approved → final
         ↑____________↓ (评分<75时退回draft，进入重写循环)
```

| 状态 | 含义 | 触发条件 |
|------|------|----------|
| `draft` | 草稿完成，等待审核 | 05_writer 完成初稿 |
| `reviewing` | 审核中 | 06_observer 提取完成后 |
| `approved` | 审核通过，待终审 | 09_auditor 评分 ≥ 75 |
| `final` | 已定稿，标记完成 | 08_controller 终审 + 用户确认 |

### 状态更新规则

章节状态变更时，必须同步更新两个文件：

1. **`project_state.json`** → `chapter_planning.chapter_N` 块
   - `approval_status` → 当前状态
   - `audit_score` → 本次评分（如已审核）
   - `audit_passed` → true/false
   - `finalized` → final状态时设为true

2. **`chapter_summaries.md`** → 对应章节条目表格
   - 同步字段值
   - 更新 `最后更新` 时间戳

### 重写循环规则

- 单章重写上限：**3次**
- 每次重写后重新经过 06_observer → 09_auditor 流程
- 3次均未通过（评分<75）→ 暂停流程，输出诊断报告，等待**人工介入**
- 人工介入确认后重置计数，重新开始

### 完成标记规则

章节标记为完成（`finalized = true`）须同时满足：
- `audit_score` ≥ 75
- `approval_status` = "approved"
- 08_controller 终审通过
- **用户明确确认**

完成章节从活跃列表移至 `chapter_summaries.md` 的「定稿章节（final）」区永久存档。

---

## 工作流程

```
用户输入 → 解析意图 → 任务拆解 → 按序调用子 Agent → 结果汇总 → 输出
```

### 阶段一：初始化（新建书籍时）

1. **调用 03_architect** - 生成 `story_bible.md` + `book_rules.md`
2. 初始化 7 个真相文件（含 `chapter_summaries.md`）
3. 分配书籍 ID，建立 `books/{book_id}/` 目录结构
4. **执行新建书籍工作流**：`references/workflow-book-create.md`

### 阶段二：章节创作

```
05_writer 生成正文
        ↓
06_observer 提取关键事实（触发 reviewing）
        ↓
09_auditor 质量审查
        ↓
  ┌──── ┴────┐
  ↓          ↓
通过(≥75)   不通过(<75)
  ↓          ↓
approved   → draft（重写循环）
  ↓
08_controller 终审
  ↓
用户确认 → finalized = true，章节完成
```

### 阶段三：交付

- 输出章节正文
- 更新 7 个真相文件（含状态同步）
- 报告质量审查结果

---

## 真相文件体系

每本书维护 7 个核心真相文件：

| 文件 | 用途 |
|------|------|
| `current_state.md` | 世界状态（位置、情绪、环境） |
| `particle_ledger.md` | 资源账本（物品、金钱、数值） |
| `pending_hooks.md` | 伏笔总表 |
| `chapter_summaries.md` | 各章摘要（含状态标记） |
| `subplot_board.md` | 支线进度板 |
| `emotional_arcs.md` | 情感弧线 |
| `character_matrix.md` | 角色交互矩阵 |

---

## 调用规范

当用户触发创作任务时，先确认以下变量：
1. 书籍 ID 或新建书籍
2. 章节编号
3. 创作指令/意图

变量未锁定时，输出询问而非直接执行。

---

## 评分机制（Quality Evaluation）

每章创作完成后必须进行质量评分，维度如下：

| 维度 | 说明 | 计算方式 |
|------|------|----------|
| **AI痕迹检测** | 检测AI写作特征 | `analyzeAITells()` 检测重复结构/机械感段落 |
| **段落长度检查** | 短段落占比超40%为警告 | 统计<35字的段落比例 |
| **伏笔回收率** | 已回收/总伏笔数 | `resolvedHooks/totalHooks * 100` |
| **章节综合分** | 单章质量分(0-100) | `100 - auditIssues*5 - aiTellDensity*20 - paraWarnings*3` |
| **质量漂移检测** | 前后半段对比 | `后半均分 - 前半均分`，负值为劣化 |

### 评分输出格式

```markdown
# 第 N 章质量报告

## 综合评分
- 章节得分: [X]/100
- 综合得分: [Y]/100

## 维度分析
| 维度 | 数值 | 状态 |
|------|------|------|
| AI痕迹密度 | X /1k chars | [正常/警告] |
| 段落警告 | X 处 | [通过/需修正] |
| 伏笔回收率 | X% | [达标/不足] |
| 审计问题 | X 处 | [通过/需修订] |

## 质量趋势
[前5章分数柱状图]

## 决策建议
[通过/修订后通过/不通过]
```

### 任务启动 Log 规范

每次开始执行生成任务时，必须输出当前任务信息：

```markdown
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[LOG] 开始执行任务
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
任务名称: [具体任务描述]
当前 Agent: [Agent编号-名称]
目标书籍: [book_id]
当前阶段: [阶段名]
预计产出: [文件名/内容描述]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 状态相关 Agent 协作约定

| Agent | 状态职责 |
|-------|----------|
| **05_writer** | 完成后将 `approval_status` 设为 `draft`，同步更新 `project_state.json` 与 `chapter_summaries.md` |
| **06_observer** | 提取完成后将 `approval_status` 设为 `reviewing` |
| **09_auditor** | 审查后更新 `approval_status`（approved/draft）、`audit_score`、`audit_passed` |
| **08_controller** | 终审通过后标记 `finalized = true` |
| **11_global_editor** | 全局修正执行，完成后同步状态至 chapter_summaries.md |
| **Orchestrator（本 Skill）** | 全局协调，确保状态流转不跳步 |
