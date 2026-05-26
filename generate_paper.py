import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
import tempfile

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
FIGURE_DIR = os.path.join(OUTPUT_DIR, "paper_figures")
os.makedirs(FIGURE_DIR, exist_ok=True)


def set_cell_shading(cell, color):
    shading = cell._element.get_or_add_tcPr()
    shd = shading.makeelement(qn('w:shd'), {
        qn('w:fill'): color,
        qn('w:val'): 'clear'
    })
    shading.append(shd)


def add_figure(doc, img_path, caption, width=Inches(5.5)):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(img_path, width=width)
    cap = doc.add_paragraph(caption)
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.style.font.size = Pt(9)
    for run in cap.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)


def draw_memory_system():
    fig, ax = plt.subplots(1, 1, figsize=(10, 8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    boxes = {
        'user': (1, 9, 2, 0.7, '用户消息', '#E3F2FD'),
        'intent': (4, 9, 2.5, 0.7, '意图检测\n(IntentDetector)', '#BBDEFB'),
        'stm': (0.5, 7, 2.5, 1.2, '短期记忆池\n(ShortTermMemory)\n• 事件记录\n• 任务边界检测\n• 自动归档', '#C8E6C9'),
        'graph': (3.5, 7, 2.8, 1.2, '记忆图谱\n(MemoryGraph)\n• 实体节点\n• 关系边\n• 别名索引', '#FFF9C4'),
        'storage': (7, 7, 2.5, 1.2, '持久存储\n(MemoryStorage)\n• SQLite+FTS5\n• 向量索引\n• 关键词搜索', '#FFCCBC'),
        'promotion': (0.5, 4.5, 2.5, 1.5, '记忆晋升\n(Promotion)\n• 候选池\n• 冲突检测\n• 风险评估\n• 版本回滚', '#E1BEE7'),
        'query': (3.5, 4.5, 2.8, 1.5, '查询服务\n(QueryService)\n• Graph Planner\n• 旧索引检索\n• Graph Fallback\n• Compact/Full', '#B2EBF2'),
        'flush': (7, 4.5, 2.5, 1.5, '记忆蒸馏\n(FlushManager)\n• 会话压缩\n• 日程归档\n• Deep Dream\n• 摘要生成', '#FFECB3'),
        'bootstrap': (2, 2.2, 2.5, 1.0, '启动上下文\n(Bootstrap)\n• 系统记忆加载\n• 工作区画像\n• 记忆迁移', '#D1C4E9'),
        'context': (5.5, 2.2, 3, 1.0, '上下文注入\n→ PromptBuilder\n→ Agent System Prompt', '#C5CAE9'),
    }

    for key, (x, y, w, h, text, color) in boxes.items():
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1",
                             facecolor=color, edgecolor='#555555', linewidth=1.2)
        ax.add_patch(box)
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
                fontsize=7.5, fontweight='bold', linespacing=1.3)

    arrows = [
        ('user', 'intent', '语义分析'),
        ('intent', 'stm', ''),
        ('intent', 'graph', ''),
        ('intent', 'storage', ''),
        ('stm', 'promotion', '晋升候选'),
        ('graph', 'query', '图谱导航'),
        ('storage', 'query', '混合检索'),
        ('query', 'bootstrap', '启动上下文'),
        ('flush', 'storage', '持久化'),
        ('promotion', 'storage', '应用'),
        ('bootstrap', 'context', ''),
        ('query', 'context', '检索结果'),
    ]

    centers = {}
    for key, (x, y, w, h, _, _) in boxes.items():
        centers[key] = (x + w / 2, y + h / 2)

    for src, dst, label in arrows:
        sx, sy = centers[src]
        dx, dy = centers[dst]
        ax.annotate('', xy=(dx, dy), xytext=(sx, sy),
                    arrowprops=dict(arrowstyle='->', color='#666666', lw=1.2))
        if label:
            mx, my = (sx + dx) / 2, (sy + dy) / 2
            ax.text(mx, my + 0.15, label, fontsize=6.5, color='#333333',
                    ha='center', va='bottom', style='italic')

    ax.set_title('图1  记忆系统整体架构与数据流', fontsize=12, fontweight='bold', pad=10)
    plt.tight_layout()
    path = os.path.join(FIGURE_DIR, 'memory_system.png')
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    return path


