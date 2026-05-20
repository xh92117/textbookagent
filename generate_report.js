const fs = require('fs');
const path = require('path');
const { Document, Packer, Paragraph, TextRun, ImageRun, HeadingLevel, 
        AlignmentType, PageBreak, Table, TableRow, TableCell, 
        WidthType, BorderStyle, ShadingType, PageNumber } = require('docx');

// 工作目录
const WORK_DIR = 'd:\\Program Files\\智能体开发\\paper agent\\TextBookAgent';
const ASSETS_DIR = path.join(WORK_DIR, 'report_assets');
const OUTPUT_DIR = 'd:\\Program Files\\智能体开发\\paper agent\\TextBookAgent';

// 读取图片
function readImage(filename) {
    const imgPath = path.join(ASSETS_DIR, filename);
    if (fs.existsSync(imgPath)) {
        return fs.readFileSync(imgPath);
    }
    return null;
}

// 章节标题样式
const heading1Options = {
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 400, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "1976D2" } }
};

const heading2Options = {
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 300, after: 150 }
};

const heading3Options = {
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 100 }
};

// 创建标题段落
function createHeading(text, level) {
    return new Paragraph({
        heading: level,
        children: [new TextRun({ text, bold: true })]
    });
}

// 创建普通段落
function createParagraph(text, options = {}) {
    return new Paragraph({
        spacing: { before: 100, after: 100, line: 360 },
        children: [new TextRun({ text, ...options })]
    });
}

// 创建带项目符号的列表
function createBullet(text, level = 0) {
    return new Paragraph({
        numbering: { reference: "bullets", level },
        spacing: { before: 50, after: 50 },
        children: [new TextRun({ text })]
    });
}

// 创建编号列表
function createNumber(text, level = 0) {
    return new Paragraph({
        numbering: { reference: "numbers", level },
        spacing: { before: 50, after: 50 },
        children: [new TextRun({ text })]
    });
}

// 插入图片
function createImage(filename, width = 500, height = 350) {
    const imgData = readImage(filename);
    if (!imgData) {
        return new Paragraph({
            children: [new TextRun({ text: `[图片: ${filename} 未找到]` })]
        });
    }
    return new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 200, after: 200 },
        children: [new ImageRun({
            type: "png",
            data: imgData,
            transformation: { width, height },
            altText: { title: filename, description: filename, name: filename }
        })]
    });
}

// 插入图片并添加标题
function createFigure(filename, caption, width = 500, height = 350) {
    const imgData = readImage(filename);
    if (!imgData) {
        return [
            new Paragraph({
                children: [new TextRun({ text: `[图片: ${filename} 未找到]` })]
            })
        ];
    }
    return [
        new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: { before: 200, after: 100 },
            children: [new ImageRun({
                type: "png",
                data: imgData,
                transformation: { width, height },
                altText: { title: caption, description: caption, name: caption }
            })]
        }),
        new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: { before: 50, after: 200 },
            children: [new TextRun({ 
                text: `图: ${caption}`, 
                italics: true, 
                size: 20,
                color: "666666"
            })]
        })
    ];
}

// 简单表格
function createSimpleTable(headers, rows) {
    const headerCells = headers.map(h => new TableCell({
        children: [new Paragraph({ 
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: h, bold: true })] 
        })],
        shading: { fill: "E3F2FD", type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 }
    }));
    
    const dataRows = rows.map(row => new TableCell({
        children: [new Paragraph({ 
            children: [new TextRun({ text: row })] 
        })],
        margins: { top: 60, bottom: 60, left: 120, right: 120 }
    }));
    
    return new Table({
        width: { size: 100, type: WidthType.PERCENTAGE },
        columnWidths: headers.map(() => Math.floor(9360 / headers.length)),
        rows: [
            new TableRow({ children: headerCells, tableHeader: true }),
            new TableRow({ children: dataRows })
        ]
    });
}

