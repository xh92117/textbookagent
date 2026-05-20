# TextBookAgent 智能教材编制系统

TextBookAgent 是一个面向教材、讲义、课程资料与专业知识内容生产的智能体系统。它基于大语言模型、Agent Skill、知识库检索、长任务管线、记忆系统和文档导出能力，支持从“一个教材需求”逐步生成大纲、章节、审查报告、图表、插图和 Word 文档。

当前版本定位为本地优先的智能教材编制工作台，适合个人研究、教学材料准备、课程开发、教材草稿生成和智能体编写流程验证。

## 核心功能

### 1. AI 对话与智能体工具调用

- 支持 Web 页面中的 AI 对话。
- 支持流式输出。
- 支持工具调用过程展示。
- 支持长期任务中的 Todo/步骤状态展示。
- 支持会话历史持久化。
- 支持进程级记忆记录，方便后续恢复“之前做过什么”。

### 2. 教材项目管理

- 新建、查看、编辑、删除教材项目。
- 配置教材标题、学科、目标读者、难度、章节数量、章节字数和写作风格。
- 查看教材整体进度。
- 管理章节内容。
- 查看教材详情和章节预览。

### 3. 教材编制管线

系统内置教材编制流程，可自动执行：

1. 生成教材大纲。
2. 审查教材大纲。
3. 组织全书上下文。
4. 逐章编写章节内容。
5. 逐章审查章节质量。
6. 按需修订和润色。
7. 持久化章节状态并生成可导出的文档。

管线执行过程中会写入状态文件，记录当前章节、当前阶段、完成章节数量和最近运行状态。

### 4. 子智能体体系

项目包含多个面向教材编制场景的子智能体：

- `OutlinerAgent`：生成教材大纲。
- `ComposerAgent`：组织章节上下文。
- `WriterAgent`：编写章节正文。
- `ReviewerAgent`：审查大纲和章节。
- `ReviserAgent`：根据审查意见修订内容。
- `PolisherAgent`：统一风格并润色文本。

这些子智能体由后端管线调度，也可通过 Agent Skill 的方式被智能体理解和调用。

### 5. Agent Skill

项目内置多个技能目录：

- `skills/outline`：教材大纲生成。
- `skills/chapter`：章节编写。
- `skills/review`：教材审查。
- `skills/fullbook`：整本教材编制。
- `skills/wordgen`：Word 文档生成。
- `skills/sandbox`：图表与代码沙盒。
- `skills/imagegen`：图片生成提示词与插图生成。
- `skills/knowledge_organizer`：知识库整理。
- `skills/multi-search-engine`：多搜索引擎技能。

技能以 `SKILL.md` 描述能力、输入、输出和执行约束。

### 6. 知识库与 LLM-WIKI 整理

知识库用于让教材编写过程检索用户上传的论文、文档、资料和图片资产。

当前知识库支持：

- 上传 PDF、Markdown、TXT、CSV、JSON、Word 等文件。
- 按章节和 token 上限进行分块。
- 为分块生成标题、摘要、关键词、使用场景和相关实体。
- 提取表格并尽量转换为 Markdown。
- 提取公式并尽量保留 LaTeX 形式。
- 提取 PDF 图片并保存为独立图片资产。
- 构建 LLM-WIKI 风格索引。
- 构建实体和关系图谱。
- 支持增量整理，只处理未整理或已变更的文件。
- 预留 embedding 和向量检索结构。

当前检索策略以元数据、BM25 和图谱扩展为主，embedding 向量库属于后续商业化增强方向。

### 7. 图表与插图生成

系统支持教材内容中的图表和插图需求：

- 图表类内容优先使用代码和数据生成。
- 可使用沙盒执行 Python 代码生成图表。
- 支持折线图、柱状图、饼图、散点图、雷达图、网络图等。
- 可检索知识库中的图片资产。
- 可调用配置的图片生成模型生成概念插图。
- 生成的图片可插入章节 Markdown，并在导出 Word 时处理。

### 8. Word 文档导出

支持将教材章节导出为 Word 文档。

当前包括：

- Markdown 到 Word 转换。
- 标题、段落、列表、代码块、图片处理。
- 多种文档模板。
- 可导出整本教材或指定章节。

### 9. 模型配置

系统支持多个 OpenAI-compatible 模型供应商。

当前配置分为：

- AI 对话模型。
- 教材审核模型。
- 图片生成模型。
- 知识库整理模型。

模型配置可包含：

- 模型显示名称。
- 供应商。
- 模型名。
- API Base。
- API Key。

审核模型、图片模型和知识库整理模型可从已配置的 AI 模型中选择。

### 10. 记忆系统

当前记忆系统包括：

- 进程级记忆：一次用户请求从开始到结束的过程记录。
- 会话历史：AI 对话消息持久化。
- 用户画像：记录用户偏好、目标、项目关注点。
- 记忆查询 API：统一查询画像、进程记忆和会话历史。
- 定期压缩与长期记忆预留。

记忆系统的目标是在后续会话中恢复上下文，同时控制进入模型的上下文长度。

## 项目结构

```text
TextBookAgent/
  agent/
    chat/                  # AI 对话服务
    knowledge/             # 知识库整理与检索
    memory/                # 记忆、会话、用户画像
    protocol/              # Agent 执行协议
    skills/                # Skill 加载与管理
    textbook/              # 教材智能体核心
      agents/              # Outliner、Writer、Reviewer 等子智能体
      docgen/              # Word 文档生成
      models/              # 教材、章节、大纲等数据模型
      pipeline/            # 教材编制管线
      prompts/             # 提示词模板
      sandbox/             # 图表和沙盒执行
      state/               # 教材状态与真相文件
    tools/                 # read/write/bash/web_search/browser 等工具
  bridge/                  # Web 与智能体/教材后端桥接
  channel/web/             # Web API 与前端页面
  common/                  # 公共工具
  models/                  # 各模型供应商适配
  plugins/                 # TextbookAgent 插件
  skills/                  # Agent Skill 文档和脚本
  tests/                   # 自动化测试
  app.py                   # 启动入口
  config-template.json     # 配置模板
  requirements.txt         # Python 依赖
```

