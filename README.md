# TextBookAgent 智能教材编制系统

<p align="right">
  <a href="README_EN.md">English</a> | <strong>中文</strong>
</p>

TextBookAgent 是一个面向教材、讲义、课程资料和专业知识内容生产的智能体系统。它将大语言模型、教材编制管线、知识库检索、Agent Skill、记忆系统、图表/插图生成和 Word 导出组合成一个本地优先的教材工作台。

项目目标不是做一个通用聊天机器人，而是让用户围绕“创建一本教材”完成从资料整理、大纲规划、章节写作、质量审查、修订润色到文档导出的完整流程。

## 项目来源与致谢

本项目源于并参考了以下两个优秀的智能体项目，在此特别致谢：

- [chatgpt-on-wechat](https://github.com/zhayujie/chatgpt-on-wechat)：提供了多渠道机器人、插件体系、模型适配、基础 Web 控制台等重要工程基础。TextBookAgent 在此基础上重构并扩展了教材工作台、知识库、长任务管线和教材专用智能体能力。
- [AgentMesh](https://github.com/MinimalFuture/AgentMesh)：为多智能体协作、任务分发和工具调用型 Agent 设计提供了参考。项目中的部分 Agent 插件设计继承了其多智能体协作思路。

同时感谢相关开源生态中的模型服务 SDK、Web 框架、文档生成、图表生成、PDF 解析和测试工具项目。

## 核心能力

### 教材项目管理

- 新建、查看、编辑、删除教材项目。
- 配置教材标题、学科、目标读者、难度、章节数量、章节字数和写作风格。
- 查看教材进度、章节状态、章节内容和导出结果。
- 每本教材维护独立状态文件，支持中断后的恢复和进度追踪。

### 多智能体教材编制管线

系统内置面向教材生产的子智能体和长任务流程：

- `OutlinerAgent`：生成教材大纲。
- `ComposerAgent`：组织全书和章节上下文。
- `WriterAgent`：编写章节正文。
- `ReviewerAgent`：审查大纲和章节质量。
- `ReviserAgent`：根据审查意见修订内容。
- `PolisherAgent`：统一语言风格并润色文本。

管线可执行以下流程：

1. 生成教材大纲。
2. 审查教材大纲。
3. 组织全书上下文。
4. 逐章编写教材内容。
5. 检索并注入知识库证据。
6. 路由图表、插图和知识库图片资产。
7. 审查章节质量。
8. 按需修订和润色。
9. 持久化章节、状态和检查点。
10. 导出 Word 文档。

### 知识库与 LLM-WIKI 整理

知识库用于管理用户上传的论文、PDF、Word、Markdown、TXT、CSV、JSON 和图片资产，并在写作时提供证据包。

当前支持：

- 增量整理资料，只处理新增或变更文件。
- 按章节、标题和上下文长度进行分块。
- 为分块生成标题、摘要、关键词、使用场景和相关实体。
- 提取 PDF 中的图片资产。
- 提取表格并转换为 Markdown。
- 尽量保留公式和 LaTeX 表达。
- 构建 LLM-WIKI 风格索引。
- 构建实体关系图谱。
- 通过元数据、BM25 和图谱扩展进行检索。
- 预留 embedding 和向量检索扩展接口。
- 支持 MinerU 配置，用于增强 PDF、公式、表格和 OCR 解析。

### 图表、插图与视觉资产

- 教材图表优先使用代码和结构化数据生成。
- 支持通过沙盒执行 Python 生成折线图、柱状图、饼图、散点图、雷达图、网络图等。
- 支持检索知识库中的已有图片资产。
- 支持调用配置的图片生成模型生成概念插图。
- 自动过滤过小、疑似 Logo 或水印类图片资产。
- 生成的图片可插入章节 Markdown，并在 Word 导出时处理。

### Agent Skill

项目内置多个教材相关技能：

- `skills/outline`：教材大纲生成。
- `skills/chapter`：章节编写。
- `skills/review`：教材审查。
- `skills/fullbook`：整本教材编制。
- `skills/wordgen`：Word 文档生成。
- `skills/sandbox`：图表与代码沙盒。
- `skills/imagegen`：插图生成提示词与图片生成。
- `skills/knowledge_organizer`：知识库整理。
- `skills/multi-search-engine`：多搜索引擎资料检索。

技能通过 `SKILL.md` 描述能力、输入、输出和执行约束，供智能体按需调用。

### Web 工作台

- `/textbook`：教材工作台。
- `/chat`：AI 对话页面。
- 支持流式输出、工具调用展示、任务步骤展示和会话历史。
- 支持知识库上传、整理、检索和章节写作。
- 默认绑定 `127.0.0.1`。如绑定公网地址，建议配置 `web_password`。
- 当 `web_require_password_on_public_host` 为 `true` 时，未设置密码的公网 Web 控制台会拒绝启动。

### 模型配置

支持多个 OpenAI-compatible 模型供应商，并可按角色分别配置：

- AI 对话模型。
- 教材审核模型。
- 图片生成模型。
- 知识库整理模型。

支持 DeepSeek、OpenAI-compatible、自定义 API Base、Qianfan、DashScope、Moonshot、Claude、Gemini、Zhipu、Minimax 等模型配置方式。实际可用性取决于本地配置和对应服务商 API。

### 记忆系统

- 会话历史持久化。
- 进程级任务记忆。
- 用户偏好和项目关注点记录。
- 记忆查询 API。
- 长会话压缩与上下文预算控制。

#### 记忆保存规则

记忆系统已经统一为系统级存储，默认目录为：

```text
{system_workspace}/system/memory/
```

教材工作区只保存教材、知识库、导出文件和项目资料，不再作为智能体记忆目录使用。旧版本中可能存在的 `工作区/MEMORY.md` 或 `工作区/memory/*.md` 会在启动时复制到 `system/memory/imported/`，并生成迁移报告：

```text
system/memory/migrations/memory_migration_report.json
```

自动保存记忆：

- 会话过程、长任务过程、错误记录、用户画像等由后端自动写入 `system/memory/`。
- 当智能体使用 `write` 或 `edit` 写入 `MEMORY.md`、`memory/YYYY-MM-DD.md`、`memory/processes/...` 时，路径会自动解析到 `system/memory/`。
- 长会话压缩和 Deep Dream 记忆蒸馏会更新 `system/memory/MEMORY.md` 与每日记忆文件。

手动保存记忆：

- 对智能体说“记住这个”“以后都按这个规则”“不要再这样做”等，智能体会把长期偏好、规则或重要结论写入 `MEMORY.md`。
- 当天进展、阶段性结论、临时上下文可写入 `memory/YYYY-MM-DD.md`。
- 可通过 Web 控制台记忆页面或记忆 API 查询已保存内容。
- 不要把 API key、token、密码等敏感信息写入记忆。

工作区画像文件的自动更新：

- `AGENT.md`、`USER.md`、`RULE.md` 属于工作区画像文件，用于描述智能体工作方式、用户静态画像和工作区规则。
- 用户明确说“写入 USER.md / AGENT.md / RULE.md”“作为工作区规则”“以后你应该……”“我的称呼是……”时，系统会自动追加到对应画像文件。
- 每次自动更新前会在 `.workspace_profile_versions/` 中备份旧文件，并在 `profile_update_log.jsonl` 记录更新时间、来源和原因。
- 与单本教材相关的偏好不会写入这些全局画像文件，应保存在教材详情页的“教材偏好”中，并同步到该教材的 `WritingSpec`。

### MCP 与工具扩展

- 支持内置 read、write、edit、bash、web_fetch、web_search、browser、vision、knowledge_query、knowledge_capture、pipeline 等工具。
- 支持通过 MCP 配置扩展外部工具。
- 工具调用过程可在 Web 页面中展示，便于观察长任务执行过程。

## 项目结构

```text
TextBookAgent/
  agent/
    chat/                  # AI 对话服务
    knowledge/             # 知识库整理、索引与检索
    memory/                # 记忆、会话和用户画像
    protocol/              # Agent 执行协议和流式工具调用
    skills/                # Skill 加载与管理
    textbook/              # 教材智能体核心
      agents/              # Outliner、Writer、Reviewer 等子智能体
      docgen/              # Word 文档生成
      models/              # 教材、章节、大纲等数据模型
      pipeline/            # 教材编制管线
      prompts/             # 教材写作提示词模板
      sandbox/             # 图表和代码沙盒
      state/               # 教材状态与真相文件
    tools/                 # Agent 工具
  bridge/                  # Web、Agent 与教材后端桥接
  channel/web/             # Web API 与前端页面
  common/                  # 公共工具
  models/                  # 模型供应商适配
  plugins/                 # 插件
  skills/                  # Agent Skill 文档和脚本
  tests/                   # 自动化测试
  app.py                   # 启动入口
  config-template.json     # 配置模板
  requirements.txt         # Python 依赖
```

## 环境要求

- Python 3.10 或更高版本。
- Windows、macOS、Linux 均可运行；当前开发和测试主要在 Windows 环境。
- 可访问所配置的大模型 API。
- 如需使用浏览器工具，请安装 Playwright 浏览器运行时。

## 安装

```bash
pip install -r requirements.txt
```

如需使用 Playwright 浏览器能力：

```bash
playwright install chromium
```

## 配置

复制或编辑 `config.json`。仓库提供了 `config-template.json` 作为模板。

最小 Web 教材工作台配置示例：

```json
{
  "channel_type": "web",
  "web_host": "127.0.0.1",
  "web_port": 9899,
  "agent": true,
  "model": "deepseek-v4-flash",
  "bot_type": "deepseek",
  "deepseek_api_key": "your-api-key",
  "deepseek_api_base": "https://api.deepseek.com/v1",
  "knowledge": true
}
```

多角色模型配置示例：

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

- 不要提交真实 `config.json`、API Key、日志、缓存和本地工作区内容。
- `.gitignore` 已忽略 `config.json`、`logs/`、`workspace/`、`node_modules/` 等本地文件。
- 公开部署时请设置 `web_password`，并确认 `web_host`、反向代理和访问控制策略。

## 启动

```bash
python app.py
```

默认访问：

```text
http://localhost:9899/textbook
```

AI 对话页面：

```text
http://localhost:9899/chat
```

## 使用流程

### 教材工作台

1. 启动服务。
2. 打开 `http://localhost:9899/textbook`。
3. 新建教材项目。
4. 配置标题、学科、读者、难度、章节数量和写作风格。
5. 上传论文、文档或图片资料。
6. 点击 AI 整理知识库。
7. 生成或审查教材大纲。
8. 启动完整教材管线，或在对话中要求编写指定章节。
9. 查看章节内容、审查结果、图表和插图。
10. 导出 Word 文档。

### 对话驱动

可以直接在 AI 对话中输入：

```text
请根据当前知识库，生成本教材的大纲。
```

或：

```text
请为《土木工程智能体开发设计实务》编写第十四章内容，并补充图表建议。
```

智能体会根据教材状态、知识库、上下文和可用工具决定执行路径。

### API 示例

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

## 知识库数据位置

知识库整理结果通常位于工作空间下：

```text
knowledge/{book_id}/_llm_wiki/
```

教材状态文件通常位于：

```text
textbooks/{book_id}/state/status.json
```

章节检查点通常位于：

```text
textbooks/{book_id}/state/pipeline_checkpoints/
```

## 测试

运行全部测试：

```bash
python -m pytest tests -q
```

当前测试覆盖教材 API、管线、状态、知识库、记忆、模型配置、文档生成、沙盒、Web 路由和工具调用等模块。

## 开发建议

- 修改代码后运行 `python -m pytest tests -q`。
- 长任务功能应优先支持进度事件、检查点和可恢复状态。
- 知识库功能应优先控制上下文长度、模型请求次数和可解释证据。
- 模型适配应尽量通过统一 registry 和角色配置接入。
- 文档和界面文案应聚焦教材编制，不再扩展与本项目无关的通用机器人说明。

## 英文文档

English documentation is available in [README_EN.md](README_EN.md).

## 许可证

使用 MIT 开源许可协议。
