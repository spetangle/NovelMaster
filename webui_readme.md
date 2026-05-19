# NovelMaster WebUI

一个独立的小说创作系统Web界面，基于多Agent协作工作流。

## 项目结构

```
novelmaster/
├── core/                    # 核心模块（独立可调用）
│   ├── __init__.py
│   ├── novel_engine.py      # 核心引擎
│   ├── llm_service.py      # LLM服务
│   └── models.py            # 数据模型
├── api/                     # API服务
│   ├── __init__.py
│   └── routes.py            # 路由定义
├── web/                     # 前端界面
│   ├── index.html           # 主页面
│   ├── static/
│   │   ├── css/style.css
│   │   └── js/app.js
│   └── templates/
├── app.py                   # 应用入口
└── requirements.txt
```

## 安装

```bash
pip install flask
```

## 运行

```bash
python app.py
```

访问 http://localhost:5000

## 核心模块调用示例

```python
from core.novel_engine import NovelEngine

engine = NovelEngine(workspace="./workspace")
result = engine.create_book_workflow("书名: 斗破苍穹\n题材: 玄幻")
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| WORKSPACE | ./workspace | 工作目录 |
| FLASK_DEBUG | false | 调试模式 |
| FLASK_HOST | 0.0.0.0 | 监听地址 |
| FLASK_PORT | 5000 | 监听端口 |

## API接口

### 书籍管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/books | 列出所有书籍 |
| POST | /api/books | 创建新书 |
| GET | /api/books/current | 获取当前书籍 |
| POST | /api/books/current | 切换当前书籍 |

### 章节创作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/chapters/write | 创作章节 |
| GET | /api/chapters/:num | 获取章节内容 |
| POST | /api/chapters/batch-write | 批量创作 |

### 真相文件

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/truth-files | 获取所有真相文件 |
| PUT | /api/truth-files/:name | 更新真相文件 |

### LLM配置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/llm/config | 获取LLM配置 |
| PUT | /api/llm/config | 更新LLM配置 |
| POST | /api/llm/test | 测试连接 |