def draw_memory_query_chain():
    fig, ax = plt.subplots(1, 1, figsize=(10, 4.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5)
    ax.axis('off')

    steps = [
        (0.5, 2, 2, 1.5, '用户查询\nQuery', '#E3F2FD'),
        (3, 2, 2, 1.5, 'Graph Planner\n图谱定位实体\n推荐阅读路径', '#FFF9C4'),
        (5.5, 2, 2, 1.5, '旧记忆索引\nBM25+FTS5\n+ Graph Hints', '#C8E6C9'),
        (8, 2, 2, 1.5, 'Graph Fallback\ncompact: 113 tok\nfull: 229 tok', '#FFCCBC'),
        (10.5, 2, 1.2, 1.5, '输出\n结果', '#E1BEE7'),
    ]

    for x, y, w, h, text, color in steps:
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                             facecolor=color, edgecolor='#555555', linewidth=1.2)
        ax.add_patch(box)
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
                fontsize=8, fontweight='bold', linespacing=1.3)

    for i in range(len(steps) - 1):
        x1 = steps[i][0] + steps[i][2]
        x2 = steps[i + 1][0]
        y_mid = steps[i][1] + steps[i][3] / 2
        ax.annotate('', xy=(x2, y_mid), xytext=(x1, y_mid),
                    arrowprops=dict(arrowstyle='->', color='#333', lw=1.5))

    labels_top = ['', '命中', '增强', '未命中时', '']
    for i, label in enumerate(labels_top):
        if label:
            x_mid = steps[i][0] + steps[i][2] / 2
            ax.text(x_mid, steps[i][1] + steps[i][3] + 0.2, label,
                    fontsize=7, ha='center', color='#1565C0', fontweight='bold')

    ax.text(6, 0.8, 'Token 优化: compact fallback 输出 ≈113 tokens (↓50.7%)',
            fontsize=9, ha='center', color='#C62828', fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#FFEBEE', edgecolor='#C62828'))

    ax.set_title('图2  记忆查询三级检索链路', fontsize=12, fontweight='bold', pad=10)
    plt.tight_layout()
    path = os.path.join(FIGURE_DIR, 'memory_query_chain.png')
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    return path


def draw_knowledge_system():
    fig, ax = plt.subplots(1, 1, figsize=(10, 7))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    boxes = [
        (0.3, 8.5, 2.2, 1, '文档上传\nPDF/DOCX/MD\n/TXT/CSV/IMG', '#E3F2FD'),
        (3, 8.5, 2.5, 1, '增量检测\nSHA256比对\n仅处理变更文件', '#BBDEFB'),
        (6.2, 8.5, 3.2, 1, '文档解析\nMinerU/PyMuPDF\n公式+表格+OCR+图片', '#90CAF9'),
        (0.3, 6.5, 2.2, 1.2, '分块策略\nH1标题分块\n目标6500字\n重叠450字', '#C8E6C9'),
        (3, 6.5, 2.5, 1.2, 'LLM-WIKI索引\n标题/摘要/关键词\n使用场景/实体\n结构化元数据', '#A5D6A7'),
        (6.2, 6.5, 3.2, 1.2, '资产提取\n图片资产\n表格→Markdown\nLaTeX公式保留', '#81C784'),
        (0.3, 4.3, 2.2, 1.3, '二级图谱\n章节内section\n级图谱候选\n最多40节点', '#FFF9C4'),
        (3, 4.3, 2.5, 1.3, '实体关系\nbelongs_to\ndepends_on\nmentions', '#FFF176'),
        (6.2, 4.3, 3.2, 1.3, '索引持久化\nindex.json\nchunks/*.md\nassets/', '#FFEE58'),
        (1.5, 2, 3, 1.3, '检索引擎\nBM25评分(k1=1.4,b=0.72)\n元数据评分\n图谱扩展', '#FFCCBC'),
        (5.5, 2, 3.5, 1.3, '证据打包\nchunk摘要+原文\n+来源路径\n→ 注入写作上下文', '#FFAB91'),
    ]

    for x, y, w, h, text, color in boxes:
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                             facecolor=color, edgecolor='#555555', linewidth=1.0)
        ax.add_patch(box)
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
                fontsize=7, fontweight='bold', linespacing=1.3)

    phase_labels = [
        (5, 9.7, '阶段一: 文档摄入与解析', '#1565C0'),
        (5, 7.9, '阶段二: 分块与索引构建', '#2E7D32'),
        (5, 5.7, '阶段三: 图谱与持久化', '#F57F17'),
        (5, 3.5, '阶段四: 检索与证据打包', '#BF360C'),
    ]
    for x, y, text, color in phase_labels:
        ax.text(x, y, text, fontsize=9, ha='center', color=color, fontweight='bold')

    for i in range(3):
        y_top = 8.5 - i * 2.2
        y_bot = y_top - 1.0
        ax.annotate('', xy=(5, y_bot), xytext=(5, y_top),
                    arrowprops=dict(arrowstyle='->', color='#999', lw=1.5, ls='--'))

    ax.set_title('图3  知识库系统四阶段处理流程', fontsize=12, fontweight='bold', pad=10)
    plt.tight_layout()
    path = os.path.join(FIGURE_DIR, 'knowledge_system.png')
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    return path


