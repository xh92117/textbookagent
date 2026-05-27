# TextBookAgent

<p align="right">
  <a href="README.md">中文</a> | <strong>English</strong>
</p>

TextBookAgent is a local-first agent workspace for producing textbooks, lecture notes, course materials, and professional knowledge documents. It focuses on the full workflow of creating a textbook: organizing source materials, planning an outline, writing chapters, reviewing quality, revising content, generating visuals, and exporting Word documents.

## Features

- Textbook project management: create books, maintain writing specs, and track chapter status.
- Textbook pipeline: outline generation, chapter drafting, review, revision, polishing, and persistence.
- Knowledge base: upload and organize PDF, Word, Markdown, TXT, CSV, JSON, and image sources.
- Specialized agents: Outliner, Writer, Reviewer, Reviser, Polisher, and related textbook agents.
- Agent Skills: outline, chapter writing, review, full-book generation, Word export, sandbox charts, image prompts, and multi-engine search.
- Tool system: built-in tools such as read/write/edit/bash/web_fetch/browser/vision/knowledge_query/textbook_chapter, plus MCP extension support.
- Web workspace: `/textbook` for textbook work and `/chat` for agent chat.
- Export: generate Word documents from chapters and visual assets.

## Requirements

- Python 3.10+
- Access to configured LLM APIs
- Playwright Chromium if browser tools are needed

## Installation

Use a project-local virtual environment to avoid installing dependencies into the system Python.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks the activation script:

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

### Browser Tool

```bash
python -m playwright install chromium
```

## Configuration

Create or edit `config.json`. Use `config-template.json` as a reference.

Minimal web workspace example:

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

Notes:

- Do not commit real `config.json`, API keys, logs, caches, or local workspace data.
- Keep the default web host on `127.0.0.1` unless you know how to secure it.
- For public deployment, set `web_password` and review reverse-proxy and access-control settings.

## Start

Activate the virtual environment first, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

Open:

```text
http://localhost:9899/textbook
http://localhost:9899/chat
```

## Project Layout

```text
agent/       Agent, tools, memory, knowledge, and textbook pipeline logic
bridge/      Bridge between Web services and Agent runtime
channel/     Web pages, API routes, and static assets
models/      Model adapters
plugins/     Plugin system
skills/      Textbook-related Agent Skills
tests/       Automated tests
```

## Tests

```bash
pytest -q
```

## Background

TextBookAgent extends engineering foundations from `chatgpt-on-wechat` and borrows multi-agent collaboration ideas from AgentMesh. It is not intended to be a general-purpose chatbot; it is a production workspace for textbooks and professional knowledge documents.
