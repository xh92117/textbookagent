import re
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ChapterQualityReport:
    score: int
    passed: bool
    issues: List[Dict[str, str]] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)
    inferred_visuals: List[Dict[str, str]] = field(default_factory=list)


class ChapterQualityGate:
    """Deterministic quality checks for generated textbook chapters.

    LLM reviewer scores are useful but not enough for stable production runs.
    This gate catches structural misses that should be machine-verifiable:
    missing headings, missing teaching objectives, promised visuals without
    generated assets, and missing knowledge evidence.
    """

    VISUAL_PROMISE_RE = re.compile(
        r"(如图所示|见图|流程图|结构图|架构图|示意图|关系图|对比图|曲线图|柱状图|雷达图|timeline|flowchart|diagram)",
        re.I,
    )
    MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
    HEADING_RE = re.compile(r"(?m)^#{1,4}\s+\S+")
    EXERCISE_RE = re.compile(r"(练习|习题|思考题|实践任务|课后作业|案例分析)")
    OBJECTIVE_RE = re.compile(r"(学习目标|教学目标|本章目标|能力目标)")

    def evaluate(
        self,
        content: str,
        *,
        review_score: int = 0,
        evidence_chars: int = 0,
        visual_asset_count: int = 0,
    ) -> ChapterQualityReport:
        content = content or ""
        checks = {
            "has_heading": bool(self.HEADING_RE.search(content)),
            "has_objective": bool(self.OBJECTIVE_RE.search(content)),
            "has_exercise": bool(self.EXERCISE_RE.search(content)),
            "has_evidence": evidence_chars > 80,
            "review_passed": int(review_score or 0) >= 80,
        }
        promised_visuals = self.VISUAL_PROMISE_RE.findall(content)
        has_inline_image = bool(self.MARKDOWN_IMAGE_RE.search(content))
        checks["visuals_resolved"] = not promised_visuals or has_inline_image or visual_asset_count > 0

        issues: List[Dict[str, str]] = []
        penalties = 0
        if not checks["has_heading"]:
            penalties += 15
            issues.append({"level": "critical", "code": "missing_heading", "message": "章节缺少 Markdown 标题结构。"})
        if not checks["has_objective"]:
            penalties += 10
            issues.append({"level": "warning", "code": "missing_objective", "message": "章节缺少学习/教学目标。"})
        if not checks["has_exercise"]:
            penalties += 8
            issues.append({"level": "warning", "code": "missing_exercise", "message": "章节缺少练习、思考题或实践任务。"})
        if not checks["has_evidence"]:
            penalties += 10
            issues.append({"level": "warning", "code": "missing_evidence", "message": "章节写作上下文中缺少知识库/研究证据。"})
        if not checks["visuals_resolved"]:
            penalties += 12
            issues.append({"level": "warning", "code": "unresolved_visual", "message": "章节承诺了图示/图表，但未发现已插入的图片或图表资产。"})

        base = int(review_score or 82)
        score = max(0, min(100, base - penalties))
        return ChapterQualityReport(
            score=score,
            passed=score >= 80 and not any(i["level"] == "critical" for i in issues),
            issues=issues,
            checks=checks,
            inferred_visuals=self.infer_visual_requirements(content),
        )

    def infer_visual_requirements(self, content: str) -> List[Dict[str, str]]:
        """Infer visual requests when the chapter text asks for a figure in prose.

        This is intentionally conservative: it only creates a small number of
        requirements from nearby sentences, preventing token/tool explosion.
        """
        content = content or ""
        if self.MARKDOWN_IMAGE_RE.search(content):
            return []
        results: List[Dict[str, str]] = []
        sentences = re.split(r"(?<=[。！？.!?])\s*", content)
        seen = set()
        for sentence in sentences:
            if not self.VISUAL_PROMISE_RE.search(sentence):
                continue
            desc = re.sub(r"\s+", " ", sentence).strip()
            desc = desc[:120] or "章节配套教学示意图"
            key = desc.lower()
            if key in seen:
                continue
            seen.add(key)
            visual_type = "chart" if re.search(r"(柱状|曲线|对比|雷达|统计|趋势|timeline)", desc, re.I) else "illustration"
            results.append({"description": desc, "image_type": visual_type})
            if len(results) >= 3:
                break
        return results