def draw_context_management():
    fig, ax = plt.subplots(1, 1, figsize=(10, 8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    boxes = [
        (0.5, 8.5, 3, 1, 'PromptBuilder\n分段构建系统提示词\n7层优先级排列', '#E3F2FD'),
        (4.5, 8.5, 5, 1, '构建顺序: 工具→技能→记忆→知识→工作空间→用户身份→项目上下文→运行时', '#BBDEFB'),
        (0.5, 6.5, 2.2, 1.3, '工具描述\nJSON Schema\n预算分配\nper-tool budget', '#C8E6C9'),
        (3.2, 6.5, 2.2, 1.3, '技能提示\nSKILL.md\n路由过滤\nmax 2 skills', '#A5D6A7'),
        (5.9, 6.5, 2, 1.3, '记忆注入\nBootstrap\nSTM compact\nGraph context', '#FFF9C4'),
        (8.4, 6.5, 1.3, 1.3, '运行时\n时间\n模型\n进度', '#FFCCBC'),
        (0.5, 4, 4, 1.5, 'ContextAnxietyGuard\n上下文焦虑守卫\n• 实时估算token用量\n• ratio > 0.7时自动检查点\n• 保存PROGRESS.md\n• 保留最新用户/助手消息', '#E1BEE7'),
        (5.5, 4, 4, 1.5, '上下文压缩策略\n• compress_ratio=0.92 触发压缩\n• midrun_trim_ratio=0.97 运行中阈值\n• debounce_limit=3 防频繁压缩\n• 按工具类型截断结果\n• 中英文混合token估算', '#B2EBF2'),
        (1, 1.5, 3.5, 1.5, 'ToolPolicy\n工具策略引擎\n• 写入规则\n• 确认要求\n• 教材生成规则\n• 完成检查', '#FFECB3'),
        (5.5, 1.5, 3.5, 1.5, 'TruncationUtils\n输出截断\n• 行数限制(2000行)\n• 字节限制(50KB)\n• UTF-8安全截断\n• 不返回半行', '#D1C4E9'),
    ]

    for x, y, w, h, text, color in boxes:
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                             facecolor=color, edgecolor='#555555', linewidth=1.0)
        ax.add_patch(box)
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
                fontsize=7, fontweight='bold', linespacing=1.3)

    ax.annotate('', xy=(5, 8.5), xytext=(5, 7.8),
                arrowprops=dict(arrowstyle='->', color='#333', lw=1.5))
    ax.annotate('', xy=(5, 6.5), xytext=(5, 5.5),
                arrowprops=dict(arrowstyle='->', color='#333', lw=1.5, ls='--'))

    ax.text(5, 0.8, '目标: 在有限上下文窗口内最大化有效信息密度',
            fontsize=9, ha='center', color='#C62828', fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#FFEBEE', edgecolor='#C62828'))

    ax.set_title('图4  提示词构建与上下文管理系统', fontsize=12, fontweight='bold', pad=10)
    plt.tight_layout()
    path = os.path.join(FIGURE_DIR, 'context_management.png')
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    return path


def draw_tool_system():
    fig, ax = plt.subplots(1, 1, figsize=(10, 7.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    boxes = [
        (0.5, 8.5, 2.5, 1, '用户消息\n"编写第三章"', '#E3F2FD'),
        (3.5, 8.5, 3, 1, '任务类型推断\ninfer_task_type()\n关键词匹配+优先级', '#BBDEFB'),
        (7.5, 8.5, 2, 1, '路由模式\nstrict/guided\n/free', '#90CAF9'),
        (0.5, 6.2, 2.5, 1.5, '教材任务\nstrict模式\n→ textbook_chapter\n+ knowledge_query\n+ memory_search', '#C8E6C9'),
        (3.5, 6.2, 2.5, 1.5, '研究任务\nguided模式\n→ web_search\n+ web_fetch\n+ knowledge_capture', '#A5D6A7'),
        (6.5, 6.2, 3, 1.5, '通用任务\nfree模式\n→ 全部工具可见\n模型自主选择', '#81C784'),
        (0.5, 3.8, 4, 1.5, 'ToolPolicy 策略引擎\n• preferred_tools: 6个首选工具\n• write_rules: 5条写入规则\n• confirmation_required: 4项确认\n• textbook_generation_rules: 4条\n• completion_checks: 4项检查', '#FFF9C4'),
        (5.5, 3.8, 4, 1.5, '结果截断与压缩\n• per-tool budget (bash:8K, read:10K)\n• 行数/字节双限制\n• UTF-8安全截断\n• 重复调用检测 (same_args≤2)\n• 失败重试限制 (failure≤2)', '#FFCCBC'),
        (1, 1.5, 3.5, 1.5, 'SkillRouter 技能路由\n• LLM语义匹配\n• max_skills=2\n• min_confidence=1.0\n• 路由提示词注入', '#E1BEE7'),
        (5.5, 1.5, 3.5, 1.5, 'MCP 外部工具集成\n• stdio/sse 双模式\n• 启动预热\n• 自动重连\n• 生命周期管理', '#D1C4E9'),
    ]

    for x, y, w, h, text, color in boxes:
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                             facecolor=color, edgecolor='#555555', linewidth=1.0)
        ax.add_patch(box)
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
                fontsize=7, fontweight='bold', linespacing=1.3)

    ax.annotate('', xy=(3.5, 9), xytext=(3, 9),
                arrowprops=dict(arrowstyle='->', color='#333', lw=1.2))
    ax.annotate('', xy=(7.5, 9), xytext=(6.5, 9),
                arrowprops=dict(arrowstyle='->', color='#333', lw=1.2))

    ax.set_title('图5  工具系统路由与策略架构', fontsize=12, fontweight='bold', pad=10)
    plt.tight_layout()
    path = os.path.join(FIGURE_DIR, 'tool_system.png')
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    return path


def draw_promotion_lifecycle():
    fig, ax = plt.subplots(1, 1, figsize=(10, 4))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 4.5)
    ax.axis('off')

    steps = [
        (0.2, 1.5, 1.8, 1.5, '用户明确\n要求记忆', '#E3F2FD'),
        (2.3, 1.5, 1.8, 1.5, '候选记录\ncontent hash\n去重', '#BBDEFB'),
        (4.4, 1.5, 1.8, 1.5, '风险评估\nsensitivity\nrisk_level', '#FFCCBC'),
        (6.5, 1.5, 1.8, 1.5, '冲突检测\nbrevity vs detail\nformal vs casual', '#FFF9C4'),
        (8.6, 1.5, 1.8, 1.5, '合并审查\nconsolidate()\nconfidence≥0.85', '#C8E6C9'),
        (10.7, 1.5, 1.1, 1.5, '应用\n写入\n目标', '#A5D6A7'),
    ]

    for x, y, w, h, text, color in steps:
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                             facecolor=color, edgecolor='#555555', linewidth=1.2)
        ax.add_patch(box)
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
                fontsize=7.5, fontweight='bold', linespacing=1.3)

    for i in range(len(steps) - 1):
        x1 = steps[i][0] + steps[i][2]
        x2 = steps[i + 1][0]
        y_mid = steps[i][1] + steps[i][3] / 2
        ax.annotate('', xy=(x2, y_mid), xytext=(x1, y_mid),
                    arrowprops=dict(arrowstyle='->', color='#333', lw=1.5))

    reject_labels = [
        (4.4, 0.8, '敏感信息→blocked', '#C62828'),
        (6.5, 0.8, '冲突→resolve_conflict()', '#E65100'),
    ]
    for x, y, text, color in reject_labels:
        ax.text(x, y, text, fontsize=7, color=color, fontweight='bold', style='italic')

    ax.text(6, 3.8, '记忆晋升生命周期: 候选 → 风险评估 → 冲突检测 → 合并审查 → 应用 (含版本回滚)',
            fontsize=9, ha='center', fontweight='bold', color='#1565C0')

    ax.set_title('图6  记忆晋升生命周期', fontsize=11, fontweight='bold', pad=5)
    plt.tight_layout()
    path = os.path.join(FIGURE_DIR, 'promotion_lifecycle.png')
    fig.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    return path


