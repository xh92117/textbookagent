import os
import uuid
import time
import asyncio
import logging
import threading
import json
import re
import textwrap
from typing import Callable, Dict, Optional, List
from ..agents.outliner import OutlinerAgent
from ..agents.composer import ComposerAgent
from ..agents.writer import WriterAgent
from ..agents.reviewer import ReviewerAgent
from ..agents.reviser import ReviserAgent
from ..agents.polisher import PolisherAgent
from ..state.manager import TextbookMemoryManager
from ..state.truth_files import TruthFileManager
from ..models.textbook import TextbookConfig
from ..metrics import measure_content
from .scheduler import ChapterScheduler
from ..sandbox.chart_generator import ChartGenerator
from ..sandbox.executor import SandboxExecutor
from ..sandbox.image_prompt import ImagePromptEngineer, ImageGenerationRequest
from .chapter_persistence import ChapterPersistence
from .context_builder import ContextPackageBuilder
from .orchestrator import ChapterOrchestrator, PipelineCheckpointStore
from .quality_gate import ChapterQualityGate
from .visual_asset_router import VisualAssetRouter
from .book_harness import BookHarness


class PipelineRunner:
    logger = logging.getLogger(__name__)
    PHASES = ['outline', 'review_outline', 'compose', 'write', 'review_chapter', 'revise', 'persist']
    PHASE_LABELS = {
        'outline': '大纲编制',
        'review_outline': '大纲审查',
        'compose': '上下文组装',
        'write': '章节编写',
        'review_chapter': '教材审查',
        'revise': '修订润色',
        'persist': '持久化',
    }

    def __init__(self, llm_model=None, review_llm_model=None, memory_manager: TextbookMemoryManager = None, on_event: Callable = None):
        self.llm_model = llm_model
        self.review_llm_model = review_llm_model or llm_model
        self.memory_manager = memory_manager
        self.on_event = on_event
        self.pipeline_id = ""
        self._paused = False
        self._cancelled = False
        self._cancel_event = threading.Event()

        self.outliner = OutlinerAgent(llm_model=llm_model, on_event=self._wrap_event('OutlinerAgent'))
        self.composer = ComposerAgent(llm_model=llm_model, on_event=self._wrap_event('ComposerAgent'))
        self.writer = WriterAgent(llm_model=llm_model, on_event=self._wrap_event('WriterAgent'))
        self.reviewer = ReviewerAgent(llm_model=self.review_llm_model, on_event=self._wrap_event('ReviewerAgent'))
        self.reviser = ReviserAgent(llm_model=llm_model, on_event=self._wrap_event('ReviserAgent'))
        self.polisher = PolisherAgent(llm_model=llm_model, on_event=self._wrap_event('PolisherAgent'))

        self._all_agents = [self.outliner, self.composer, self.writer, self.reviewer, self.reviser, self.polisher]

    def _create_fallback_illustration(self, description: str, output_dir: str, filename: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, filename)
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (1200, 900), "#f8fafc")
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, 1199, 899), outline="#cbd5e1", width=4)
            draw.rectangle((70, 70, 1130, 830), fill="#ffffff", outline="#94a3b8", width=2)
            title = "教材插图占位图"
            body = textwrap.wrap(description or "待生成插图", width=24)[:8]
            try:
                font_title = ImageFont.truetype("msyh.ttc", 54)
                font_body = ImageFont.truetype("msyh.ttc", 34)
            except Exception:
                font_title = ImageFont.load_default()
                font_body = ImageFont.load_default()
            draw.text((120, 130), title, fill="#0f172a", font=font_title)
            y = 240
            for line in body:
                draw.text((120, y), line, fill="#334155", font=font_body)
                y += 54
            draw.text((120, 760), "图片生成失败时自动生成，可稍后替换为正式插图。", fill="#64748b", font=font_body)
            img.save(output_path, "PNG")
            return output_path
        except Exception:
            svg_path = os.path.splitext(output_path)[0] + ".svg"
            safe_desc = (description or "待生成插图").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900">'
                    '<rect width="100%" height="100%" fill="#f8fafc"/>'
                    '<rect x="70" y="70" width="1060" height="760" fill="#fff" stroke="#94a3b8" stroke-width="2"/>'
                    '<text x="120" y="170" font-size="54" fill="#0f172a">教材插图占位图</text>'
                    f'<text x="120" y="260" font-size="32" fill="#334155">{safe_desc[:80]}</text>'
                    '</svg>'
                )
            return svg_path

    def _load_research_evidence(self, book_id: str, requirement: str = "") -> str:
        evidence_parts = []
        if requirement and requirement.strip():
            evidence_parts.append("## Web Evidence Pack\n" + requirement.strip())
        if self.memory_manager:
            try:
                mgr = self.memory_manager.get_truth_manager(book_id)
                saved = mgr.read("research_evidence")
                if saved and saved.strip() and saved.strip() not in "\n\n".join(evidence_parts):
                    evidence_parts.append("## Saved Web Evidence Pack\n" + saved.strip())
            except Exception:
                pass
        return "\n\n".join(evidence_parts).strip()

    def _load_wiki_context(self, book_id: str, chapter_hint: str, limit: int = 6) -> str:
        self._last_wiki_diagnostics = {}
        if not self.memory_manager:
            return ""
        try:
            from agent.knowledge.retriever import KnowledgeRetriever
            workspace_root = getattr(self.memory_manager, "workspace_root", self.memory_manager.workspace_dir)
            retriever = KnowledgeRetriever(workspace_root, book_id)
            self._last_wiki_diagnostics = retriever.diagnose(chapter_hint, limit=max(limit, 8))
            return retriever.format_compact_evidence_pack(chapter_hint, metadata_limit=max(limit, 8), excerpt_limit=3, excerpt_chars=500)
        except Exception:
            return ""

    def _chapter_retrieval_query(self, book_config: TextbookConfig, chapter_number: int, outline_text: str) -> str:
        """Build a compact retrieval query without dumping the whole outline."""
        current = ContextPackageBuilder()._current_chapter_outline(outline_text, chapter_number)
        current = re.sub(r"\s+", " ", current or "").strip()
        if len(current) > 1200:
            current = current[:1200].rstrip() + "..."
        return " ".join(
            part for part in [
                book_config.title,
                book_config.subject,
                book_config.level,
                f"第{chapter_number}章",
                current,
            ]
            if part
        )

    def _read_wiki_chunk_excerpt(self, wiki_dir: str, rel_path: str, max_chars: int = 900) -> str:
        if not rel_path or ".." in rel_path:
            return ""
        full_path = os.path.normpath(os.path.join(wiki_dir, rel_path))
        allowed = os.path.normpath(wiki_dir)
        if not full_path.startswith(allowed + os.sep) and full_path != allowed:
            return ""
        if not os.path.isfile(full_path):
            return ""
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return ""
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                text = parts[2]
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "..."
        return text

    def _wrap_event(self, agent_name: str) -> Callable:
        def wrapper(event: dict):
            event['pipeline_id'] = self.pipeline_id
            event['agent_name'] = agent_name
            self._emit(event.get('type', 'agent_event'), event.get('data', {}))
        return wrapper

    def _emit(self, event_type: str, data: dict):
        if self.on_event:
            self.on_event({
                'type': event_type,
                'pipeline_id': self.pipeline_id,
                'data': data,
                'timestamp': time.time(),
            })

    async def _check_pause_cancel(self, phase: str, results: dict) -> bool:
        """Check for pause/cancel between phases. Returns True if cancelled."""
        while self._paused:
            await asyncio.sleep(0.5)
        if self._cancelled:
            self._emit('pipeline_error', {'phase': phase, 'error': 'Cancelled'})
            return True
        return False

    def _ensure_agent_result(self, result: dict, agent_name: str, phase: str):
        status = (result or {}).get("status", "")
        if status and status not in ("success", "ok", "passed"):
            error = (result or {}).get("error") or (result or {}).get("message") or f"{agent_name} failed"
            raise RuntimeError(f"{phase}: {agent_name} failed: {error}")
        return result or {}

    @staticmethod
    def _insert_visual_assets(content: str, asset_files: dict, visual_requests: list | None = None) -> str:
        content_with_media = content or ""
        requests_by_desc = {
            item.get("description", ""): item
            for item in (visual_requests or [])
            if isinstance(item, dict) and item.get("description")
        }
        inserted = set()

        for desc, fpath in (asset_files or {}).items():
            rel_path = fpath.replace('\\', '/') if fpath else ''
            replacement = f'![{desc}]({rel_path})'
            count = 0
            for kind in ("chart", "Chart", "image", "Image", "Illustration", "illustration"):
                for separator in (":", "："):
                    marker = f"[{kind}{separator} {desc}]"
                    if marker in content_with_media:
                        count += content_with_media.count(marker)
                        content_with_media = content_with_media.replace(marker, replacement)
            if count:
                inserted.add(desc)

        for desc, fpath in (asset_files or {}).items():
            if desc in inserted:
                continue
            rel_path = fpath.replace('\\', '/') if fpath else ''
            image_line = f'![{desc}]({rel_path})'
            insert_after = (requests_by_desc.get(desc) or {}).get("insert_after")
            if not insert_after:
                content_with_media = content_with_media.rstrip() + "\n\n" + image_line + "\n"
                continue

            lines = content_with_media.splitlines()
            target_index = next(
                (idx for idx, line in enumerate(lines) if insert_after in line),
                None,
            )
            if target_index is None:
                content_with_media = content_with_media.rstrip() + "\n\n" + image_line + "\n"
                continue
            lines.insert(target_index + 1, image_line)
            content_with_media = "\n".join(lines)

        return content_with_media

    def _should_polish_chapter(self, content: str, review_result: dict, style: str) -> bool:
        """Skip an expensive polish pass when the chapter already passed cleanly."""
        if not self.llm_model:
            return False
        score = review_result.get("score", 0) or 0
        issues = review_result.get("issues") or []
        has_non_info_issue = any(str(issue.get("level", "")).lower() in ("critical", "warning") for issue in issues if isinstance(issue, dict))
        if score >= 88 and not has_non_info_issue:
            return False
        if len(content or "") < 1200 and score >= 82 and not has_non_info_issue:
            return False
        return True

    async def run_full_pipeline(self, book_config: TextbookConfig, requirement: str = "", resume_from: str = "") -> dict:
        self.pipeline_id = str(uuid.uuid4())
        self._cancelled = False
        self._paused = False
        self._cancel_event.clear()
        for agent in self._all_agents:
            agent.set_cancel_event(self._cancel_event)
        book_id = book_config.id
        writing_spec = book_config.ensure_writing_spec()
        writing_spec_prompt = writing_spec.to_prompt()
        research_evidence = self._load_research_evidence(book_id, requirement)
        book_dir = os.path.join(self.memory_manager.workspace_dir, book_id) if self.memory_manager else ''
        book_harness = BookHarness(book_dir) if book_dir else None
        book_harness_text = book_harness.ensure(book_config, writing_spec) if book_harness else ""
        book_harness_prompt = book_harness.compact_prompt_section() if book_harness and book_harness_text else ""
        generation_contract = "\n\n".join(part for part in [writing_spec_prompt, book_harness_prompt] if part)

        start_phase = resume_from if resume_from else 'outline'
        phase_index = self.PHASES.index(start_phase) if start_phase in self.PHASES else 0

        self._emit('pipeline_start', {
            'pipeline_id': self.pipeline_id,
            'book_id': book_id,
            'total_phases': len(self.PHASES),
            'phases': self.PHASES,
            'resume_from': start_phase,
        })

        results = {}
        outline_text = ""
        total_chapters = book_config.total_chapters
        completed_chapters = []

        if self.memory_manager:
            mgr = self.memory_manager.get_truth_manager(book_id)
            existing_outline = mgr.read('outline')
            completed_chapters = mgr.list_completed_chapter_numbers(min_chars=50)
            if completed_chapters and phase_index < 2:
                phase_index = 2

        if phase_index <= 0 and existing_outline.strip():
            outline_text = existing_outline
            self._emit('phase_complete', {'phase': 'outline', 'result_summary': 'outline exists; skipped regeneration'})
        elif phase_index <= 0:
            self._emit('phase_start', {'phase': 'outline', 'phase_label': self.PHASE_LABELS['outline'], 'agent': 'OutlinerAgent'})
            outline_result = await self.outliner.run({
                'title': book_config.title,
                'subject': book_config.subject,
                'target_audience': book_config.target_audience,
                'level': book_config.level,
                'total_chapters': book_config.total_chapters,
                'chapter_word_count': book_config.chapter_word_count,
                'style': book_config.style,
                'writing_spec': generation_contract,
                'curriculum_standard': "\n\n".join(
                    part for part in [book_config.curriculum_standard, research_evidence] if part
                ),
            })
            outline_result = self._ensure_agent_result(outline_result, "OutlinerAgent", "outline")
            results['outline'] = outline_result
            self._emit('phase_complete', {'phase': 'outline', 'result_summary': '大纲生成完成'})

            if await self._check_pause_cancel('outline', results):
                return results

            if self.memory_manager:
                mgr = self.memory_manager.get_truth_manager(book_id)
                mgr.write('outline', outline_result.get('outline_text', ''))
                mgr.invalidate_outline_review("outline_regenerated")
                self.memory_manager.update_terminology(book_id, outline_result.get('terminology', {}))
            outline_text = outline_result.get('outline_text', '')
        else:
            if self.memory_manager:
                mgr = self.memory_manager.get_truth_manager(book_id)
                outline_text = mgr.read('outline')
            self._emit('phase_complete', {'phase': 'outline', 'result_summary': '大纲已存在，跳过生成'})

        outline_review_current = False
        if self.memory_manager:
            try:
                mgr = self.memory_manager.get_truth_manager(book_id)
                outline_review_current = mgr.is_outline_review_current(outline_text)
                if not outline_review_current:
                    outline_review_current = mgr.infer_outline_review_from_reports()
            except Exception:
                outline_review_current = False

        if phase_index <= 1 and outline_review_current:
            self._emit('phase_complete', {'phase': 'review_outline', 'result_summary': 'outline review is current; skipped re-review'})
        elif phase_index <= 1:
            self._emit('phase_start', {'phase': 'review_outline', 'phase_label': self.PHASE_LABELS['review_outline'], 'agent': 'ReviewerAgent'})
            self.reviewer.set_review_mode('outline')
            review_result = await self.reviewer.run({
                'title': book_config.title,
                'item_label': '大纲',
                'content': outline_text,
                'outline_context': '',
                'writing_spec': generation_contract,
            })
            review_result = self._ensure_agent_result(review_result, "ReviewerAgent", "review_outline")
            results['review_outline'] = review_result
            if self.memory_manager:
                mgr = self.memory_manager.get_truth_manager(book_id)
                mgr.mark_outline_reviewed(outline_text, review_result)
            self._emit('phase_complete', {'phase': 'review_outline', 'score': review_result.get('score', 0)})

            if await self._check_pause_cancel('review_outline', results):
                return results
        else:
            self._emit('phase_complete', {'phase': 'review_outline', 'result_summary': '大纲审查已跳过'})

        scheduler = ChapterScheduler(total_chapters)
        workspace_root = getattr(self.memory_manager, "workspace_root", self.memory_manager.workspace_dir) if self.memory_manager else os.path.dirname(os.path.dirname(book_dir))
        persistence = ChapterPersistence(book_dir) if book_dir else None
        context_builder = ContextPackageBuilder(self.memory_manager)
        quality_gate = ChapterQualityGate()
        if book_config.chapter_word_count:
            scale = 0.85 if book_config.chapter_word_count <= 3000 else 1.15 if book_config.chapter_word_count >= 8000 else 1.0
            context_builder.budgets = {
                key: max(800, int(value * scale))
                for key, value in context_builder.budgets.items()
            }
        orchestrator = ChapterOrchestrator()
        checkpoint_store = PipelineCheckpointStore(book_dir) if book_dir else None

        def update_book_status(current_chapter: Optional[int], current_phase: str, run_status: str = "running", extra: Optional[Dict] = None):
            if not self.memory_manager:
                return
            try:
                mgr = self.memory_manager.get_truth_manager(book_id)
                mgr.update_status(
                    total_chapters=total_chapters,
                    current_chapter=current_chapter,
                    current_phase=current_phase,
                    run_status=run_status,
                    extra=extra,
                )
            except Exception as exc:
                logger.warning(f"Failed to update textbook status.json: {exc}")

        update_book_status(None, "pipeline_started", "running", {"pipeline_id": self.pipeline_id})

        if completed_chapters:
            for ch_num in completed_chapters:
                scheduler.mark_completed(ch_num)

        while True:
            i = scheduler.get_next_chapter()
            if i is None:
                break
            if await self._check_pause_cancel('compose', {}):
                break

            self._emit('phase_progress', {
                'phase': 'write',
                'current_item': i,
                'total_items': total_chapters,
                'item_label': f'第{i}章',
            })

            actions = orchestrator.plan(i, outline_text=outline_text, has_knowledge=bool(self.memory_manager))
            if checkpoint_store:
                checkpoint_store.save(i, actions, {"stage": "planned"})
            update_book_status(i, "chapter_actions_planned", "running", {"pipeline_id": self.pipeline_id})
            self._emit('chapter_actions_planned', {
                'chapter_number': i,
                'actions': [action.__dict__ for action in actions],
            })

            terminology = self.memory_manager.get_terminology(book_id) if self.memory_manager else {}
            chapter_hint = self._chapter_retrieval_query(book_config, i, outline_text)
            PipelineCheckpointStore.mark(actions, "read_outline", "completed", "outline loaded")
            if checkpoint_store:
                checkpoint_store.save(i, actions, {"stage": "read_outline"})
            update_book_status(i, "read_outline", "running", {"pipeline_id": self.pipeline_id})
            PipelineCheckpointStore.mark(actions, "retrieve_knowledge", "running")
            wiki_context = self._load_wiki_context(book_id, chapter_hint)
            wiki_diagnostics = getattr(self, "_last_wiki_diagnostics", {}) or {}
            PipelineCheckpointStore.mark(actions, "retrieve_knowledge", "completed", f"{len(wiki_context)} chars")
            if checkpoint_store:
                checkpoint_store.save(i, actions, {"stage": "retrieve_knowledge", "knowledge_diagnostics": wiki_diagnostics})
            update_book_status(i, "retrieve_knowledge", "running", {
                "pipeline_id": self.pipeline_id,
                "wiki_context_chars": len(wiki_context),
                "knowledge_diagnostics": wiki_diagnostics,
            })
            self._emit('knowledge_retrieved', {
                "chapter_number": i,
                "query_chars": wiki_diagnostics.get("query_chars", len(chapter_hint)),
                "chunk_count": wiki_diagnostics.get("chunk_count", 0),
                "top_chunks": wiki_diagnostics.get("top_chunks", [])[:5],
            })
            self._emit('phase_progress', {
                'phase': 'compose',
                'current_item': i,
                'total_items': total_chapters,
                'item_label': f'第{i}章 确定性上下文组装',
            })

            PipelineCheckpointStore.mark(actions, "build_context", "running")
            context_package = context_builder.build(
                book_id=book_id,
                chapter_number=i,
                outline_text=outline_text,
                research_evidence=research_evidence,
                wiki_context=wiki_context,
                terminology=terminology,
                book_harness=book_harness_prompt,
            )
            PipelineCheckpointStore.mark(actions, "build_context", "completed", f"{len(context_package)} chars")
            if checkpoint_store:
                checkpoint_store.save(i, actions, {"stage": "build_context", "context_chars": len(context_package)})
            update_book_status(i, "build_context", "running", {
                "pipeline_id": self.pipeline_id,
                "context_chars": len(context_package),
            })
            chapter_plan = context_builder.extract_chapter_plan(outline_text, i)

            if await self._check_pause_cancel('compose', {}):
                break

            self._emit('phase_progress', {
                'phase': 'write',
                'current_item': i,
                'total_items': total_chapters,
                'item_label': f'第{i}章 章节编写',
            })

            PipelineCheckpointStore.mark(actions, "write_chapter", "running")
            write_result = await self.writer.run({
                'chapter_number': i,
                'chapter_title': chapter_plan.title or f'第{i}章',
                'objective': chapter_plan.objective,
                'key_results': chapter_plan.key_results,
                'cognitive_level': chapter_plan.cognitive_level or '应用',
                'prerequisites': chapter_plan.prerequisites,
                'key_concepts': chapter_plan.key_concepts_text(),
                'target_words': book_config.chapter_word_count,
                'context': context_package,
                'terminology': terminology,
                'writing_spec': generation_contract,
            })
            write_result = self._ensure_agent_result(write_result, "WriterAgent", "write_chapter")
            draft_metrics = write_result.get("metrics") or measure_content(write_result.get('content', '')).to_dict()
            PipelineCheckpointStore.mark(actions, "write_chapter", "completed", f"{draft_metrics.get('effective_word_count', 0)} effective words")
            if checkpoint_store:
                checkpoint_store.save(i, actions, {"stage": "write_chapter"})
            update_book_status(i, "write_chapter", "running", {
                "pipeline_id": self.pipeline_id,
                "draft_metrics": draft_metrics,
            })

            chart_reqs = write_result.get('chart_requirements', [])
            image_reqs = write_result.get('image_requirements', [])
            inferred_visuals = quality_gate.infer_visual_requirements(write_result.get('content', ''))
            for req in inferred_visuals:
                desc = req.get("description", "")
                if desc and not any(item.get("description") == desc for item in image_reqs):
                    image_reqs.append(req)
            chart_files = {}
            visual_decisions = []
            PipelineCheckpointStore.mark(actions, "route_visual_assets", "running")
            if (chart_reqs or image_reqs) and book_dir:
                router = VisualAssetRouter(
                    book_dir=book_dir,
                    book_id=book_id,
                    workspace_root=workspace_root,
                )
                for idx, req in enumerate(chart_reqs, start=1):
                    desc = req.get('description', '')
                    decision = router.resolve_chart(desc, i, idx, chart_type=req.get('chart_type', 'auto'))
                    visual_decisions.append(decision.__dict__)
                    if decision.status == 'success' and decision.path:
                        chart_files[desc] = decision.path
                    else:
                        logger.warning(f"Visual chart routing failed for chapter {i}: {desc} - {decision.reason}")
                for idx, req in enumerate(image_reqs, start=1):
                    desc = req.get('description', '')
                    decision = router.resolve_image(desc, i, idx, image_type=req.get('image_type', 'illustration'))
                    visual_decisions.append(decision.__dict__)
                    if decision.status == 'success' and decision.path:
                        chart_files[desc] = decision.path
                    else:
                        logger.warning(f"Visual image routing failed for chapter {i}: {desc} - {decision.reason}")
            PipelineCheckpointStore.mark(actions, "route_visual_assets", "completed", f"{len(chart_files)} assets")
            if checkpoint_store:
                checkpoint_store.save(i, actions, {
                    "stage": "route_visual_assets",
                    "asset_count": len(chart_files),
                    "visual_decisions": visual_decisions,
                })
            update_book_status(i, "route_visual_assets", "running", {
                "pipeline_id": self.pipeline_id,
                "asset_count": len(chart_files),
            })

            content_with_media = write_result.get('content', '')
            relative_chart_files = {}
            for desc, fpath in chart_files.items():
                rel_path = fpath.replace('\\', '/') if fpath else ''
                if book_dir and os.path.isabs(rel_path):
                    try:
                        rel_path = os.path.relpath(rel_path, book_dir).replace('\\', '/')
                    except ValueError:
                        pass
                relative_chart_files[desc] = rel_path
            write_result['content'] = self._insert_visual_assets(
                content_with_media,
                relative_chart_files,
                list(chart_reqs or []) + list(image_reqs or []),
            )

            if self.memory_manager:
                self.memory_manager.update_terminology(book_id, write_result.get('key_terms', {}))

            if await self._check_pause_cancel('write', {}):
                break

            self._emit('phase_progress', {
                'phase': 'review_chapter',
                'current_item': i,
                'total_items': total_chapters,
                'item_label': f'第{i}章 教材审查',
            })

            self.reviewer.set_review_mode('chapter')
            PipelineCheckpointStore.mark(actions, "review_chapter", "running")
            chapter_review = await self.reviewer.run({
                'title': book_config.title,
                'item_label': f'第{i}章',
                'content': write_result.get('content', ''),
                'outline_context': outline_text,
                'writing_spec': generation_contract,
                'content_metrics': measure_content(write_result.get('content', '')).to_dict(),
            })
            chapter_review = self._ensure_agent_result(chapter_review, "ReviewerAgent", "review_chapter")
            deterministic_quality = quality_gate.evaluate(
                write_result.get('content', ''),
                review_score=chapter_review.get('score', 0),
                evidence_chars=len(wiki_context) + len(research_evidence),
                visual_asset_count=len(chart_files),
                target_words=book_config.chapter_word_count,
                word_tolerance=writing_spec.word_count_policy.tolerance,
                min_visual_assets=writing_spec.visual_policy.min_assets_per_chapter,
            )
            chapter_review["deterministic_quality"] = deterministic_quality.__dict__
            chapter_review["score"] = min(chapter_review.get("score", 0) or 0, deterministic_quality.score)
            if deterministic_quality.issues:
                chapter_review["issues"] = (chapter_review.get("issues") or []) + deterministic_quality.issues
            PipelineCheckpointStore.mark(actions, "review_chapter", "completed", f"score={chapter_review.get('score', 0)}")
            if checkpoint_store:
                checkpoint_store.save(i, actions, {"stage": "review_chapter", "score": chapter_review.get('score', 0)})
            update_book_status(i, "review_chapter", "running", {
                "pipeline_id": self.pipeline_id,
                "review_score": chapter_review.get('score', 0),
            })

            if await self._check_pause_cancel('review_chapter', {}):
                break

            content = write_result.get('content', '')
            if chapter_review.get('score', 0) < 80 and chapter_review.get('issues'):
                PipelineCheckpointStore.mark(actions, "revise_chapter", "running")
                self._emit('phase_progress', {
                    'phase': 'revise',
                    'current_item': i,
                    'total_items': total_chapters,
                    'item_label': f'第{i}章 修订润色',
                })
                revise_result = await self.reviser.run({
                    'content': content,
                    'score': chapter_review.get('score', 0),
                    'issues': chapter_review.get('issues', []),
                    'mode': 'spot-fix',
                    'chapter_number': i,
                    'writing_spec': generation_contract,
                })
                revise_result = self._ensure_agent_result(revise_result, "ReviserAgent", "revise_chapter")
                content = revise_result.get('revised_content', content)
                PipelineCheckpointStore.mark(actions, "revise_chapter", "completed", f"{len(content)} chars")
            else:
                PipelineCheckpointStore.mark(actions, "revise_chapter", "skipped", "review score passed")
            if checkpoint_store:
                checkpoint_store.save(i, actions, {"stage": "revise_chapter"})

            if self._should_polish_chapter(content, chapter_review, book_config.style):
                self._emit('phase_progress', {
                    'phase': 'revise',
                    'current_item': i,
                    'total_items': total_chapters,
                    'item_label': f'第{i}章 润色',
                })

                PipelineCheckpointStore.mark(actions, "polish_chapter", "running")
                polish_result = await self.polisher.run({
                    'content': content,
                    'style': book_config.style,
                    'writing_spec': generation_contract,
                    'chapter_number': i,
                })
                polish_result = self._ensure_agent_result(polish_result, "PolisherAgent", "polish_chapter")
                final_content = polish_result.get('polished_content', content)
                PipelineCheckpointStore.mark(actions, "polish_chapter", "completed", f"{len(final_content)} chars")
            else:
                final_content = content
                PipelineCheckpointStore.mark(actions, "polish_chapter", "skipped", "review quality gate passed")
            if checkpoint_store:
                checkpoint_store.save(i, actions, {"stage": "polish_chapter"})
            final_metrics = measure_content(final_content)
            update_book_status(i, "polish_chapter", "running", {
                "pipeline_id": self.pipeline_id,
                "final_metrics": final_metrics.to_dict(),
            })

            if await self._check_pause_cancel('revise', {}):
                break

            if self.memory_manager:
                mgr = self.memory_manager.get_truth_manager(book_id)
                PipelineCheckpointStore.mark(actions, "persist_chapter", "running")
                if persistence:
                    self._emit('phase_progress', {
                        'phase': 'persist',
                        'current_item': i,
                        'total_items': total_chapters,
                        'item_label': f'第{i}章 持久化',
                    })
                    persistence.save_chapter(i, final_content, metadata={
                        'word_count': final_metrics.effective_word_count,
                        'metrics': final_metrics.to_dict(),
                        'review_score': chapter_review.get('score', 0),
                        'quality': chapter_review.get('deterministic_quality', {}),
                        'visual_decisions': visual_decisions,
                        'knowledge_diagnostics': wiki_diagnostics,
                        'outline_hash': TruthFileManager.content_hash(outline_text),
                    })
                mgr.append_chapter_summary(i, f'第{i}章', final_content[:200])
                mgr.update_progress(i, total_chapters)
                PipelineCheckpointStore.mark(actions, "persist_chapter", "completed", "chapter saved")
                if checkpoint_store:
                    checkpoint_store.save(i, actions, {"stage": "persist_chapter", "word_count": final_metrics.effective_word_count})
                update_book_status(i, "persist_chapter", "running", {
                    "pipeline_id": self.pipeline_id,
                    "word_count": final_metrics.effective_word_count,
                    "metrics": final_metrics.to_dict(),
                    "review_score": chapter_review.get('score', 0),
                })

            scheduler.mark_completed(i)
            completed_chapters.append({
                'chapter_number': i,
                'word_count': final_metrics.effective_word_count,
                'review_score': chapter_review.get('score', 0),
            })

        results['chapters'] = completed_chapters

        if await self._check_pause_cancel('write_loop', results):
            return results

        self._emit('phase_start', {'phase': 'persist', 'phase_label': self.PHASE_LABELS['persist'], 'agent': 'Persistor'})
        if self.memory_manager:
            mgr = self.memory_manager.get_truth_manager(book_id)
            mgr.save_snapshot()
            if persistence:
                persistence.create_snapshot()
            update_book_status(None, "pipeline_completed", "completed", {"pipeline_id": self.pipeline_id})
        self._emit('phase_complete', {'phase': 'persist', 'result_summary': f'{len(completed_chapters)}章已持久化'})

        self._emit('pipeline_complete', {
            'book_id': book_id,
            'total_chapters': len(completed_chapters),
        })

        return results

    def pause(self):
        self._paused = True
        self._cancel_event.set()
        self._emit('pipeline_pause', {'pipeline_id': self.pipeline_id})

    def resume(self):
        self._paused = False
        self._cancel_event.clear()
        self._emit('pipeline_resume', {'pipeline_id': self.pipeline_id})

    def cancel(self):
        self._cancelled = True
        self._cancel_event.set()
        self._emit('pipeline_error', {'phase': 'current', 'error': 'Cancelled by user'})

