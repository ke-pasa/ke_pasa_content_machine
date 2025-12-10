import json
import re
import logging
from typing import Optional, Dict, Any

from .prompts import (
    stage1_messages,
    stage2_messages,
    stage3_messages,
    stage4_messages,
    stage5_messages,
    stage6_messages,
)

_logger = logging.getLogger('workers.article_generator.translator')
_logger.propagate = False


def _get_worker_module():
    """Load worker module if available for monkeypatching."""
    try:
        import importlib
        return importlib.import_module('workers.article_generator.worker')
    except Exception:
        return None


def _get_openai_client():
    if worker_mod := _get_worker_module():
        if hasattr(worker_mod, 'get_openai_client'):
            return worker_mod.get_openai_client()
    from workers.tools.openai_client import get_openai_client as _go
    return _go()


def _chat_completion(client: Any, model: str, messages: list, max_tokens: int = 6000, temperature: float = 0) -> Optional[str]:
    if worker_mod := _get_worker_module():
        if hasattr(worker_mod, 'chat_completion'):
            return worker_mod.chat_completion(client, model, messages, max_tokens=max_tokens, temperature=temperature)
    from workers.tools.openai_client import chat_completion as _cc
    return _cc(client, model, messages, max_tokens=max_tokens, temperature=temperature)


def _parse_json_from_text(text: str) -> Optional[Dict]:
    if worker_mod := _get_worker_module():
        if hasattr(worker_mod, 'parse_json_from_text'):
            return worker_mod.parse_json_from_text(text)
    from workers.tools.openai_client import parse_json_from_text
    return parse_json_from_text(text)


def _save_raw_response(doc_id: str, stage: str, text: str) -> Optional[str]:
    """Log raw OpenAI response; save to file if running in GitHub Actions."""
    try:
        _logger.warning('Raw OpenAI output for %s stage=%s:\n%s', doc_id, stage, (text or '')[:20000])
        
        import os
        from pathlib import Path
        if os.environ.get('GITHUB_ACTIONS', '').lower() == 'true':
            log_dir = Path(os.environ.get('GITHUB_WORKSPACE', os.getcwd())) / 'logs' / 'openai_raw'
            log_dir.mkdir(parents=True, exist_ok=True)
            import time
            fname = log_dir / f"{doc_id}_{stage}_{int(time.time())}.txt"
            fname.write_text(text or '', encoding='utf-8')
            _logger.warning('Wrote CI raw OpenAI output to %s', str(fname))
        
        return text or None
    except Exception:
        return None


def _log_stage_debug(stage: str, model: str, messages: list, payload_len: int):
    """Log debug info for translation stage."""
    try:
        msg_count = len(messages)
        snippet = ''
        if msg_count and isinstance(messages[-1], dict):
            content = str(messages[-1].get('content', ''))
            snippet = (content[:300] + '...') if len(content) > 300 else content
        _logger.debug('Translator %s: model=%s messages=%d payload_len=%d snippet=%s', 
                     stage, model, msg_count, payload_len, snippet[:300])
    except Exception:
        pass


def _parse_stage_response(text: str, stage: str, doc_id: str) -> Optional[Dict]:
    """Parse JSON response from stage, handle errors consistently."""
    try:
        parsed = _parse_json_from_text(text or '')
        if parsed is None or not isinstance(parsed, dict):
            raw_text = _save_raw_response(doc_id, stage, text or '')
            if raw_text:
                return {'_parse_error': True, '_raw_text': raw_text}
            return None
        return parsed
    except Exception:
        return None