## 环境要求

- Python 3.10 或更高版本。
- Windows、macOS、Linux 均可运行，当前开发和测试主要在 Windows 环境。
- 可访问所配置的大模型 API。

## 安装依赖

```bash
pip install -r requirements.txt
```

如果需要处理 PDF 图片抽取，请确认已安装：

```bash
pip install PyMuPDF
```

项目的 `requirements.txt` 已包含常用依赖。

## 配置模型

复制或编辑 `config.json`。

最小配置示例：

```json
{
  "channel_type": "web",
  "web_console": true,
  "agent": true,
  "model": "your-chat-model",
  "bot_type": "custom",
  "custom_api_key": "your-api-key",
  "custom_api_base": "https://your-openai-compatible-endpoint/v1"
}
```

多模型配置示例：

```json
{
  "ai_chat_models": [
    {
      "id": "chat_model_1",
      "name": "主对话模型",
      "provider": "custom",
      "model": "your-chat-model",
      "api_base": "https://your-openai-compatible-endpoint/v1"
    }
  ],
  "active_chat_model_id": "chat_model_1",
  "review_model_id": "chat_model_1",
  "image_model_id": "chat_model_1",
  "knowledge_model_id": "chat_model_1"
}
```

注意：

- 不建议将真实 API Key 提交到代码仓库。
- 当前 `.gitignore` 已忽略 `config.json`。
- 商业化版本建议使用系统密钥库或环境变量管理 API Key。

## 启动系统

```bash
python app.py
```

默认访问地址：

```text
http://localhost:9899/textbook
```

普通聊天页面：

```text
http://localhost:9899/chat
```

如果配置了 `web_password`，访问时需要登录。

## 使用方式

### 方式一：教材工作台

1. 启动服务。
2. 打开 `http://localhost:9899/textbook`。
3. 在工作台中新建教材。
4. 配置教材基本信息。
5. 进入教材详情页。
6. 上传知识库资料。
7. 点击 AI 整理知识库。
8. 在 AI 对话中要求智能体编写某一章，或启动完整教材管线。
9. 查看章节内容、审查结果、图表和插图。
10. 导出 Word 文档。

### 方式二：AI 对话驱动

可以直接在 AI 对话中输入：

```text
请为《土木工程智能体开发设计实务》编写第十四章内容。
```

或者：

```text
请根据当前知识库，生成本教材的大纲。
```

智能体会根据上下文、教材状态、知识库和可用工具决定执行路径。

### 方式三：API 调用

创建教材：

```bash
curl -X POST http://localhost:9899/api/textbook ^
  -H "Content-Type: application/json" ^
  -d "{\"title\":\"数据结构\",\"subject\":\"计算机科学\",\"target_audience\":\"本科生\",\"total_chapters\":10}"
```

启动教材管线：

```bash
curl -X POST http://localhost:9899/api/textbook/{book_id}/pipeline
```

查询管线状态：

```bash
curl http://localhost:9899/api/textbook/{book_id}/pipeline
```

导出 Word：

```bash
curl http://localhost:9899/api/textbook/{book_id}/export?template=academic
```

查询记忆：

```bash
curl "http://localhost:9899/api/memory/query?session_id=your_session_id"
```

## 知识库使用流程

1. 在教材工作台进入知识库管理。
2. 上传论文、PDF、Markdown、Word 或其他资料。
3. 点击 AI 整理。
4. 系统会增量处理未整理或已变更文件。
5. 整理完成后，系统会生成 LLM-WIKI 索引、分块摘要、使用场景、实体关系和图片资产索引。
6. 编写章节时，智能体会检索相关分块并作为证据包注入上下文。

知识库整理结果通常位于工作空间下：

```text
knowledge/{book_id}/_llm_wiki/
```

## 教材状态文件

每本教材会维护状态文件，用于恢复和观察生成进度：

```text
textbooks/{book_id}/state/status.json
```

状态中包含：

- 总章节数。
- 当前章节。
- 当前阶段。
- 已完成章节。
- 运行状态。
- 更新时间。

## 测试

运行全部测试：

```bash
python -m pytest tests -q
```

当前代码库包含教材 API、管线、状态、记忆、知识库、模型配置、文档生成等多类测试。

## 当前限制

当前版本仍有一些商业化前需要继续增强的内容：

- Web 前端仍是单体页面，后续计划封装为桌面客户端。
- 工作区和系统区尚未完全拆分。
- 知识库 embedding 和向量数据库为预留结构，尚未完全启用。
- Web 图片搜索默认禁用，避免版权和合规风险。
- 长任务仍需要进一步改造为持久任务系统。
- 配置和密钥治理需要继续增强。
- 前端文案、交互和商业化体验仍在改造中。

详细商业化改造计划见：

```text
商业应用改造计划.md
```

## 开发建议

- 修改代码后运行 `python -m pytest tests -q`。
- 不要提交 `config.json`、日志、缓存、本地用户数据和工作区内容。
- 大模型 API Key 建议使用环境变量或本地私有配置。
- 新增长期任务时，优先设计可恢复状态和进度事件。
- 新增知识库能力时，优先控制上下文长度和模型请求次数。

## 许可证

当前仓库尚未声明正式开源许可证。商业发布或公开分发前，请补充许可证、第三方依赖声明和素材版权说明。
