# TextBookAgent 智能教材编制系统

<p align="right">
  <strong>中文</strong> | <a href="README_EN.md">English</a>
</p>

TextBookAgent 是一个面向教材、讲义、课程资料和专业知识文档生产的本地优先 Agent 工作台。它围绕“创建一本教材”的完整流程设计，集成大语言模型、知识库整理、教材编制管线、Agent Skills、记忆系统、图表/插图生成和 Word 导出。

## 核心功能

- 教材项目管理：创建教材、维护配置、查看章节状态和生成进度。
- 教材编制管线：支持大纲生成、章节写作、质量审查、修订、润色和持久化。
- 知识库：上传 PDF、Word、Markdown、TXT、CSV、JSON 和图片资料，整理为可检索证据。
- 多智能体协作：内置 Outliner、Writer、Reviewer、Reviser、Polisher 等教材专用子智能体。
- Agent Skills：提供大纲、章节、审查、整书、Word 导出、沙盒图表、插图和多搜索引擎等技能。
- 工具系统：支持 read/write/edit/bash/web_fetch/browser/vision/knowledge_query/textbook_chapter 等内置工具，并支持 MCP 扩展。
- Web 工作台：提供 `/textbook` 教材工作台和 `/chat` 对话页面。
- 导出能力：支持将教材章节和图片资产导出为 Word 文档。

## 环境要求

- Python 3.10+
- 可访问已配置的大语言模型 API
- 如需浏览器工具，需安装 Playwright Chromium

## 安装

建议使用项目本地虚拟环境，避免依赖污染系统 Python。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果 PowerShell 阻止激活脚本，可执行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 浏览器工具

```bash
python -m playwright install chromium
```

## 配置

复制或编辑 `config.json`，可参考 `config-template.json`。

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

注意：

- 不要提交真实 `config.json`、API Key、日志、缓存或本地工作区内容。
- 默认 Web 地址建议绑定 `127.0.0.1`。
- 如需公网访问，请设置 `web_password` 并检查反向代理和访问控制。

## 启动

先激活虚拟环境，再启动服务：

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

访问：

```text
http://localhost:9899/textbook
http://localhost:9899/chat
```

## 常用目录

```text
agent/       Agent、工具、记忆、知识库和教材编制核心逻辑
bridge/      Web 与 Agent 服务桥接
channel/     Web 页面、API 路由和静态资源
models/      模型适配器
plugins/     插件系统
skills/      教材相关 Agent Skills
tests/       自动化测试
```

## 测试

```bash
pytest -q
```

## 说明

项目继承并扩展了 `chatgpt-on-wechat` 的多渠道、插件和模型适配工程基础，并参考了 AgentMesh 的多智能体协作思想。TextBookAgent 的定位不是通用聊天机器人，而是教材和专业知识文档的生产工作台。