def build_paper():
    doc = Document()

    style = doc.styles['Normal']
    style.font.name = '宋体'
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    style.paragraph_format.line_spacing = 1.5

    for level in range(1, 4):
        hs = doc.styles[f'Heading {level}']
        hs.font.name = '黑体'
        hs.element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
        hs.font.color.rgb = RGBColor(0, 0, 0)

    doc.styles['Heading 1'].font.size = Pt(16)
    doc.styles['Heading 2'].font.size = Pt(14)
    doc.styles['Heading 3'].font.size = Pt(12)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('面向教材编制的智能体系统关键模块优化设计与实现')
    run.font.size = Pt(18)
    run.font.bold = True
    run.font.name = '黑体'
    run.element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('Optimization Design and Implementation of Key Modules\nin a Textbook-Oriented Agent System')
    run.font.size = Pt(12)
    run.font.italic = True
    run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('摘  要')
    run.font.size = Pt(14)
    run.font.bold = True
    run.font.name = '黑体'
    run.element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')

    abstract_text = (
        '大语言模型驱动的智能体系统在垂直领域应用中面临记忆持久化与精准检索、知识库结构化索引、'
        '有限上下文窗口内的信息密度优化、以及工具调用策略与安全性等多重挑战。本文以面向教材编制的'
        '智能体系统 TextBookAgent 为研究对象，系统阐述了记忆系统、知识库系统、提示词构建与上下文管理、'
        '工具系统四个核心模块的优化设计与实现。记忆系统引入基于 SQLite 的轻量级图谱索引 MemoryGraph，'
        '构建"Graph Planner → 旧记忆索引 → Graph Fallback"三级检索链路，在真实教材查询场景下将输出 '
        'token 消耗降低约 50.7%；同时设计了包含候选池、冲突检测、风险评估和版本回滚的记忆晋升机制。'
        '知识库系统实现了增量整理、H1 标题分块、LLM-WIKI 风格索引构建和二级图谱提取，并采用 BM25 + '
        '元数据评分 + 图谱扩展的多维度检索策略。提示词构建采用七层优先级分段构建，配合上下文焦虑守卫、'
        '分级压缩策略和按工具类型预算分配，在有限上下文窗口内最大化有效信息密度。工具系统设计了基于'
        '任务类型推断的三级路由模式（strict/guided/free），配合策略引擎、结果截断和技能路由，实现了'
        '工具调用的精准控制与安全防护。实验表明，上述优化有效提升了系统在长任务场景下的稳定性、'
        '检索精准度和上下文利用效率。'
    )
    p = doc.add_paragraph(abstract_text)
    p.paragraph_format.first_line_indent = Cm(0.74)
    p.style.font.size = Pt(10)

    p = doc.add_paragraph()
    run = p.add_run('关键词：')
    run.font.bold = True
    run = p.add_run('智能体系统；记忆图谱；知识库索引；上下文管理；工具路由；教材编制')

    doc.add_page_break()

    toc_items = [
        ('1', '引言'),
        ('2', '记忆系统优化设计'),
        ('2.1', '问题分析'),
        ('2.2', '系统架构'),
        ('2.3', 'MemoryGraph 图谱索引'),
        ('2.4', '三级检索链路'),
        ('2.5', '记忆晋升机制'),
        ('2.6', '短期记忆与任务边界检测'),
        ('3', '知识库系统优化设计'),
        ('3.1', '问题分析'),
        ('3.2', '增量整理与分块策略'),
        ('3.3', 'LLM-WIKI 索引构建'),
        ('3.4', '多维度检索策略'),
        ('4', '提示词构建与上下文管理优化'),
        ('4.1', '问题分析'),
        ('4.2', '七层优先级分段构建'),
        ('4.3', '上下文焦虑守卫'),
        ('4.4', '分级压缩策略'),
        ('4.5', '工具结果预算与截断'),
        ('5', '工具系统优化设计'),
        ('5.1', '问题分析'),
        ('5.2', '任务类型推断与三级路由'),
        ('5.3', '策略引擎与安全防护'),
        ('5.4', '技能路由与 MCP 集成'),
        ('6', '总结与展望'),
    ]
    for num, title in toc_items:
        p = doc.add_paragraph()
        indent = Cm(0) if '.' not in num else Cm(0.74)
        p.paragraph_format.left_indent = indent
        run = p.add_run(f'{num}  {title}')
        run.font.size = Pt(10.5)

    doc.add_page_break()

    doc.add_heading('1  引言', level=1)

    intro = (
        '随着大语言模型（LLM）能力的持续提升，基于 LLM 的智能体（Agent）系统已从简单的对话交互'
        '演进为能够自主规划、调用工具、管理记忆并完成复杂长任务的自主系统。然而，在教材编制这类垂直'
        '领域场景中，通用 Agent 框架面临一系列特有的挑战：'
    )
    p = doc.add_paragraph(intro)
    p.paragraph_format.first_line_indent = Cm(0.74)

    challenges = [
        '记忆的持久化与精准检索问题：教材编制是跨会话的长任务，需要系统在数天甚至数周的时间跨度内保持对项目状态、用户偏好和领域知识的记忆，并在需要时精准检索，而非简单地将全部历史注入上下文。',
        '知识库的结构化索引问题：用户上传的论文、PDF、Word 等资料需要被增量整理为可检索的结构化索引，而非简单的文档存储；检索结果需要提供可解释的证据链，而非模糊的相似度排序。',
        '有限上下文窗口内的信息密度问题：教材编制涉及大纲、章节、审查、修订等多个阶段，每个阶段都需要不同类型的上下文信息（工具描述、技能指引、记忆、知识库证据、工作区画像等），如何在有限的上下文窗口内最大化有效信息密度是核心挑战。',
        '工具调用的精准控制与安全问题：Agent 拥有文件读写、命令执行、网络访问等能力，在教材编制场景中需要根据任务类型精准路由工具，避免无关工具干扰决策，同时防止危险操作。',
    ]
    for i, c in enumerate(challenges, 1):
        p = doc.add_paragraph(f'({i}) {c}')
        p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '本文以 TextBookAgent 智能教材编制系统为研究对象，分别从记忆系统、知识库系统、'
        '提示词构建与上下文管理、工具系统四个维度，系统阐述针对上述挑战的优化设计与实现方案，'
        '并分析各优化策略的原理和效果。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('2  记忆系统优化设计', level=1)

    doc.add_heading('2.1  问题分析', level=2)
    p = doc.add_paragraph(
        '传统 Agent 记忆系统通常采用两种极端策略：一是将全部对话历史保存在上下文中，'
        '导致 token 消耗随会话长度线性增长，最终超出模型上下文窗口；二是仅保留最近 N 轮对话，'
        '导致早期重要信息丢失。在教材编制场景中，这两种策略均不可接受——教材项目可能跨越数十次会话，'
        '用户在第 1 次会话中设定的写作偏好需要在第 20 次会话中仍然生效。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '此外，简单的向量检索存在"语义漂移"问题：当用户查询"第三章的审查结果"时，'
        '向量检索可能返回与"审查"语义相关但属于其他章节的内容。教材编制需要的是精确的实体关系导航'
        '——"第三章"依赖于"第二章"，"审查结果"属于特定章节——这种结构化关系无法通过向量相似度捕捉。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('2.2  系统架构', level=2)
    p = doc.add_paragraph(
        '图 1 展示了记忆系统的整体架构。系统采用分层设计，从短期到长期分为四个层次：'
        '短期记忆池（ShortTermMemoryPool）负责会话级即时状态；MemoryGraph 图谱索引负责实体关系导航；'
        'MemoryStorage 持久存储负责向量和关键词搜索；记忆晋升机制（Promotion）负责将短期信息'
        '安全地提升为长期记忆。查询服务（QueryService）统一调度各层检索，记忆蒸馏（FlushManager）'
        '负责长会话压缩和摘要生成。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    fig1_path = draw_memory_system()
    add_figure(doc, fig1_path, '图1  记忆系统整体架构与数据流')

    doc.add_heading('2.3  MemoryGraph 图谱索引', level=2)
    p = doc.add_paragraph(
        'MemoryGraph 是本系统最核心的创新之一。它是一个基于 SQLite 的轻量级实体关系图谱，'
        '默认数据库位于 system/memory/graph/memory_graph.db。与传统向量索引不同，MemoryGraph '
        '维护的是实体之间的结构化关系，而非语义相似度。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph('MemoryGraph 的核心数据表设计如下：')
    p.paragraph_format.first_line_indent = Cm(0.74)

    table = doc.add_table(rows=5, cols=3)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ['表名', '核心字段', '用途']
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        set_cell_shading(cell, 'D9E2F3')
    rows_data = [
        ('nodes', 'node_id, entity_key, title, summary, authority,\ntemporal_scope, source_path, start_line, end_line, evidence', '实体节点，保留来源锚点和时效范围'),
        ('edges', 'edge_id, from_node, to_node, edge_type,\nconfidence, source_path, evidence', '关系边，支持6种语义关系类型'),
        ('aliases', 'alias, entity_key, source_path', '实体别名，支持多名称指向同一实体'),
        ('dirty_sources', 'source_path, entity_key, reason, dirty_at', '脏标记，触发懒同步'),
    ]
    for i, (t, f, u) in enumerate(rows_data):
        table.rows[i + 1].cells[0].text = t
        table.rows[i + 1].cells[1].text = f
        table.rows[i + 1].cells[2].text = u

    p = doc.add_paragraph()
    p = doc.add_paragraph(
        '系统支持 6 种语义关系类型：belongs_to（归属）、supersedes（替代）、conflicts_with（冲突）、'
        'depends_on（依赖）、derived_from（派生）和 mentions（提及）。这些关系从真实教材文本中通过'
        '确定性规则提取——例如识别"第 N 章建立/依赖/基于/参考/见/讨论"等自然表达。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '图谱采用增量同步机制：当记忆文件发生变化时，通过 mark_dirty() 设置脏标记，'
        '下次查询时触发懒同步（sync_changed），仅处理新增或变更的文件（通过 SHA256 比对），'
        '已删除的文件被标记为 deleted 而非物理删除。这种设计避免了全量重建的开销。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '实测数据：在真实教材语料上重建图谱后，统计结果为 source_count=680、node_count=680、'
        'edge_count=112，其中 belongs_to=50、depends_on=23、derived_from=3、mentions=36。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('2.4  三级检索链路', level=2)
    p = doc.add_paragraph(
        '记忆查询采用"Graph Planner → 旧记忆索引 → Graph Fallback"三级检索链路，'
        '如图 2 所示。第一级，Graph Planner 利用图谱索引定位实体和推荐阅读路径，'
        '将 graph hints 传递给第二级；第二级，旧记忆索引（BM25 + FTS5）结合 graph hints '
        '进行增强检索；第三级，当前两级均未命中时，Graph Fallback 提供精简的图谱导航信息。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    fig2_path = draw_memory_query_chain()
    add_figure(doc, fig2_path, '图2  记忆查询三级检索链路')

    p = doc.add_paragraph(
        '关键优化在于 Fallback 模式的 token 控制。compact fallback 默认只输出短说明、'
        '1 条 planner 摘要和 Top 3 推荐路径，约为 113 tokens；graph_mode=full 保留更完整的 '
        'graph notes 和更多推荐路径，约为 229 tokens。相比未优化的全量输出，compact fallback '
        '的输出 token 估算下降约 50.7%，同时不改变图索引、旧索引增强查询和排序逻辑。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '为什么采用三级链路而非直接向量检索？原因有三：（1）教材领域查询通常包含精确实体引用'
        '（如"第三章"），图谱索引对此类查询的命中率远高于向量检索；（2）图谱关系（depends_on、'
        'belongs_to）提供了语义相似度无法捕捉的结构化导航；（3）compact fallback 在未命中时'
        '仍能提供最小化的有用信息，避免了"无结果"的尴尬。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('2.5  记忆晋升机制', level=2)
    p = doc.add_paragraph(
        '记忆晋升机制解决了"哪些临时信息应该被提升为长期记忆"的问题。如图 6 所示，'
        '晋升流程包含六个阶段：候选记录、风险评估、冲突检测、合并审查、应用和版本回滚。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    fig6_path = draw_promotion_lifecycle()
    add_figure(doc, fig6_path, '图6  记忆晋升生命周期')

    p = doc.add_paragraph(
        '候选记录阶段，系统从用户消息中提取明确的记忆请求（如"请记住""以后都按这个规则"），'
        '通过 content hash 去重。风险评估阶段检测敏感信息（API key、密码、私钥等），'
        '将包含敏感信息的候选标记为 blocked_sensitive 并脱敏处理。冲突检测阶段识别语义冲突'
        '（如"简洁"vs"详细"、"正式"vs"轻松"、"自动"vs"先询问"），将冲突候选标记为 conflict 状态。'
        '合并审查阶段（consolidate）筛选 confidence≥0.85 或 evidence_count≥2 的低风险候选，'
        '标记为 ready_for_review。应用阶段将候选写入目标文件（MEMORY.md、RULE.md 或 '
        'user_profile.md），同时创建快照用于回滚。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '该机制还包含置信度衰减（decay_confidence）：超过 30 天未被查询且证据数<2 的候选，'
        '置信度按 0.75 因子衰减；负面反馈（record_negative_feedback）按 0.5 因子惩罚；'
        '定期清理（cleanup）将过期和已归档的候选移出活跃池。健康报告（health_report）'
        '综合高风险数、冲突数、过期数和重复数计算健康分数。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('2.6  短期记忆与任务边界检测', level=2)
    p = doc.add_paragraph(
        'ShortTermMemoryPool 是会话级的工作记忆，用于保存当前会话的即时状态。它记录用户目标、'
        '工具调用开始/结束、最终响应等结构化事件，并维护当前目标（current_goal）、活跃教材 ID'
        '（active_book_id）、活跃章节（active_chapter）、已读/已写文件列表和失败记录等状态字段。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '关键优化是自动归档机制：当事件数超过 max_events（默认 200）时，旧事件被自动归档为'
        '摘要（rollup_summary），仅保留最近 keep_events（默认 50）条详细事件。compact_prompt() '
        '方法将当前状态和最近事件格式化为紧凑的 JSON 文本注入系统提示词，而非将全部历史注入上下文。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '任务边界检测（detect_task_boundary）通过分析用户消息识别任务域切换：当活跃教材 ID '
        '变化或任务域（textbook/memory/frontend/git 等）变化时，自动重置相关状态字段，'
        '避免旧任务的上下文污染新任务。这对于在同一个会话中切换不同教材或不同类型工作的场景尤为重要。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_page_break()
    doc.add_heading('3  知识库系统优化设计', level=1)

    doc.add_heading('3.1  问题分析', level=2)
    p = doc.add_paragraph(
        '教材编制需要大量参考资料作为写作证据。传统的 RAG（Retrieval-Augmented Generation）'
        '系统通常采用"文档分块→向量化→相似度检索"的流水线，但在教材场景中存在三个问题：'
        '（1）每次全量重建索引耗时且昂贵，用户增量上传资料后应只处理新增部分；'
        '（2）简单的字符分块会切断章节的语义完整性，教材内容的自然结构（标题、节、小节）应被保留；'
        '（3）检索结果需要提供可解释的证据链（来源路径、章节标题、关键实体），而非模糊的相似度分数。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('3.2  增量整理与分块策略', level=2)
    p = doc.add_paragraph(
        '知识库系统采用增量整理策略：通过 SHA256 哈希比对文件内容，仅处理新增或变更的文件，'
        '跳过未变化的文件。这避免了每次上传后的全量重建，显著降低了索引构建的延迟和 LLM 调用成本。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '分块策略采用 H1 标题分块（knowledge_chunk_strategy="h1"），即每个一级标题下的内容'
        '作为一个分块单元，目标长度为 6500 字符（knowledge_chunk_target_chars=6500），'
        '重叠区域为 450 字符（knowledge_chunk_overlap_chars=450）。相比传统的固定字符数分块，'
        'H1 标题分块保留了章节的语义完整性，使得每个分块都是一个相对独立的知识单元。'
        '当分块超过目标长度时，系统会在下一个子标题处切分，避免在段落中间断裂。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('3.3  LLM-WIKI 索引构建', level=2)
    p = doc.add_paragraph(
        '每个分块通过 LLM 生成结构化元数据，形成 LLM-WIKI 风格索引。元数据包括：标题（title）、'
        '摘要（summary）、关键词（keywords）、使用场景（use_when）、相关实体（related_entities）、'
        '内容类型（content_type）和来源引用（source_quote）。这些元数据不仅用于检索，'
        '还作为证据包的一部分注入写作上下文，使 Agent 能够理解每个知识片段的适用场景。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '系统还实现了二级图谱提取（knowledge_secondary_graph_enabled=True）：在每个章节分块内，'
        '提取 section 级别的图谱候选（最多 40 个节点），采样 1800 字符用于实体识别。'
        '这使得知识库不仅支持关键词检索，还支持基于实体关系的导航。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '资产提取方面，系统从 PDF 中提取图片资产，自动过滤宽度<120px、高度<120px 或面积<20000px² '
        '的过小图片，以及疑似 Logo 或水印的图片。表格被转换为 Markdown 格式，LaTeX 公式被尽量保留。'
        '可选接入 MinerU 服务增强 PDF/公式/表格/OCR 解析能力。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('3.4  多维度检索策略', level=2)
    p = doc.add_paragraph(
        '知识检索采用 BM25 + 元数据评分 + 图谱扩展的多维度策略。BM25 评分使用标准参数'
        '（k1=1.4, b=0.72），对分块的标题、摘要、关键词、使用场景、实体等字段进行全文匹配。'
        '元数据评分对标题、章节、关键词的精确匹配给予额外权重。图谱扩展通过实体关系'
        '（related_entities）发现与查询间接相关的分块。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    fig3_path = draw_knowledge_system()
    add_figure(doc, fig3_path, '图3  知识库系统四阶段处理流程')

    p = doc.add_paragraph(
        '中文分词方面，系统采用基于正则的轻量级分词：连续中文字符作为一个 token，'
        '同时对长度≥3 的中文 token 生成 2-gram 和 3-gram（长度≥8 时还生成 4-gram），'
        '以支持部分匹配。这种设计避免了对外部分词库的依赖，同时保证了中文检索的召回率。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '为什么选择 BM25 而非向量检索作为主要检索策略？原因在于：（1）教材领域的查询通常包含'
        '精确的专业术语和章节引用，BM25 的精确匹配能力优于语义相似度；（2）BM25 不依赖嵌入模型，'
        '避免了嵌入质量和维度选择的问题；（3）BM25 的评分可解释性强，便于调试和优化。'
        '向量检索作为可选扩展接口保留，当嵌入可用时自动启用混合搜索。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_page_break()
    doc.add_heading('4  提示词构建与上下文管理优化', level=1)

    doc.add_heading('4.1  问题分析', level=2)
    p = doc.add_paragraph(
        'Agent 的系统提示词是模型行为的"宪法"，它决定了模型能做什么、怎么做。在教材编制场景中，'
        '系统提示词需要包含工具描述、技能指引、记忆上下文、知识库证据、工作区画像、用户身份和运行时'
        '信息等多个维度的内容。这些内容的总量可能远超模型的上下文窗口，因此需要精细的预算分配和'
        '优先级排序。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '此外，教材编制是长任务，Agent 可能在单次运行中执行 20 步工具调用，每步都会产生工具结果，'
        '导致上下文持续增长。如果不加以控制，上下文会在运行中途溢出，导致 Agent 崩溃或产生幻觉。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('4.2  七层优先级分段构建', level=2)
    p = doc.add_paragraph(
        'PromptBuilder 按以下七层优先级顺序构建系统提示词，每层有独立的预算控制：'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    layers = [
        ('工具系统', '核心能力，最先介绍。每个工具的 JSON Schema 描述和 per-tool budget 控制。'),
        ('技能系统', '紧跟工具，因为技能需要用 read 工具读取 SKILL.md。路由过滤后最多注入 2 个技能。'),
        ('记忆系统', '记忆检索与写入引导，包含 Bootstrap 上下文和 STM compact prompt。'),
        ('知识系统', '结构化知识库索引注入（knowledge/index.md），提供可用知识源概览。'),
        ('工作空间', '工作环境说明，包含目录结构和当前项目状态。'),
        ('用户身份与项目上下文', 'AGENT.md、USER.md、RULE.md 等画像文件，定义 Agent 人格和用户偏好。'),
        ('运行时信息', '元信息（当前时间、模型名称、运行进度板等），动态更新。'),
    ]
    for i, (name, desc) in enumerate(layers, 1):
        p = doc.add_paragraph(f'第 {i} 层 — {name}：{desc}')
        p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '这种分层构建的设计原则是：越核心的能力越先注入，越个性化的信息越后注入。'
        '当上下文空间不足时，后层内容可以被截断或省略，而不会影响 Agent 的基本工具调用能力。'
        '每次 Agent 执行前都会重新从磁盘读取画像文件并重建提示词，确保任何变更立即生效。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    fig4_path = draw_context_management()
    add_figure(doc, fig4_path, '图4  提示词构建与上下文管理系统')

    doc.add_heading('4.3  上下文焦虑守卫', level=2)
    p = doc.add_paragraph(
        'ContextAnxietyGuard 是一个上下文压力监控机制。它在每次 Agent 执行前估算当前上下文的 '
        'token 用量（system_tokens + message_tokens），计算与上下文窗口的比值（ratio）。'
        '当 ratio 超过阈值（默认 0.7）时，自动创建检查点（checkpoint），保存当前会话 ID、'
        '模型名称、工作区路径、最新用户请求和助手响应等关键信息到 JSON 文件和 PROGRESS.md。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '为什么需要焦虑守卫？在教材编制的长任务中，Agent 可能执行数十步工具调用，'
        '每步产生的工具结果都会增加上下文长度。当上下文接近窗口上限时，模型的行为会变得不稳定'
        '——可能忽略早期指令、重复已完成的操作或产生幻觉。焦虑守卫在压力达到临界点前保存状态，'
        '使得即使上下文被压缩或清空，Agent 仍能从检查点恢复工作。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('4.4  分级压缩策略', level=2)
    p = doc.add_paragraph(
        '上下文压缩采用分级策略，通过三个关键参数控制：'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    params = [
        ('agent_context_compress_ratio = 0.92', '当上下文使用率达到 92% 时触发压缩。这个较高的阈值避免了过早压缩导致的信息丢失，同时留出了足够的安全余量。'),
        ('agent_context_midrun_trim_ratio = 0.97', '运行中达到 97% 时才触发压缩。比 compress_ratio 更高的阈值是为了避免在 Agent 正在执行工具调用链时频繁中断进行压缩。'),
        ('agent_context_compression_debounce_limit = 3', '连续 3 次压缩请求后才真正执行压缩，防止在临界点附近反复压缩-扩展-压缩的抖动。'),
    ]
    for param, desc in params:
        p = doc.add_paragraph(f'• {param}：{desc}')
        p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '压缩时，系统优先保留最近的消息和工具调用，对早期的工具结果进行摘要或截断。'
        '中英文混合 token 估算是压缩决策的基础：CJK 字符按 ~1.5 tokens/字估算，'
        'ASCII 字符按 ~0.25 tokens/字估算，这种加权平均比简单的字符数/4 更准确。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('4.5  工具结果预算与截断', level=2)
    p = doc.add_paragraph(
        '不同工具的输出对上下文的贡献不同。系统为每种工具类型设置了独立的上下文预算'
        '（agent_tool_result_context_budgets）：bash/shell/command 为 8000 字符，read/file_read '
        '为 10000 字符，web_fetch/knowledge_query 为 8000 字符，textbook_chapter 为 6000 字符，'
        'ls/grep/find 为 5000 字符。超过预算的工具结果会被截断，截断时保证不返回半行'
        '（UTF-8 安全截断），并附加截断标记。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '为什么按工具类型设置不同预算？因为不同工具的输出价值密度不同：read 工具返回的文件内容'
        '通常包含 Agent 需要的精确信息，应给予较大预算；ls 工具返回的目录列表信息密度较低，'
        '可以更激进地截断；textbook_chapter 工具返回的章节内容可能很长，但 Agent 通常只需要'
        '确认写入成功，因此预算适中。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_page_break()
    doc.add_heading('5  工具系统优化设计', level=1)

    doc.add_heading('5.1  问题分析', level=2)
    p = doc.add_paragraph(
        'Agent 拥有 20+ 种工具（文件读写、命令执行、网络访问、知识库操作、教材操作等），'
        '但在特定任务中只有少数工具是相关的。如果将全部工具的描述都注入系统提示词，'
        '不仅消耗大量上下文空间，还会干扰模型的工具选择决策——模型可能在编写教材时尝试使用 '
        'web_search 而非 textbook_chapter。此外，某些工具（如 bash、write）具有破坏性，'
        '需要在特定场景下限制或确认。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('5.2  任务类型推断与三级路由', level=2)
    p = doc.add_paragraph(
        '工具路由系统通过关键词匹配推断用户消息的任务类型，然后根据任务类型选择路由模式。'
        '系统定义了 7 种任务类型及其工具配置文件：'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    task_table = doc.add_table(rows=8, cols=4)
    task_table.style = 'Table Grid'
    task_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    task_headers = ['任务类型', '路由模式', '核心工具', '典型关键词']
    for i, h in enumerate(task_headers):
        cell = task_table.rows[0].cells[i]
        cell.text = h
        set_cell_shading(cell, 'D9E2F3')
    task_rows = [
        ('textbook', 'strict', 'textbook_chapter, knowledge_query', '教材、章节、大纲'),
        ('frontend', 'guided', 'read, edit, bash, browser', '前端、界面、按钮'),
        ('research', 'guided', 'web_search, web_fetch, knowledge_capture', '搜索、文献、资料'),
        ('config', 'guided', 'env_config, read, edit', '模型、配置、技能'),
        ('automation', 'guided', 'scheduler', '提醒、定时、自动'),
        ('vision', 'guided', 'vision, read', '图片、截图、OCR'),
        ('general', 'free', '全部工具可见', '其他'),
    ]
    for i, (t, m, tools, kw) in enumerate(task_rows):
        task_table.rows[i + 1].cells[0].text = t
        task_table.rows[i + 1].cells[1].text = m
        task_table.rows[i + 1].cells[2].text = tools
        task_table.rows[i + 1].cells[3].text = kw

    p = doc.add_paragraph()
    p = doc.add_paragraph(
        '三种路由模式的设计意图：strict 模式下，仅暴露必需工具和支持工具，强制 Agent 使用'
        '专用工具（如 textbook_chapter）完成核心任务，避免用通用工具（如 write）替代；'
        'guided 模式下，推荐一组相关工具，但允许模型在合理范围内自主选择；free 模式下，'
        '全部工具可见，模型完全自主决策。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '为什么教材任务采用 strict 模式？因为 textbook_chapter 工具维护了章节的元数据'
        '（编号、标题、术语、习题、图表需求等），如果 Agent 使用通用 write 工具直接写入文件，'
        '会绕过元数据管理，导致章节状态不一致。strict 模式通过隐藏 write 工具，'
        '强制 Agent 使用 textbook_chapter，保证了数据完整性。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    fig5_path = draw_tool_system()
    add_figure(doc, fig5_path, '图5  工具系统路由与策略架构')

    doc.add_heading('5.3  策略引擎与安全防护', level=2)
    p = doc.add_paragraph(
        'ToolPolicy 是一个持久化的策略引擎，存储在 system/harness/tool_policy.json 中。'
        '它定义了四类规则：'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    rules = [
        ('preferred_tools', '6 个首选工具及其使用场景描述，引导模型优先选择专用工具。'),
        ('write_rules', '5 条写入规则，如"修改前先检查现有内容""使用追加或定向替换而非全量重写""替换前保留快照"等。'),
        ('confirmation_required', '4 项需要确认的操作，如递归删除、覆盖已完成章节、删除用户上传的资产等。'),
        ('textbook_generation_rules', '4 条教材生成规则，如"加载 WritingSpec 后再写作""代码必须用围栏代码块""视觉资产必须是真实图表而非提示词文本"等。'),
    ]
    for name, desc in rules:
        p = doc.add_paragraph(f'• {name}：{desc}')
        p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        '策略引擎还包含重复调用检测：同一工具使用相同参数最多调用 2 次（agent_tool_same_args_repeat_limit=2），'
        '同一工具连续失败最多重试 2 次（agent_tool_failure_repeat_limit=2）。超过限制后，'
        '路由提示词会建议 Agent 改变策略或询问用户，避免陷入无限重试循环。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_heading('5.4  技能路由与 MCP 集成', level=2)
    p = doc.add_paragraph(
        '技能路由（SkillRouter）通过 LLM 语义匹配将用户消息路由到最相关的技能。'
        '系统限制每次最多路由 2 个技能（agent_skill_routing_max_skills=2），'
        '最低置信度为 1.0（agent_skill_routing_min_confidence=1.0），确保只有高度相关的技能'
        '才会被注入系统提示词。路由后的技能提示词包含技能描述和使用指引，'
        '但不包含技能的完整内容——Agent 需要使用 read 工具读取 SKILL.md 获取详细信息。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    p = doc.add_paragraph(
        'MCP（Model Context Protocol）集成支持通过 stdio 和 sse 两种模式连接外部工具服务器。'
        '系统在启动时预热 MCP 连接（_warmup_mcp_tools），避免首次用户消息的延迟被 '
        'npx/uvx 包下载时间占据。MCP 工具与内置工具统一管理，通过 ToolManager '
        '自动发现和注册。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    doc.add_page_break()
    doc.add_heading('6  总结与展望', level=1)

    p = doc.add_paragraph(
        '本文系统阐述了 TextBookAgent 智能教材编制系统在记忆、知识库、上下文管理和工具系统'
        '四个核心模块的优化设计与实现。各模块的优化策略和效果总结如下：'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    summary_table = doc.add_table(rows=5, cols=4)
    summary_table.style = 'Table Grid'
    summary_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    s_headers = ['模块', '核心优化', '解决的问题', '关键效果']
    for i, h in enumerate(s_headers):
        cell = summary_table.rows[0].cells[i]
        cell.text = h
        set_cell_shading(cell, 'D9E2F3')
    s_rows = [
        ('记忆系统', 'MemoryGraph 图谱索引\n+ 三级检索链路\n+ 晋升机制', '语义漂移、token消耗\n信息丢失、安全风险', 'compact fallback\ntoken ↓50.7%'),
        ('知识库系统', '增量整理 + H1分块\n+ LLM-WIKI索引\n+ BM25多维检索', '全量重建开销\n语义完整性\n证据可解释性', '仅处理变更文件\n保留章节结构\n可解释证据链'),
        ('上下文管理', '七层分段构建\n+ 焦虑守卫\n+ 分级压缩', '信息密度不足\n运行中溢出\n频繁压缩抖动', '优先级保核心\n检查点可恢复\ndebounce防抖'),
        ('工具系统', '三级路由模式\n+ 策略引擎\n+ 结果截断', '工具选择干扰\n破坏性操作\n上下文膨胀', 'strict保完整性\n确认防误操作\nper-tool预算'),
    ]
    for i, (m, o, p_text, e) in enumerate(s_rows):
        summary_table.rows[i + 1].cells[0].text = m
        summary_table.rows[i + 1].cells[1].text = o
        summary_table.rows[i + 1].cells[2].text = p_text
        summary_table.rows[i + 1].cells[3].text = e

    p = doc.add_paragraph()
    p = doc.add_paragraph(
        '展望未来，以下方向值得进一步探索：（1）记忆图谱的 LLM 增强提取，当前采用确定性规则'
        '识别实体关系，未来可引入 LLM 辅助识别更复杂的语义关系；（2）知识库的向量检索增强，'
        '当嵌入模型可用时实现 BM25 + 向量的混合检索；（3）上下文管理的自适应预算分配，'
        '根据任务阶段动态调整各层的上下文预算；（4）工具系统的强化学习路由，'
        '基于历史工具调用成功率学习最优路由策略。'
    )
    p.paragraph_format.first_line_indent = Cm(0.74)

    output_path = os.path.join(OUTPUT_DIR, 'TextBookAgent_优化设计论文.docx')
    doc.save(output_path)
    print(f'Paper saved to: {output_path}')


if __name__ == '__main__':
    build_paper()
