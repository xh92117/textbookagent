# TextBookAgent

<p align="right">
  <strong>English</strong> | <a href="README.md">中文</a>
</p>

TextBookAgent is an agentic textbook authoring system for textbooks, lecture notes, course materials, and professional knowledge documents. It combines large language models, textbook production pipelines, knowledge retrieval, Agent Skills, memory, visual asset generation, and Word export into a local-first authoring workspace.

The project is not intended to be a general-purpose chatbot. Its main goal is to help users create a textbook: organize source materials, generate an outline, write chapters, review quality, revise content, polish style, and export the final document.

## Origins and Acknowledgements

TextBookAgent is derived from and inspired by two excellent agent projects:

- [chatgpt-on-wechat](https://github.com/zhayujie/chatgpt-on-wechat): provides important engineering foundations, including multi-channel bot support, plugin architecture, model adapters, and a basic web console. TextBookAgent refactors and extends these foundations with a textbook workspace, knowledge base, long-running pipelines, and textbook-specific agents.
- [AgentMesh](https://github.com/MinimalFuture/AgentMesh): provides ideas for multi-agent collaboration, task delegation, and tool-using agents. Some Agent plugin concepts in this repository follow the multi-agent collaboration pattern inspired by AgentMesh.

Thanks also to the broader open-source ecosystem behind model SDKs, web frameworks, document generation, charting, PDF parsing, and testing tools.

## Core Features

### Textbook Project Management

- Create, view, edit, and delete textbook projects.
- Configure title, subject, target audience, difficulty, chapter count, chapter length, and writing style.
- Track textbook progress, chapter status, chapter content, and export results.
- Maintain durable state files for each textbook so long-running tasks can be resumed or inspected.

### Multi-Agent Textbook Pipeline

The system includes textbook-specific sub-agents and long-running workflows:

- `OutlinerAgent`: creates textbook outlines.
- `ComposerAgent`: builds book-level and chapter-level context.
- `WriterAgent`: drafts chapter content.
- `ReviewerAgent`: reviews outlines and chapters.
- `ReviserAgent`: revises content based on review feedback.
- `PolisherAgent`: normalizes style and improves readability.

The pipeline can:

1. Generate a textbook outline.
2. Review the outline.
3. Build book-level context.
4. Write chapters one by one.
5. Retrieve and inject knowledge-base evidence.
6. Route charts, illustrations, and image assets.
7. Review chapter quality.
8. Revise and polish content when needed.
9. Persist chapters, state, and checkpoints.
10. Export Word documents.

### Knowledge Base and LLM-WIKI Organization

The knowledge base manages uploaded papers, PDFs, Word documents, Markdown, TXT, CSV, JSON, and image assets. It provides evidence packs during textbook writing.

Current capabilities include:

- Incremental organization of new or changed files.
- Chunking by section, heading, and context budget.
- Generating titles, summaries, keywords, usage scenarios, and related entities.
- Extracting image assets from PDFs.
- Extracting tables and converting them to Markdown where possible.
- Preserving formulas and LaTeX expressions where possible.
- Building LLM-WIKI-style indexes.
- Building entity-relation graphs.
- Retrieval through metadata, BM25, and graph expansion.
- Reserved extension points for embeddings and vector retrieval.
- MinerU configuration for enhanced PDF, formula, table, and OCR parsing.

### Charts, Illustrations, and Visual Assets

- Charts are preferably generated from code and structured data.
- Python sandbox execution supports line charts, bar charts, pie charts, scatter plots, radar charts, network graphs, and more.
- Existing image assets can be retrieved from the knowledge base.
- Configured image-generation models can create conceptual illustrations.
- Very small images, logo-like assets, and watermark-like assets can be filtered automatically.
- Generated images can be inserted into chapter Markdown and handled during Word export.

### Agent Skills

Built-in textbook-related skills include:

- `skills/outline`: textbook outline generation.
- `skills/chapter`: chapter writing.
- `skills/review`: textbook review.
- `skills/fullbook`: full-book production.
- `skills/wordgen`: Word document generation.
- `skills/sandbox`: charting and code sandboxing.
- `skills/imagegen`: illustration prompts and image generation.
- `skills/knowledge_organizer`: knowledge base organization.
- `skills/multi-search-engine`: web research through multiple search engines.

Each skill is described by a `SKILL.md` file, including capabilities, inputs, outputs, and execution constraints.

### Web Workspace

- `/textbook`: textbook workspace.
- `/chat`: AI chat page.
- Supports streaming output, tool-call display, task-step display, and conversation history.
- Supports knowledge upload, organization, retrieval, and chapter writing.
- Binds to `127.0.0.1` by default. If exposed publicly, configure `web_password`.
- When `web_require_password_on_public_host` is `true`, an unauthenticated public web console refuses to start.

### Model Configuration

TextBookAgent supports multiple OpenAI-compatible providers and role-based model configuration:

- Main AI chat model.
- Textbook review model.
- Image generation model.
- Knowledge organization model.

Supported configuration styles include DeepSeek, OpenAI-compatible APIs, custom API bases, Qianfan, DashScope, Moonshot, Claude, Gemini, Zhipu, Minimax, and others. Actual availability depends on local configuration and provider access.

### Memory System

- Persistent conversation history.
- Process-level task memory.
- User preference and project-focus records.
- Memory query API.
- Long-session compression and context-budget control.

#### Memory Persistence Rules

The memory system now uses one system-level storage location by default:

```text
{system_workspace}/system/memory/
```

Textbook workspaces are reserved for textbook files, knowledge bases, exports, and project assets. They are no longer used as the agent memory store. Legacy files such as `workspace/MEMORY.md` or `workspace/memory/*.md` are copied into `system/memory/imported/` on startup, with a migration report written to:

```text
system/memory/migrations/memory_migration_report.json
```

Automatic memory saving:

- Conversation state, long-running process state, error records, and user profile data are written automatically under `system/memory/`.
- When an agent uses `write` or `edit` for `MEMORY.md`, `memory/YYYY-MM-DD.md`, or `memory/processes/...`, the path is routed to `system/memory/`.
- Long-session compression and Deep Dream memory distillation update `system/memory/MEMORY.md` and daily memory files.

Manual memory saving:

- Tell the agent “remember this”, “always follow this rule”, or “do not do this again” to store long-term preferences, rules, and important conclusions in `MEMORY.md`.
- Daily progress, temporary context, and stage conclusions can be stored in `memory/YYYY-MM-DD.md`.
- Saved memory can be inspected from the web console memory page or through the memory API.
- Do not store API keys, tokens, passwords, or other sensitive secrets in memory.

Automatic workspace profile updates:

- `AGENT.md`, `USER.md`, and `RULE.md` are workspace profile files for agent operating style, stable user profile, and workspace rules.
- When the user explicitly says “write this to USER.md / AGENT.md / RULE.md”, “make this a workspace rule”, “you should always...”, or “call me...”, the system appends the durable instruction to the matching profile file.
- Before each automatic update, the previous file is backed up under `.workspace_profile_versions/`, and `profile_update_log.jsonl` records the time, source, and reason.
- Preferences that belong to one specific textbook are not written to these global profile files. They should be saved from the textbook detail page and synchronized to that textbook's `WritingSpec`.

### MCP and Tool Extensions

- Built-in tools include read, write, edit, bash, web_fetch, web_search, browser, vision, knowledge_query, knowledge_capture, and pipeline tools.
- External tools can be added through MCP configuration.
- Tool calls can be displayed in the web UI for better observability during long-running tasks.

## Project Structure

```text
TextBookAgent/
  agent/
    chat/                  # AI chat service
    knowledge/             # Knowledge organization, indexing, retrieval
    memory/                # Memory, conversations, user profile
    protocol/              # Agent protocol and streaming tool calls
    skills/                # Skill loading and management
    textbook/              # Textbook agent core
      agents/              # Outliner, Writer, Reviewer, etc.
      docgen/              # Word document generation
      models/              # Textbook, chapter, outline data models
      pipeline/            # Textbook production pipeline
      prompts/             # Textbook writing prompt templates
      sandbox/             # Charting and code sandbox
      state/               # Textbook state and truth files
    tools/                 # Agent tools
  bridge/                  # Bridge between Web, Agent, and textbook backend
  channel/web/             # Web API and frontend pages
  common/                  # Shared utilities
  models/                  # Model provider adapters
  plugins/                 # Plugins
  skills/                  # Agent Skill docs and scripts
  tests/                   # Automated tests
  app.py                   # Entry point
  config-template.json     # Config template
  requirements.txt         # Python dependencies
```

## Requirements

- Python 3.10 or newer.
- Windows, macOS, or Linux. Current development and testing mainly happen on Windows.
- Access to the configured LLM APIs.
- Playwright browser runtime if browser tools are needed.

## Installation

```bash
pip install -r requirements.txt
```

To enable Playwright browser features:

```bash
playwright install chromium
```

## Configuration

Create or edit `config.json`. A template is provided as `config-template.json`.

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

Role-based model example:

```json
{
  "ai_chat_models": [
    {
      "id": "chat_model_1",
      "name": "Main Chat Model",
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

Notes:

- Do not commit real `config.json`, API keys, logs, caches, or local workspaces.
- `.gitignore` already excludes `config.json`, `logs/`, `workspace/`, `node_modules/`, and other local files.
- For public deployment, set `web_password` and review host, reverse-proxy, and access-control settings.

## Start

```bash
python app.py
```

Default textbook workspace:

```text
http://localhost:9899/textbook
```

AI chat page:

```text
http://localhost:9899/chat
```

## Usage

### Textbook Workspace

1. Start the service.
2. Open `http://localhost:9899/textbook`.
3. Create a textbook project.
4. Configure title, subject, audience, difficulty, chapter count, and writing style.
5. Upload papers, documents, or image materials.
6. Organize the knowledge base with AI.
7. Generate or review the textbook outline.
8. Start the full textbook pipeline, or ask the agent to write a specific chapter.
9. Review chapter content, review results, charts, and illustrations.
10. Export the Word document.

### Chat-Driven Workflow

Example prompts:

```text
Generate an outline for this textbook based on the current knowledge base.
```

```text
Write Chapter 14 for "Practical Design of Civil Engineering Agents" and add chart suggestions.
```

The agent chooses an execution path based on textbook state, knowledge base evidence, context, and available tools.

### API Examples

Create a textbook:

```bash
curl -X POST http://localhost:9899/api/textbook ^
  -H "Content-Type: application/json" ^
  -d "{\"title\":\"Data Structures\",\"subject\":\"Computer Science\",\"target_audience\":\"Undergraduates\",\"total_chapters\":10}"
```

Start the textbook pipeline:

```bash
curl -X POST http://localhost:9899/api/textbook/{book_id}/pipeline
```

Check pipeline status:

```bash
curl http://localhost:9899/api/textbook/{book_id}/pipeline
```

Export Word:

```bash
curl http://localhost:9899/api/textbook/{book_id}/export?template=academic
```

## Data Locations

Knowledge organization results are usually stored under:

```text
knowledge/{book_id}/_llm_wiki/
```

Textbook state files are usually stored under:

```text
textbooks/{book_id}/state/status.json
```

Chapter checkpoints are usually stored under:

```text
textbooks/{book_id}/state/pipeline_checkpoints/
```

## Testing

Run all tests:

```bash
python -m pytest tests -q
```

Current tests cover textbook APIs, pipelines, state management, knowledge base, memory, model configuration, document generation, sandboxing, web routes, and tool calls.

## Development Notes

- Run `python -m pytest tests -q` after code changes.
- Long-running tasks should provide progress events, checkpoints, and resumable state.
- Knowledge features should control context size, model-call count, and evidence explainability.
- Model adapters should use the shared registry and role-based configuration where possible.
- Documentation and UI copy should stay focused on textbook authoring instead of unrelated general bot features.

## Chinese Documentation

中文文档见 [README.md](README.md).

## License

MIT License.