// 创建文档内容
const doc = new Document({
    styles: {
        default: {
            document: {
                run: {
                    font: { ascii: "Microsoft YaHei", hAnsi: "Microsoft YaHei", eastAsia: "Microsoft YaHei" },
                    size: 24
                }
            }
        },
        paragraphStyles: [
            {
                id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 36, bold: true, color: "1976D2", font: { ascii: "Microsoft YaHei", hAnsi: "Microsoft YaHei", eastAsia: "Microsoft YaHei" } },
                paragraph: { spacing: { before: 400, after: 200 }, outlineLevel: 0, keepNext: false, keepLines: false }
            },
            {
                id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 28, bold: true, color: "2E7D32", font: { ascii: "Microsoft YaHei", hAnsi: "Microsoft YaHei", eastAsia: "Microsoft YaHei" } },
                paragraph: { spacing: { before: 300, after: 150 }, outlineLevel: 1, keepNext: false, keepLines: false }
            },
            {
                id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
                run: { size: 24, bold: true, color: "7B1FA2", font: { ascii: "Microsoft YaHei", hAnsi: "Microsoft YaHei", eastAsia: "Microsoft YaHei" } },
                paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2, keepNext: false, keepLines: false }
            }
        ]
    },
    numbering: {
        config: [
            {
                reference: "bullets",
                levels: [{
                    level: 0, format: "bullet", text: "•", alignment: AlignmentType.LEFT,
                    style: { paragraph: { indent: { left: 720, hanging: 360 } } }
                }, {
                    level: 1, format: "bullet", text: "○", alignment: AlignmentType.LEFT,
                    style: { paragraph: { indent: { left: 1080, hanging: 360 } } }
                }]
            },
            {
                reference: "numbers",
                levels: [{
                    level: 0, format: "decimal", text: "%1.", alignment: AlignmentType.LEFT,
                    style: { paragraph: { indent: { left: 720, hanging: 360 } } }
                }]
            }
        ]
    },
    sections: [{
        properties: {
            page: {
                size: { width: 11906, height: 16838 },
                margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
            }
        },
        headers: {
            default: new (require('docx').Header)({
                children: [new Paragraph({
                    alignment: AlignmentType.RIGHT,
                    children: [new TextRun({ text: "TextBookAgent 智能教材编制系统 - 技术分析报告", size: 18, color: "888888" })]
                })]
            })
        },
        footers: {
            default: new (require('docx').Footer)({
                children: [new Paragraph({
                    alignment: AlignmentType.CENTER,
                    children: [new TextRun({ 
                        children: ["第 ", PageNumber.CURRENT, " 页"] 
                    })]
                })]
            })
        },
        children: [
            // ========== 封面 ==========
            new Paragraph({ spacing: { before: 2000 } }),
            new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [new TextRun({ text: "TextBookAgent", size: 72, bold: true, color: "1976D2" })]
            }),
            new Paragraph({
                alignment: AlignmentType.CENTER,
                spacing: { before: 200 },
                children: [new TextRun({ text: "智能教材编制系统", size: 48, bold: true, color: "2E7D32" })]
            }),
            new Paragraph({
                alignment: AlignmentType.CENTER,
                spacing: { before: 800 },
                children: [new TextRun({ text: "技术架构与实现机制", size: 36, color: "666666" })]
            }),
            new Paragraph({
                alignment: AlignmentType.CENTER,
                spacing: { before: 600 },
                children: [new TextRun({ text: "详细分析报告", size: 28, color: "888888" })]
            }),
            new Paragraph({ spacing: { before: 2000 } }),
            new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [new TextRun({ text: "项目路径: TextBookAgent/", size: 20, color: "999999" })]
            }),
            new Paragraph({
                alignment: AlignmentType.CENTER,
                spacing: { before: 100 },
                children: [new TextRun({ text: "报告日期: 2026年", size: 20, color: "999999" })]
            }),
            new Paragraph({ children: [new PageBreak()] }),

            // ========== 目录 ==========
            createHeading("目录", HeadingLevel.HEADING_1),
            new Paragraph({ 
                spacing: { before: 200, after: 100 },
                children: [new TextRun({ text: "1. 项目概述与整体架构", size: 24 })]
            }),
            new Paragraph({ 
                spacing: { before: 100, after: 100 },
                children: [new TextRun({ text: "2. 教材编写管线流程分析", size: 24 })]
            }),
            new Paragraph({ 
                spacing: { before: 100, after: 100 },
                children: [new TextRun({ text: "3. 知识库系统架构与检索机制", size: 24 })]
            }),
            new Paragraph({ 
                spacing: { before: 100, after: 100 },
                children: [new TextRun({ text: "4. 记忆系统实现机制", size: 24 })]
            }),
            new Paragraph({ 
                spacing: { before: 100, after: 100 },
                children: [new TextRun({ text: "5. 智能体工具调用系统", size: 24 })]
            }),
            new Paragraph({ 
                spacing: { before: 100, after: 100 },
                children: [new TextRun({ text: "6. 智能体协调机制", size: 24 })]
            }),
            new Paragraph({ 
                spacing: { before: 100, after: 100 },
                children: [new TextRun({ text: "7. 总结与展望", size: 24 })]
            }),
            new Paragraph({ children: [new PageBreak()] }),

            // ========== 1. 项目概述与整体架构 ==========
            createHeading("1. 项目概述与整体架构", HeadingLevel.HEADING_1),
            
            createHeading("1.1 项目简介", HeadingLevel.HEADING_2),
            createParagraph("TextBookAgent 是一个面向教材、讲义、课程资料与专业知识内容生产的智能体系统。该系统基于大语言模型、Agent Skill、知识库检索、长任务管线、记忆系统和文档导出能力，支持从一个教材需求逐步生成大纲、章节、审查报告、图表、插图和 Word 文档。"),
            
            createHeading("1.2 核心功能模块", HeadingLevel.HEADING_2),
            createBullet("AI对话与智能体工具调用：支持流式输出、工具调用展示、长期任务状态展示"),
            createBullet("教材项目管理：新建、查看、编辑、删除教材项目，配置教材参数"),
            createBullet("教材编制管线：自动执行大纲生成、章节编写、审查、修订、导出等流程"),
            createBullet("子智能体体系：OutlinerAgent、WriterAgent、ReviewerAgent等专用智能体"),
            createBullet("Agent Skill：模块化的技能目录，支持技能扩展"),
            createBullet("知识库系统：文档整理、检索、图谱索引"),
            createBullet("图表与插图生成：支持多种图表类型和插图生成"),
            createBullet("Word文档导出：支持多种模板和格式"),
            createBullet("记忆系统：进程级记忆、会话历史、用户画像"),
            
            createHeading("1.3 整体架构图", HeadingLevel.HEADING_2),
            ...createFigure('01_architecture.png', '图1-1 TextBookAgent 整体架构图', 550, 400),
            
            createHeading("1.4 目录结构说明", HeadingLevel.HEADING_2),
            createParagraph("项目采用分层架构设计，主要目录结构如下："),
            createSimpleTable(["目录", "功能描述"], [
                ["agent/chat/", "AI对话服务模块"],
                ["agent/knowledge/", "知识库整理与检索"],
                ["agent/memory/", "记忆、会话、用户画像管理"],
                ["agent/protocol/", "智能体执行协议定义"],
                ["agent/skills/", "Skill加载与管理"],
                ["agent/textbook/", "教材智能体核心模块"],
                ["agent/textbook/agents/", "子智能体实现"],
                ["agent/textbook/pipeline/", "教材编制管线"],
                ["agent/tools/", "工具模块（read/write/bash等）"],
                ["bridge/", "Web与智能体/教材后端桥接"],
                ["channel/web/", "Web API与前端页面"],
                ["models/", "各模型供应商适配器"]
            ]),
            new Paragraph({ children: [new PageBreak()] }),

            // ========== 2. 教材编写管线流程 ==========
            createHeading("2. 教材编写管线流程分析", HeadingLevel.HEADING_1),
            
            createHeading("2.1 管线概述", HeadingLevel.HEADING_2),
            createParagraph("教材编制管线（Pipeline）是TextBookAgent的核心编排引擎，负责协调多个子智能体完成教材的完整生成过程。管线采用确定性规划与智能调度相结合的方式，确保教材编写的质量和效率。"),
            
            createHeading("2.2 管线执行阶段", HeadingLevel.HEADING_2),
            createParagraph("管线执行分为七个主要阶段："),
            createNumber("大纲编制（Outline）：使用OutlinerAgent生成教材大纲", 0),
            createNumber("大纲审查（Review Outline）：使用ReviewerAgent审查大纲质量", 0),
            createNumber("上下文组装（Compose）：组织全书上下文，为章节编写做准备", 0),
            createNumber("章节编写（Write）：使用WriterAgent编写章节内容", 0),
            createNumber("章节审查（Review Chapter）：审查章节正确性和连贯性", 0),
            createNumber("修订润色（Revise/Polish）：按需修订并统一风格", 0),
            createNumber("持久化（Persist）：保存章节内容并更新状态", 0),
            
            createHeading("2.3 管线流程图", HeadingLevel.HEADING_2),
            ...createFigure('02_pipeline.png', '图2-1 教材编写管线完整流程图', 600, 450),
            
            createHeading("2.4 章节级语义动作规划", HeadingLevel.HEADING_2),
            createParagraph("PipelineRunner的ChapterOrchestrator为每个章节规划语义动作序列："),
            createBullet("read_outline：读取当前章节大纲"),
            createBullet("retrieve_knowledge：检索知识库证据"),
            createBullet("build_context：组装低上下文写作包"),
            createBullet("write_chapter：调用写作子智能体"),
            createBullet("route_visual_assets：路由图表与插图资产"),
            createBullet("review_chapter：调用教材审核子智能体"),
            createBullet("revise_chapter：按需修订章节"),
            createBullet("polish_chapter：调用润色子智能体"),
            createBullet("persist_chapter：保存章节与更新状态"),
            
            createHeading("2.5 检查点与恢复机制", HeadingLevel.HEADING_2),
            createParagraph("管线实现了完善的检查点机制："),
            createBullet("每个章节执行前保存检查点到 state/pipeline_checkpoints/ 目录"),
            createBullet("支持从断点恢复执行（resume_from参数）"),
            createBullet("自动检测已完成章节，跳过重复工作"),
            createBullet("状态文件记录当前章节、阶段、完成数量等信息"),
            new Paragraph({ children: [new PageBreak()] }),

            // ========== 3. 知识库系统 ==========
            createHeading("3. 知识库系统架构与检索机制", HeadingLevel.HEADING_1),
            
            createHeading("3.1 知识库功能概述", HeadingLevel.HEADING_2),
            createParagraph("知识库用于让教材编写过程检索用户上传的论文、文档、资料和图片资产。系统支持上传PDF、Markdown、TXT、CSV、JSON、Word等文件，并进行智能化整理。"),
            
            createHeading("3.2 文档整理流程", HeadingLevel.HEADING_2),
            createBullet("分块处理：按章节和token上限进行智能分块"),
            createBullet("元数据提取：为分块生成标题、摘要、关键词、使用场景和相关实体"),
            createBullet("表格提取：提取表格并尽量转换为Markdown格式"),
            createBullet("公式提取：提取公式并保留LaTeX形式"),
            createBullet("图片抽取：提取PDF图片并保存为独立图片资产"),
            createBullet("LLM-WIKI索引：构建LLM-WIKI风格的知识索引"),
            
            createHeading("3.3 知识库检索流程图", HeadingLevel.HEADING_2),
            ...createFigure('03_knowledge.png', '图3-1 知识库检索与整理流程图', 550, 350),
            
            createHeading("3.4 混合检索策略", HeadingLevel.HEADING_2),
            createParagraph("KnowledgeRetriever采用混合检索策略："),
            createHeading("3.4.1 BM25关键词检索", HeadingLevel.HEADING_3),
            createParagraph("基于经典BM25算法进行关键词匹配，考虑文档频率和文档长度归一化。"),
            createHeading("3.4.2 元数据评分", HeadingLevel.HEADING_3),
            createBullet("标题匹配：权重×3.0"),
            createBullet("章节匹配：权重×2.5"),
            createBullet("关键词匹配：权重×2.0"),
            createBullet("实体匹配：权重×1.5"),
            createBullet("摘要匹配：权重×1.0"),
            createHeading("3.4.3 图谱扩展检索", HeadingLevel.HEADING_3),
            createParagraph("基于实体关系图谱进行扩展检索，通过相关实体的关联chunk提升召回率。"),
            
            createHeading("3.5 证据包生成", HeadingLevel.HEADING_2),
            createParagraph("检索结果以Evidence Pack格式返回，包含："),
            createBullet("元数据：标题、章节、摘要、使用场景、关键词"),
            createBullet("实体列表：相关实体"),
            createBullet("引用路径：knowledge/_llm_wiki/文件路径"),
            createBullet("资产列表：关联的图片等资源"),
            createBullet("内容摘录：原始内容片段"),
            new Paragraph({ children: [new PageBreak()] }),

            // ========== 4. 记忆系统 ==========
            createHeading("4. 记忆系统实现机制", HeadingLevel.HEADING_1),
            
            createHeading("4.1 记忆系统架构", HeadingLevel.HEADING_2),
            createParagraph("记忆系统采用混合存储与检索架构，支持向量检索与关键词检索的融合查询。"),
            ...createFigure('04_memory.png', '图4-1 记忆系统混合检索架构图', 550, 380),
            
            createHeading("4.2 核心组件", HeadingLevel.HEADING_2),
            createBullet("MemoryManager：核心管理器，协调各组件工作"),
            createBullet("MemoryStorage：基于SQLite的持久化存储"),
            createBullet("TextChunker：文本分块器，控制token数量和重叠"),
            createBullet("EmbeddingProvider：向量嵌入提供者（可选）"),
            createBullet("MemoryFlushManager：定期压缩与长期记忆管理"),
            
            createHeading("4.3 混合检索机制", HeadingLevel.HEADING_2),
            createHeading("4.3.1 向量检索", HeadingLevel.HEADING_3),
            createParagraph("当embedding_provider可用时，支持语义相似度搜索。当前支持OpenAI和LinkAI两种嵌入服务。"),
            createHeading("4.3.2 关键词检索", HeadingLevel.HEADING_3),
            createParagraph("基于SQLite FTS5全文搜索引擎的关键词匹配，即使没有向量服务也能正常工作。"),
            createHeading("4.3.3 结果融合", HeadingLevel.HEADING_3),
            createParagraph("向量检索和关键词检索的结果通过权重融合："),
            createBullet("可配置向量权重和关键词权重（默认各0.5）"),
            createBullet("应用时间衰减函数降低旧记忆权重"),
            
            createHeading("4.4 时间衰减机制", HeadingLevel.HEADING_2),
            createParagraph("记忆系统实现了时间衰减机制："),
            createBullet("非日期文件（如MEMORY.md）：权重为1.0（永久有效）"),
            createBullet("日期文件（如memory/daily/2024-01-29.md）：按文件日期计算衰减"),
            createBullet("衰减公式：multiplier = exp(-ln2/half_life × age_in_days)"),
            createBullet("半衰期默认为30天"),
            
            createHeading("4.5 记忆同步与持久化", HeadingLevel.HEADING_2),
            createBullet("文件扫描：定期扫描workspace目录下的.md文件"),
            createBullet("增量同步：计算文件hash，只同步变更文件"),
            createBullet("分块存储：文件内容分块后存储，支持精确回溯"),
            createBullet("多源支持：支持memory、knowledge、textbook三类来源"),
            new Paragraph({ children: [new PageBreak()] }),

            // ========== 5. 智能体工具调用 ==========
            createHeading("5. 智能体工具调用系统", HeadingLevel.HEADING_1),
            
            createHeading("5.1 工具系统架构", HeadingLevel.HEADING_2),
            createParagraph("工具系统采用模块化设计，支持内置工具、MCP工具和Skill工具的统一管理。"),
            ...createFigure('05_tools.png', '图5-1 智能体工具调用流程图', 550, 420),
            
            createHeading("5.2 工具类型", HeadingLevel.HEADING_2),
            createHeading("5.2.1 内置工具", HeadingLevel.HEADING_3),
            createBullet("read：从文件或目录读取内容"),
            createBullet("write：写入或创建文件"),
            createBullet("bash：执行Shell命令"),
            createBullet("web_search：网络搜索"),
            createBullet("browser：浏览器自动化"),
            createBullet("knowledge_capture：知识捕获"),
            createBullet("memory_search/memory_get：记忆检索"),
            createBullet("pipeline_tool：管线控制"),
            createBullet("send：消息发送"),
            createBullet("vision：图像理解"),
            createBullet("web_fetch：网页抓取"),
            createHeading("5.2.2 MCP工具", HeadingLevel.HEADING_3),
            createParagraph("通过MCP（Model Context Protocol）协议集成的外部工具服务器，支持stdio和SSE两种连接方式。"),
            createBullet("后台异步加载，不阻塞主流程"),
            createBullet("支持运行时配置刷新"),
            createBullet("独立进程隔离，故障不影响主系统"),
            createHeading("5.2.3 Skill工具", HeadingLevel.HEADING_3),
            createParagraph("通过SkillManager管理的技能脚本，提供领域专用的复杂操作能力。"),
            
            createHeading("5.3 工具管理机制", HeadingLevel.HEADING_2),
            createHeading("5.3.1 ToolManager", HeadingLevel.HEADING_3),
            createParagraph("采用单例模式管理所有工具类，负责工具的加载、配置和实例化。"),
            createHeading("5.3.2 BaseTool基类", HeadingLevel.HEADING_3),
            createParagraph("所有工具继承BaseTool基类，统一接口规范："),
            createBullet("name：工具名称"),
            createBullet("description：工具描述（供LLM理解）"),
            createBullet("params：JSON Schema参数定义"),
            createBullet("stage：执行阶段（PRE_PROCESS/POST_PROCESS）"),
            createBullet("execute()：工具执行逻辑"),
            
            createHeading("5.4 工具调用流程", HeadingLevel.HEADING_2),
            createNumber("LLM决策：根据上下文判断是否需要调用工具", 0),
            createNumber("工具选择：根据工具描述匹配最合适的工具", 0),
            createNumber("参数填充：LLM生成工具调用参数", 0),
            createNumber("工具执行：调用BaseTool.execute()方法", 0),
            createNumber("结果返回：ToolResult返回执行结果", 0),
            createNumber("上下文更新：将结果注入LLM上下文继续执行", 0),
            new Paragraph({ children: [new PageBreak()] }),

            // ========== 6. 智能体协调 ==========
            createHeading("6. 智能体协调机制", HeadingLevel.HEADING_1),
            
            createHeading("6.1 Bridge架构", HeadingLevel.HEADING_2),
            createParagraph("TextbookBridge是主编排器，负责协调各子智能体、管理状态和广播事件。"),
            ...createFigure('06_coordination.png', '图6-1 智能体协调与Bridge架构图', 550, 420),
            
            createHeading("6.2 子智能体体系", HeadingLevel.HEADING_2),
            createHeading("6.2.1 OutlinerAgent", HeadingLevel.HEADING_3),
            createParagraph("负责生成教材大纲。根据书名、学科、受众、难度等配置，生成结构化的章节大纲。"),
            createHeading("6.2.2 ComposerAgent", HeadingLevel.HEADING_3),
            createParagraph("组织章节上下文。整合前序章节内容、术语表、知识库证据等，构建低token消耗的上下文包。"),
            createHeading("6.2.3 WriterAgent", HeadingLevel.HEADING_3),
            createParagraph("核心章节编写智能体。支持目标设定、关键结果、认知层次、前置知识等精细控制。"),
            createHeading("6.2.4 ReviewerAgent", HeadingLevel.HEADING_3),
            createParagraph("审查大纲和章节内容。评估内容完整性、逻辑结构、语言表达、学术规范、实用性等维度。"),
            createHeading("6.2.5 ReviserAgent", HeadingLevel.HEADING_3),
            createParagraph("根据审查意见修订内容。处理critical和warning级别的问题。"),
            createHeading("6.2.6 PolisherAgent", HeadingLevel.HEADING_3),
            createParagraph("统一风格并润色文本。确保全书语言风格一致性。"),
            
            createHeading("6.3 事件驱动机制", HeadingLevel.HEADING_2),
            createParagraph("系统采用事件驱动架构，主要事件类型包括："),
            createBullet("pipeline_start/pipeline_complete：管线开始/完成"),
            createBullet("phase_start/phase_complete：阶段开始/完成"),
            createBullet("phase_progress：阶段进度更新"),
            createBullet("agent_call/agent_result：智能体调用/结果"),
            createBullet("chapter_actions_planned：章节动作规划"),
            createBullet("pipeline_error/pipeline_pause/pipeline_resume：管线错误/暂停/恢复"),
            
            createHeading("6.4 SSE实时推送", HeadingLevel.HEADING_2),
            createParagraph("通过Server-Sent Events实现实时进度推送，用户可以在Web界面实时查看管线执行状态。"),
            
            createHeading("6.5 状态持久化", HeadingLevel.HEADING_2),
            createBullet("status.json：当前状态、进度、完成章节"),
            createBullet("truth_files/*.md：真相文件，记录大纲、章节、术语表等"),
            createBullet("checkpoints/：管线检查点，支持断点恢复"),
            createBullet("versions/：大纲版本历史"),
            new Paragraph({ children: [new PageBreak()] }),

            // ========== 7. 总结 ==========
            createHeading("7. 总结与展望", HeadingLevel.HEADING_1),
            
            createHeading("7.1 技术特点总结", HeadingLevel.HEADING_2),
            createBullet("模块化设计：清晰的层次结构和职责划分"),
            createBullet("可扩展性：支持Skill扩展和MCP工具集成"),
            createBullet("可靠性：检查点机制、状态持久化支持断点恢复"),
            createBullet("混合检索：融合向量检索、关键词检索、图谱扩展"),
            createBullet("事件驱动：实时进度反馈，用户体验友好"),
            createBullet("多智能体协作：专业化子智能体，高效分工"),
            
            createHeading("7.2 当前限制", HeadingLevel.HEADING_2),
            createBullet("Web前端仍在改进中，计划封装为桌面客户端"),
            createBullet("知识库embedding和向量数据库为预留结构"),
            createBullet("长任务需要进一步改造为持久任务系统"),
            createBullet("配置和密钥治理需要继续增强"),
            
            createHeading("7.3 未来展望", HeadingLevel.HEADING_2),
            createBullet("完善向量检索能力，支持语义相似度搜索"),
            createBullet("支持更多文档格式和复杂内容处理"),
            createBullet("增强多模态能力，支持更多图表和插图类型"),
            createBullet("优化长任务系统，支持后台持久运行"),
            createBullet("提供更多文档模板和导出格式"),
            
            new Paragraph({ spacing: { before: 600 } }),
            new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [new TextRun({ text: "— 报告结束 —", size: 24, color: "888888" })]
            })
        ]
    }]
});

// 保存文档
const outputPath = path.join(OUTPUT_DIR, 'TextBookAgent_技术分析报告.docx');
Packer.toBuffer(doc).then(buffer => {
    fs.writeFileSync(outputPath, buffer);
    console.log('报告已生成: ' + outputPath);
}).catch(err => {
    console.error('生成失败:', err);
});