class ArticleTranslator:
    """Encapsulates multi-stage translation of article fields to Russian via OpenAI."""

    def __init__(
        self,
        client=None,
        model: str = 'gpt-4o-mini',
        stage1_max_tokens: int = 800,
        stage2_max_tokens: int = 800,
        stage3_max_tokens: int = 800,
        stage1_temperature: float = 0.2,
        stage2_temperature: float = 0.4,
        stage3_temperature: float = 1.0,
    ) -> None:
        self.client = client if client is not None else _get_openai_client()
        self.model = model
        self.stage1_max_tokens = stage1_max_tokens
        self.stage2_max_tokens = stage2_max_tokens
        self.stage3_max_tokens = stage3_max_tokens
        self.stage1_temperature = stage1_temperature
        self.stage2_temperature = stage2_temperature
        self.stage3_temperature = stage3_temperature
        # Stage 4, 5, 6 use same params as stage 3
        self.stage4_max_tokens = stage3_max_tokens
        self.stage4_temperature = stage3_temperature
        self.stage5_max_tokens = stage3_max_tokens
        self.stage5_temperature = stage3_temperature
        self.stage6_max_tokens = stage3_max_tokens
        self.stage6_temperature = stage3_temperature
        # Token tracking
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_tokens = 0

    @staticmethod
    def _build_source_text(title: str, description: str, content: str) -> str:
        """Build formatted source text from article parts."""
        parts = []
        if title:
            parts.append(f"Заголовок: {title}")
        if description:
            parts.append(f"Описание: {description}")
        if content:
            parts.append(f"Текст: {content}")
        return '\n\n'.join(parts).strip()

    def _execute_translation_pipeline(self, title: str, description: str, content: str, metadata: Dict) -> tuple:
        """Execute 6-stage translation pipeline. Returns (stage1, stage2, stage3, stage4, stage5, stage6)."""
        import time
        doc_id = metadata.get('doc_id', 'unknown')
        _logger.info('[%s] Starting translation pipeline', doc_id)
        
        source_text = self._build_source_text(title, description, content)

        _logger.info('[%s] Stage 1: Translation...', doc_id)
        t0 = time.time()
        stage1 = self._stage1_translate(title, description, content, metadata)
        _logger.info('[%s] Stage 1 completed in %.1fs', doc_id, time.time() - t0)
        if not stage1 or not isinstance(stage1, dict):
            _logger.warning('[%s] Stage 1 failed', doc_id)
            return (stage1, None, None, None, None, None)

        _logger.info('[%s] Stage 2: Reporter style...', doc_id)
        t0 = time.time()
        stage2 = self._stage2_reporter(stage1, metadata)
        _logger.info('[%s] Stage 2 completed in %.1fs', doc_id, time.time() - t0)
        if not stage2 or not isinstance(stage2, dict):
            _logger.warning('[%s] Stage 2 failed', doc_id)
            return (stage1, None, None, None, None, None)

        _logger.info('[%s] Stage 3: Editorial evaluation...', doc_id)
        t0 = time.time()
        stage3 = self._stage3_edit_first(stage1, stage2, source_text, metadata)
        _logger.info('[%s] Stage 3 completed in %.1fs', doc_id, time.time() - t0)
        if not stage3 or not isinstance(stage3, dict):
            _logger.warning('[%s] Stage 3 failed', doc_id)
            return (stage1, stage2, None, None, None, None)

        _logger.info('[%s] Stage 4: Final edit...', doc_id)
        t0 = time.time()
        stage4 = self._stage4_edit_final(stage1, stage2, stage3, source_text, metadata)
        _logger.info('[%s] Stage 4 completed in %.1fs', doc_id, time.time() - t0)
        if not stage4 or not isinstance(stage4, dict):
            _logger.warning('[%s] Stage 4 failed', doc_id)
            return (stage1, stage2, stage3, None, None, None)

        _logger.info('[%s] Stage 5: Publish markdown...', doc_id)
        t0 = time.time()
        stage5 = self._stage5_publish_md(stage4, metadata)
        _logger.info('[%s] Stage 5 completed in %.1fs', doc_id, time.time() - t0)

        stage6 = None
        try:
            total_score_meta = float(metadata.get('total_score', 0))
        except Exception:
            total_score_meta = 0.0
        from workers.tools.constants import PUBLISH_THRESHOLD
        if total_score_meta >= PUBLISH_THRESHOLD and metadata.get('url'):
            _logger.info('[%s] Stage 6: Telegram preview (score=%.1f)...', doc_id, total_score_meta)
            t0 = time.time()
            slug = stage5.get('slug') if stage5 and isinstance(stage5, dict) else None
            stage6 = self._stage6_telegram(stage4, metadata, slug)
            _logger.info('[%s] Stage 6 completed in %.1fs', doc_id, time.time() - t0)
        else:
            _logger.info('[%s] Stage6 skipped: total_score=%.1f (need >=%d), has_url=%s', 
                        doc_id, total_score_meta, PUBLISH_THRESHOLD, bool(metadata.get('url')))

        return (stage1, stage2, stage3, stage4, stage5, stage6)

    def _build_base_result(self, stage1: Dict, stage2: Dict, stage3: Dict, stage4: Dict) -> Dict:
        """Build base result dictionary with core translation fields."""
        return {
            'translation_ru': stage4.get('body') or stage2.get('body') or stage1.get('explanation_ru') or '',
            'notes': stage4.get('notes') or stage2.get('notes') or [],
            'flags': stage4.get('flags') or stage2.get('flags') or [],
            'lang_detected': stage1.get('lang_detected') or 'es',
            'facts_raw': stage1.get('facts_raw', []),
            'actors': stage1.get('actors', []),
            'stage2_facts': stage2.get('facts', []),
            'stage2_entities': stage2.get('entities', []),
            'stage4_facts': stage4.get('facts', []),
            'stage4_entities': stage4.get('entities', []),
            'stage3_evaluation': stage3 if isinstance(stage3, dict) else {},
            'editorial_result': {
                'stage1': stage1,
                'stage2': stage2,
                'stage3': stage3,
                'stage4': stage4,
            },
        }

    def _add_optional_fields(self, final: Dict, stage1: Dict, stage2: Dict, stage3: Dict, stage4: Dict) -> None:
        """Add optional fields (title_ru, description_ru, content_ru) with fallback logic."""
        title_ru = stage4.get('title') or stage2.get('title')
        if title_ru:
            final['title_ru'] = title_ru

        description_ru = stage4.get('dek') or stage2.get('dek')
        if description_ru:
            final['description_ru'] = description_ru

        content_ru = stage4.get('body') or stage2.get('body')
        if content_ru:
            final['content_ru'] = content_ru
        else:
            final['content_ru'] = final.get('translation_ru', '')

    def _merge_stage5_results(self, final: Dict, stage5: Optional[Dict]) -> None:
        """Merge stage5 results into final output."""
        if isinstance(stage5, dict):
            if publish_md := stage5.get('publish_md'):
                final['publish_md'] = publish_md
            publish_flags = stage5.get('flags') or []
            if publish_flags:
                final['flags'] = list(dict.fromkeys((final.get('flags') or []) + publish_flags))
            final['publish_flags'] = publish_flags

    def _merge_stage6_results(self, final: Dict, stage6: Optional[Dict]) -> None:
        """Merge stage6 results into final output."""
        if isinstance(stage6, dict):
            if tg_preview := stage6.get('tg_preview'):
                final['tg_preview'] = tg_preview
            tg_flags = stage6.get('flags') or []
            if tg_flags:
                final['flags'] = list(dict.fromkeys((final.get('flags') or []) + tg_flags))
            final['tg_flags'] = tg_flags
            final['stage6_telegram'] = stage6

    def translate(self, title: str, description: str, content: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Execute 6-stage translation pipeline and merge results."""
        if not self.client:
            _logger.error('OpenAI client is not initialized')
            return None

        metadata = metadata or {}
        doc_id = metadata.get('doc_id', 'unknown')
        _logger.info(f'Starting translation for {doc_id}')
        
        pipeline_start = __import__('time').time()

        stage1, stage2, stage3, stage4, stage5, stage6 = self._execute_translation_pipeline(title, description, content, metadata)

        if not stage1 or not isinstance(stage1, dict):
            _logger.error(f'Stage1 failed for {doc_id}: stage1={stage1}')
            return stage1 if isinstance(stage1, dict) else None
        if not stage2 or not stage3 or not stage4:
            _logger.error(f'Translation pipeline failed for {doc_id}: stage2={bool(stage2)} stage3={bool(stage3)} stage4={bool(stage4)}')
            return stage1

        final = self._build_base_result(stage1, stage2, stage3, stage4)
        self._add_optional_fields(final, stage1, stage2, stage3, stage4)
        self._merge_stage5_results(final, stage5)
        self._merge_stage6_results(final, stage6)
        
        pipeline_duration = __import__('time').time() - pipeline_start
        _logger.info(f'[{doc_id}] Translation completed in {pipeline_duration:.1f}s (6 stages)')

        return final

    def _stage1_translate(self, title: str, description: str, content: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        metadata = metadata or {}
        article_text = self._build_source_text(title, description, content)

        messages = stage1_messages(article_text)
        _log_stage_debug('stage1', self.model, messages, len(article_text or ''))

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage1_max_tokens,
                temperature=self.stage1_temperature,
            )
        except Exception as e:
            _logger.exception(f'Stage1 chat_completion failed for {metadata.get("doc_id", "unknown")}: {e}')
            return None

        return _parse_stage_response(text, 'stage1', (metadata or {}).get('doc_id', 'unknown'))

    def _stage2_reporter(self, stage1_result: Dict, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Stage 2: Create reporter-style text based on stage1 explanation and facts."""
        metadata = metadata or {}
        draft_json = json.dumps(stage1_result, ensure_ascii=False)

        messages = stage2_messages(draft_json)
        _log_stage_debug('stage2', self.model, messages, len(draft_json or ''))

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage2_max_tokens,
                temperature=self.stage2_temperature,
            )
        except Exception as e:
            _logger.exception(f'Stage2 chat_completion failed for {metadata.get("doc_id", "unknown")}: {e}')
            return None

        return _parse_stage_response(text, 'stage2', metadata.get('doc_id', 'unknown'))

    def _stage3_edit_first(self, stage1_result: Dict, stage2_result: Dict, source_text: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Stage 3: Editorial evaluation based on source_text, stage1, and stage2."""
        metadata = metadata or {}
        if not stage2_result:
            return None
        stage1_json = json.dumps(stage1_result, ensure_ascii=False)
        stage2_json = json.dumps(stage2_result, ensure_ascii=False)

        messages = stage3_messages(source_text, stage1_json, stage2_json)
        _log_stage_debug('stage3', self.model, messages, len(stage2_json or ''))

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage3_max_tokens,
                temperature=self.stage3_temperature,
            )
        except Exception as e:
            _logger.exception(f'Stage3 chat_completion failed for {metadata.get("doc_id", "unknown")}: {e}')
            return None

        return _parse_stage_response(text, 'stage3', metadata.get('doc_id', 'unknown'))

    def _stage4_edit_final(self, stage1_result: Dict, stage2_result: Dict, stage3_result: Dict, source_text: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Stage 4: Final article creation based on source_text, stage1, stage2, and stage3 evaluation."""
        metadata = metadata or {}
        if not stage3_result:
            return None
        stage1_json = json.dumps(stage1_result, ensure_ascii=False)
        stage2_json = json.dumps(stage2_result, ensure_ascii=False)
        stage3_json = json.dumps(stage3_result, ensure_ascii=False)

        messages = stage4_messages(source_text, stage1_json, stage2_json, stage3_json)
        _log_stage_debug('stage4', self.model, messages, len(stage3_json or ''))

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage3_max_tokens,
                temperature=self.stage3_temperature,
            )
        except Exception:
            return None

        return _parse_stage_response(text, 'stage4', metadata.get('doc_id', 'unknown'))

    def _stage5_publish_md(self, stage4_result: Dict, metadata: Dict) -> Optional[Dict]:
        """Stage 5: Generate markdown article for website based on stage4."""
        metadata = metadata or {}
        if not stage4_result:
            return None

        tech_meta = {
            'source_url': metadata.get('url') or metadata.get('link') or '',
            'image_hint': metadata.get('image_url') or metadata.get('image') or '',
            'pub_date_hint': metadata.get('published_at') or metadata.get('pub_date') or None,
            'category_hint': metadata.get('category') or '',
            'region_hint': metadata.get('region') or 'unknown',
        }

        stage4_json = json.dumps(stage4_result, ensure_ascii=False)
        tech_meta_json = json.dumps(tech_meta, ensure_ascii=False)

        messages = stage5_messages(stage4_json, tech_meta_json)
        _log_stage_debug('stage5', self.model, messages, len(stage4_json or ''))

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage5_max_tokens,
                temperature=self.stage5_temperature,
            )
        except Exception as e:
            _logger.exception(f'Stage5 chat_completion failed for {metadata.get("doc_id", "unknown")}: {e}')
            return None

        if not text:
            return None
            
        result = {'publish_md': text.strip()}
        import re
        if slug_match := re.search(r'^slug:\s*(.+?)\s*$', text, re.MULTILINE):
            slug = slug_match.group(1).strip().strip('"').strip("'")
            result['slug'] = slug
        return result

    def _stage6_telegram(self, stage4_result: Dict, metadata: Dict, slug: Optional[str] = None) -> Optional[Dict]:
        """Stage 6: Generate telegram text based on stage4."""
        metadata = metadata or {}
        if not stage4_result:
            return None
        
        is_own_site = bool(slug)
        url = f"https://ke-pasa.es/news/{slug}/" if slug else (metadata.get('url') or metadata.get('link'))
        
        if not url:
            return None

        stage4_json = json.dumps(stage4_result, ensure_ascii=False)

        messages = stage6_messages(stage4_json, url, is_own_site)
        _log_stage_debug('stage6', self.model, messages, len(stage4_json or ''))

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=6000,
                temperature=0.6,
            )
        except Exception:
            return None

        parsed = _parse_stage_response(text, 'stage6', metadata.get('doc_id', 'unknown'))
        if not parsed or not isinstance(parsed, dict):
            return parsed

        if tg := parsed.get('tg_preview'):
            if isinstance(tg, str):
                tg = re.sub(r'<br\s*/?>', '\n', tg)
                tg = re.sub(r'\n{3,}', '\n\n', tg)
                parsed['tg_preview'] = tg

        return parsed
