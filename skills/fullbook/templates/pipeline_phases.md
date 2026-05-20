# 全教材编制管线阶段说明

## 阶段1: 大纲编制 (outline)
- **执行智能体**: OutlinerAgent
- **输入**: 教材需求、课标信息
- **输出**: outline.md（结构化大纲）
- **关键动作**: OKR递归分解、布鲁姆层次标注、前置依赖梳理

## 阶段2: 大纲审查 (review_outline)
- **执行智能体**: ReviewerAgent
- **输入**: outline.md
- **输出**: review_outline.json（8维度审查结果）
- **关键动作**: 8维度审查、问题分级、修订建议

## 阶段3: 上下文组装 (compose)
- **执行智能体**: ComposerAgent
- **输入**: outline.md + 审查反馈 + 真相文件
- **输出**: 各章上下文包
- **关键动作**: 上下文裁剪、术语表注入、前章摘要注入

## 阶段4: 逐章编写 (write)
- **执行智能体**: WriterAgent × N
- **输入**: 各章上下文包
- **输出**: chapter_XXX.md（各章正文）
- **关键动作**: 正文编写、图表需求识别、习题生成
- **调度策略**: 可顺序或并行

## 阶段5: 逐章审查 (review_chapter)
- **执行智能体**: ReviewerAgent × N
- **输入**: chapter_XXX.md
- **输出**: review_chapter_XXX.json（22维度审查结果）
- **关键动作**: 22维度审查、问题分级、修订建议

## 阶段6: 修订润色 (revise)
- **执行智能体**: ReviserAgent + PolisherAgent
- **输入**: 章节正文 + 审查结果
- **输出**: 修订后章节
- **关键动作**: spot-fix/rewrite/rework修订、语言润色、去AI味

## 阶段7: 持久化 (persist)
- **执行智能体**: WordGenerator
- **输入**: 全部章节 + 大纲
- **输出**: .docx文件 + 状态快照
- **关键动作**: Markdown→Word转换、格式模板应用、图片插入、快照保存
