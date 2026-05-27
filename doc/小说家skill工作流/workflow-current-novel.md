# 工作流：获取当前小说

**编号**：workflow-current-novel  
**版本**：1.0  
**制定日期**：2026-05-13  
**适用范围**：所有涉及当前小说状态的操作  

---

## 核心原则

每次询问"当前小说"或需要加载小说状态时，**必须按以下顺序执行**。

---

## 操作步骤

### 第一步：读取 book_index.json

读取根目录下的 `book_index.json` 文件。

**文件位置**：`{workspace}/book_index.json`

**输出字段**：
```json
{
  "current_novel": "项目ID",
  "books": [ ... ]
}
```

### 第二步：从 current_novel 获取项目ID

从 `current_novel` 字段提取当前小说ID。

**示例**：
```
current_novel: "chao_neng_fu_shu"
```

### 第三步：在 books 数组中定位完整信息

在 `books` 数组中查找 `id` 字段等于 `current_novel` 的对象，获取完整项目信息。

**示例**：
```json
{
  "id": "chao_neng_fu_shu",
  "name": "超能复苏",
  "path": "books/超能复苏",
  "genre": "都市异能",
  "platform": "番茄小说",
  "words_per_chapter": 3000,
  "total_chapters": 80,
  "completed_chapters": 2,
  "status": "进行中"
}
```

### 第四步：读取项目级状态文件（如需详情）

如需章节评分、伏笔追踪等详细状态，读取对应项目的 `project_state.json`。

**文件路径**：`{workspace}/{path}/project_state.json`

**示例**：
```
{workspace}/books/超能复苏/project_state.json
```

---

## 数据层级说明

| 层级 | 文件 | 作用域 |
|------|------|--------|
| 全局索引 | book_index.json | 多本小说并行管理 |
| 项目状态 | project_state.json | 单本小说进度与评分 |
| 章节文件 | 正文/*.md | 单章内容 |

---

## 注意事项

1. **禁止跳过第一步**：严禁在未读取 book_index.json 的情况下，直接读取某一项目的 project_state.json
2. **禁止依赖记忆**：每次操作前必须重新读取 book_index.json 获取 current_novel
3. **变量校验**：读取 project_state.json 后，需与 book_index.json 中的项目信息交叉验证

---

## 快速查询指令

```bash
# 读取全局索引
cat {workspace}/book_index.json

# 获取 current_novel
grep -o '"current_novel": "[^"]*"' {workspace}/book_index.json
```

---

**执行要点**：book_index.json → current_novel → 定位 books[] → 读取 project_state.json