# 示意图提示词模板

## 基础结构
```
[主体描述], [视角/构图], [风格约束], [技术参数], [质量约束]
```

## 教材示意图模板
```
A clear, professional educational diagram of {subject_matter},
{composition_description},
clean line art style, labeled with Chinese text annotations,
academic textbook illustration, white background,
CMYK-friendly color palette, high contrast,
suitable for print at 300 DPI,
{size_constraint}
```

## 负面提示词
```
blurry, low quality, watermark, logo, cartoon, anime,
photorealistic, 3D render, gradient background,
dark background, small text, cluttered layout,
oversaturated colors, neon colors
```

## 图片类型专用约束

### 概念图
- 关键词: conceptual diagram, relationship map, labeled nodes
- 构图: 居中对称，层次分明
- 色系: 蓝-灰学术色系

### 设备图
- 关键词: technical illustration, cross-section view, labeled parts
- 构图: 正视/侧视/剖面
- 色系: 工程蓝+灰色

### 场景图
- 关键词: educational scene, classroom/laboratory/field setting
- 构图: 宽幅，人物与环境
- 色系: 自然色系

### 流程图
- 关键词: flowchart, process diagram, step-by-step
- 构图: 从上到下或从左到右
- 色系: 蓝-绿渐变
