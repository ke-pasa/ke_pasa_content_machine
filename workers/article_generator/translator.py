import json
import re
import logging
import html
import os
import unicodedata
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from .prompts import (
    stage1_messages,
    stage2_messages,
    stage3_messages,
    stage6_messages,
)

_logger = logging.getLogger('workers.article_generator.translator')
_logger.propagate = True

# Constants
STAGE_NAMES = ('stage1', 'stage2', 'stage3', 'stage5', 'stage6')


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


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


def _chat_completion(
    client: Any,
    model: str,
    messages: list,
    max_tokens: int = 6000,
    reasoning_effort: Optional[str] = None,
) -> Optional[str]:
    if worker_mod := _get_worker_module():
        if hasattr(worker_mod, 'chat_completion'):
            return worker_mod.chat_completion(
                client,
                model,
                messages,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
    from workers.tools.openai_client import chat_completion as _cc
    return _cc(
        client,
        model,
        messages,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )


def _parse_json_from_text(text: str) -> Optional[Dict]:
    if worker_mod := _get_worker_module():
        if hasattr(worker_mod, 'parse_json_from_text'):
            return worker_mod.parse_json_from_text(text)
    from workers.tools.openai_client import parse_json_from_text
    return parse_json_from_text(text)


def _extract_system_user_from_messages(messages: list) -> tuple:
    """Extract system and user prompts from messages list for Azure fallback."""
    system_prompt = ''
    user_prompt = ''
    if isinstance(messages, list) and messages:
        for m in messages:
            if isinstance(m, dict) and m.get('role') == 'system':
                system_prompt += m.get('content', '') + '\n'
        last = messages[-1]
        user_prompt = last.get('content') if isinstance(last, dict) else str(last)
    return system_prompt.strip(), user_prompt


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


def _yaml_quote(value: Any) -> str:
    """Return a JSON-compatible quoted scalar, which is safe in YAML frontmatter."""
    if value is None:
        value = ''
    return json.dumps(str(value), ensure_ascii=False)


def _slugify(value: str, fallback: str = 'article') -> str:
    translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    text = ''.join(translit.get(ch, ch) for ch in str(value or '').lower())
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = re.sub(r'-{2,}', '-', text).strip('-')
    return text or fallback


def _date_hint_to_frontmatter_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return datetime.fromisoformat(text.replace('Z', '+00:00')).date().isoformat()
        except Exception:
            if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
                return text
    return datetime.now(timezone.utc).date().isoformat()


def _build_publish_markdown(stage4_result: Dict, metadata: Dict) -> Dict:
    title = (stage4_result.get('title') or '').strip()
    dek = (stage4_result.get('dek') or '').strip()
    body = (stage4_result.get('body') or '').strip()
    doc_id = str((metadata or {}).get('doc_id') or 'article')
    slug = _slugify(title, fallback=doc_id)
    source_url = (metadata or {}).get('url') or (metadata or {}).get('link') or ''
    source_feed = (
        (metadata or {}).get('source_name')
        or (metadata or {}).get('source_feed')
        or (metadata or {}).get('feed_name')
        or (metadata or {}).get('source')
        or 'источник'
    )
    image = (metadata or {}).get('image_url') or (metadata or {}).get('image') or ''
    pub_date = _date_hint_to_frontmatter_date(
        (metadata or {}).get('published_at')
        or (metadata or {}).get('pub_date')
        or stage4_result.get('pubDate')
    )
    category = (metadata or {}).get('category') or stage4_result.get('category') or ''
    region = (metadata or {}).get('region') or stage4_result.get('region') or 'Spain'
    try:
        score = float((metadata or {}).get('total_score') or 0.0)
    except Exception:
        score = 0.0

    entity_names = []
    for entity in stage4_result.get('entities') or []:
        if isinstance(entity, dict) and entity.get('name'):
            entity_names.append(str(entity.get('name')))
    keywords = list(dict.fromkeys(entity_names[:8]))

    frontmatter = [
        '---',
        f'title: {_yaml_quote(title)}',
        f'description: {_yaml_quote(dek)}',
        f'pubDate: {_yaml_quote(pub_date)}',
        'author: "Auto-Editorial"',
        'tags: []',
        f'category: {_yaml_quote(category)}',
        f'slug: {_yaml_quote(slug)}',
        f'image: {_yaml_quote(image)}',
        f'region: {_yaml_quote(region)}',
        'seo:',
        f'  title: {_yaml_quote(title)}',
        f'  description: {_yaml_quote(dek)}',
        f'  keywords: {json.dumps(keywords, ensure_ascii=False)}',
        f'score: {score:.2f}',
        '---',
        '',
    ]

    source_line = ''
    if source_url:
        safe_url = html.escape(str(source_url), quote=True)
        safe_feed = html.escape(str(source_feed), quote=False)
        source_line = f'\n\nОригинал: <a href="{safe_url}" target="_blank">{safe_feed}</a>'
    else:
        flags = list(stage4_result.get('flags') or [])
        flags.append('Missing source URL for original link')
        stage4_result['flags'] = list(dict.fromkeys(flags))

    return {
        'publish_md': '\n'.join(frontmatter) + body + source_line,
        'slug': slug,
        'flags': stage4_result.get('flags') or [],
    }


def _maybe_save_stage_record(doc_id: str, metadata: Dict, stages: Dict):
    """If metadata['save_stages'] is truthy, write a plain text file with
    parsed stage JSON and raw texts for inspection.

    The file path is `logs/article_generator_stages/{doc_id}.txt`.
    This replaces the previous JSON output.
    """
    try:
        from pathlib import Path
        # Only save when the caller provided the explicit flag in metadata
        if not metadata or not metadata.get('save_stages'):
            return

        repo_root = Path(__file__).resolve().parent.parent.parent
        text_dir = repo_root / 'logs' / 'article_generator_stages'
        text_dir.mkdir(parents=True, exist_ok=True)
        out_file = text_dir / f"{str(doc_id)}.txt"

        with out_file.open('w', encoding='utf-8') as f:
            f.write(f"doc_id: {doc_id}\n")
            f.write(f"source_link: {metadata.get('url') or metadata.get('link') or metadata.get('source') or ''}\n\n")
            # For each stage write INPUT, OUTPUT (PARSED), OUTPUT (RAW), and MESSAGES
            for stage_name in STAGE_NAMES:
                # Input
                f.write(f"=== {stage_name} INPUT ===\n")
                inp = stages.get(f"{stage_name}_input") if isinstance(stages, dict) else None
                try:
                    if inp is None:
                        f.write('<NO INPUT SAVED>\n')
                    else:
                        f.write(json.dumps(inp, ensure_ascii=False, indent=2) + '\n')
                except Exception:
                    f.write('<INPUT NOT SERIALIZABLE>\n')
                f.write('\n')

                # Output (Parsed)
                parsed = stages.get(stage_name) if isinstance(stages, dict) else None
                f.write(f"=== {stage_name} OUTPUT (PARSED) ===\n")
                try:
                    if parsed is None:
                        f.write('<NO PARSED DATA>\n')
                    else:
                        f.write(json.dumps(parsed, ensure_ascii=False, indent=2) + '\n')
                except Exception:
                    f.write('<PARSED NOT SERIALIZABLE>\n')
                f.write('\n')

                # Output (Raw)
                f.write(f"=== {stage_name} OUTPUT (RAW) ===\n")
                raw = stages.get(f"{stage_name}_raw") if isinstance(stages, dict) else None
                try:
                    if raw is None:
                        f.write('<NO RAW OUTPUT SAVED>\n')
                    else:
                        if isinstance(raw, str):
                            f.write(raw + '\n')
                        else:
                            f.write(json.dumps(raw, ensure_ascii=False, indent=2) + '\n')
                except Exception:
                    f.write('<RAW OUTPUT NOT SERIALIZABLE>\n')
                f.write('\n')

                # Messages
                f.write(f"=== {stage_name} MESSAGES ===\n")
                msgs = stages.get(f"{stage_name}_messages") if isinstance(stages, dict) else None
                try:
                    if msgs is None:
                        f.write('<NO MESSAGES SAVED>\n')
                    else:
                        f.write(json.dumps(msgs, ensure_ascii=False, indent=2) + '\n')
                except Exception:
                    f.write('<MESSAGES NOT SERIALIZABLE>\n')
                f.write('\n')
    except Exception:
        _logger.exception('Failed to save stage text file for %s', doc_id)


class ArticleTranslator:
    """Encapsulates multi-stage translation of article fields to Russian via OpenAI."""

    def __init__(
        self,
        client=None,
        model: str = 'gpt-5.4-mini',
        stage1_max_tokens: int = 1800,
        stage2_max_tokens: int = 2500,
        stage3_max_tokens: int = 3500,
        stage4_max_tokens: int = 6000,
    ) -> None:
        self.client = client if client is not None else _get_openai_client()
        self.model = model
        self.stage1_max_tokens = stage1_max_tokens
        self.stage2_max_tokens = stage2_max_tokens
        self.stage3_max_tokens = stage3_max_tokens
        # Kept for backward compatibility with callers that still pass this option.
        self.stage4_max_tokens = stage4_max_tokens
        self.stage6_max_tokens = 2000
        # Token tracking
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_tokens = 0
        # Store the messages/prompts used for each stage for debugging
        self._last_stage_messages = {}
        # Store input/output collections for each stage
        self._last_stage_io = {}

    def _save_stage_io(self, stage_name: str, input_data: dict = None, raw_output: str = None, messages: list = None):
        """Safely save input/output/messages for a stage."""
        try:
            if messages is not None:
                self._last_stage_messages[f'{stage_name}_messages'] = messages
            if input_data is not None:
                self._last_stage_io[f'{stage_name}_input'] = input_data
            if raw_output is not None:
                self._last_stage_io[f'{stage_name}_raw'] = raw_output
        except Exception:
            pass

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
        """Execute compact translation pipeline.

        LLM stages:
        1) factual extraction
        2) article draft
        3) independent validation and final revision

        Stage 5 is deterministic markdown assembly. Stage 6 remains an optional
        LLM call for Telegram/video assets when the source article is publishable.
        """
        import time
        doc_id = metadata.get('doc_id', 'unknown')
        _logger.info('[%s] Starting translation pipeline', doc_id)
        
        source_text = self._build_source_text(title, description, content)

        _logger.info('[%s] Stage 1: Translation...', doc_id)
        t0 = time.time()
        stage1, raw1 = self._stage1_translate(title, description, content, metadata)
        _logger.info('[%s] Stage 1 completed in %.1fs', doc_id, time.time() - t0)
        if not stage1 or not isinstance(stage1, dict):
            _logger.warning('[%s] Stage 1 failed', doc_id)
            return (stage1, None, None, None, None, None, {'stage1': raw1})

        _logger.info('[%s] Stage 2: Reporter style...', doc_id)
        t0 = time.time()
        stage2, raw2 = self._stage2_reporter(stage1, metadata)
        _logger.info('[%s] Stage 2 completed in %.1fs', doc_id, time.time() - t0)
        if not stage2 or not isinstance(stage2, dict):
            _logger.warning('[%s] Stage 2 failed', doc_id)
            return (stage1, stage2, None, None, None, None, {'stage1': raw1, 'stage2': raw2})

        _logger.info('[%s] Stage 3: Validate and revise...', doc_id)
        t0 = time.time()
        stage3, raw3 = self._stage3_edit_first(stage1, stage2, source_text, metadata)
        _logger.info('[%s] Stage 3 completed in %.1fs', doc_id, time.time() - t0)
        if not stage3 or not isinstance(stage3, dict):
            _logger.warning('[%s] Stage 3 failed', doc_id)
            return (stage1, stage2, stage3, None, None, None, {'stage1': raw1, 'stage2': raw2, 'stage3': raw3})

        stage4 = stage3
        raw4 = None

        _logger.info('[%s] Stage 5: Build publish markdown...', doc_id)
        t0 = time.time()
        stage5, raw5 = self._stage5_publish_md(stage4, metadata)
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
            stage6, raw6 = self._stage6_telegram(stage4, metadata, slug)
            _logger.info('[%s] Stage 6 completed in %.1fs', doc_id, time.time() - t0)
        else:
            _logger.info('[%s] Stage6 skipped: total_score=%.1f (need >=%d), has_url=%s', 
                        doc_id, total_score_meta, PUBLISH_THRESHOLD, bool(metadata.get('url')))

        raws = {'stage1': raw1, 'stage2': raw2, 'stage3': raw3, 'stage4': raw4, 'stage5': raw5, 'stage6': raw6 if 'raw6' in locals() else None}
        return (stage1, stage2, stage3, stage4, stage5, stage6, raws)

    def _build_base_result(self, stage1: Dict, stage2: Dict, stage3: Dict, stage4: Dict) -> Dict:
        """Build base result dictionary with core translation fields."""
        final = {}
        # Stage 3 contains the approved final article body.
        final_body = stage4.get('body') or stage2.get('body')
        final['body_ru'] = final_body
        if final_body:
            final['translation_ru'] = final_body
        # pubDate (from stage1)
        final['pubDate'] = stage1.get('pubDate')
        # image (from stage1)
        if 'image' in stage1:
            final['image'] = stage1['image']
        return final
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
            if slug := stage5.get('slug'):
                final['slug'] = slug
            publish_flags = stage5.get('flags') or []
            if publish_flags:
                final['flags'] = list(dict.fromkeys((final.get('flags') or []) + publish_flags))
            final['publish_flags'] = publish_flags

    def _merge_stage6_results(self, final: Dict, stage6: Optional[Dict]) -> None:
        """Merge stage6 results into final output."""
        if isinstance(stage6, dict):
            if tg_preview := stage6.get('tg_preview'):
                final['tg_preview'] = tg_preview
            if video_script := stage6.get('video_script'):
                final['video_script'] = video_script
            tg_flags = stage6.get('flags') or []
            if tg_flags:
                final['flags'] = list(dict.fromkeys((final.get('flags') or []) + tg_flags))
            final['tg_flags'] = tg_flags
            final['stage6_telegram'] = stage6

    def translate(self, title: str, description: str, content: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Execute compact translation pipeline and merge results."""
        if not self.client:
            _logger.error('OpenAI client is not initialized')
            return None

        metadata = metadata or {}
        doc_id = metadata.get('doc_id', 'unknown')
        _logger.info(f'Starting translation for {doc_id}')
        
        pipeline_start = __import__('time').time()

        stage1, stage2, stage3, stage4, stage5, stage6, raws = self._execute_translation_pipeline(title, description, content, metadata)

        if not stage1 or not isinstance(stage1, dict):
            _logger.error(f'Stage1 failed for {doc_id}: stage1={stage1}')
            return stage1 if isinstance(stage1, dict) else None
        if not stage2 or not stage3 or not stage4:
            _logger.error(f'Translation pipeline failed for {doc_id}: stage2={bool(stage2)} stage3={bool(stage3)} stage4={bool(stage4)}')
            return None

        final = self._build_base_result(stage1, stage2, stage3, stage4)
        self._add_optional_fields(final, stage1, stage2, stage3, stage4)
        self._merge_stage5_results(final, stage5)
        self._merge_stage6_results(final, stage6)
        # Optionally save compact stage records for debugging/archival
        try:
            stages = {
                'stage1': stage1,
                'stage2': stage2,
                'stage3': stage3,
                'stage4': stage4,
                'stage5': stage5,
                'stage6': stage6,
            }
            try:
                # merge in any captured messages/prompts
                if isinstance(self._last_stage_messages, dict):
                    for k, v in self._last_stage_messages.items():
                        stages[k] = v
            except Exception:
                pass
            try:
                # merge in any captured input/output data
                if isinstance(self._last_stage_io, dict):
                    for k, v in self._last_stage_io.items():
                        stages[k] = v
            except Exception:
                pass
            _maybe_save_stage_record(metadata.get('doc_id', 'unknown'), metadata, stages)
        except Exception:
            _logger.exception('Error while trying to save stage record for %s', metadata.get('doc_id', 'unknown'))
        
        pipeline_duration = __import__('time').time() - pipeline_start
        _logger.info(f'[{doc_id}] Translation completed in {pipeline_duration:.1f}s (3 LLM stages)')

        return final

    def _stage1_translate(self, title: str, description: str, content: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        metadata = metadata or {}
        article_text = self._build_source_text(title, description, content)

        messages = stage1_messages(article_text)
        self._save_stage_io('stage1', input_data={'article_text': article_text}, messages=messages)
        _log_stage_debug('stage1', self.model, messages, len(article_text or ''))

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage1_max_tokens,
                reasoning_effort='low',
            )
        except Exception as e:
            _logger.exception(f'Stage1 chat_completion failed for {metadata.get("doc_id", "unknown")}: {e}')
            return None, None

        parsed = _parse_stage_response(text, 'stage1', (metadata or {}).get('doc_id', 'unknown'))
        self._save_stage_io('stage1', raw_output=text)
        return parsed, (text or None)

    def _stage2_reporter(self, stage1_result: Dict, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Stage 2: Create reporter-style text based on stage1 explanation and facts."""
        metadata = metadata or {}
        draft_json = json.dumps(stage1_result, ensure_ascii=False)

        messages = stage2_messages(draft_json)
        self._save_stage_io('stage2', input_data={'stage1_json': draft_json}, messages=messages)
        _log_stage_debug('stage2', self.model, messages, len(draft_json or ''))

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage2_max_tokens,
                reasoning_effort='low',
            )
        except Exception as e:
            _logger.exception(f'Stage2 chat_completion failed for {metadata.get("doc_id", "unknown")}: {e}')
            return None, None

        parsed = _parse_stage_response(text, 'stage2', metadata.get('doc_id', 'unknown'))
        self._save_stage_io('stage2', raw_output=text)
        return parsed, (text or None)

    def _stage3_edit_first(self, stage1_result: Dict, stage2_result: Dict, source_text: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Stage 3: Validate and finalize based on source_text, stage1, and stage2."""
        metadata = metadata or {}
        if not stage2_result:
            return None
        stage1_json = json.dumps(stage1_result, ensure_ascii=False)
        stage2_json = json.dumps(stage2_result, ensure_ascii=False)

        messages = stage3_messages(source_text, stage1_json, stage2_json)
        self._save_stage_io('stage3', 
                           input_data={'source_text': source_text, 'stage1_json': stage1_json, 'stage2_json': stage2_json},
                           messages=messages)
        _log_stage_debug('stage3', self.model, messages, len(stage2_json or ''))

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage3_max_tokens,
            )
        except Exception as e:
            _logger.exception(f'Stage3 chat_completion failed for {metadata.get("doc_id", "unknown")}: {e}')
            return None, None

        parsed = _parse_stage_response(text, 'stage3', metadata.get('doc_id', 'unknown'))
        self._save_stage_io('stage3', raw_output=text)
        return parsed, (text or None)

    def _stage5_publish_md(self, stage4_result: Dict, metadata: Dict) -> Optional[Dict]:
        """Stage 5: Build markdown article for website based on final article JSON."""
        metadata = metadata or {}
        if not stage4_result:
            return None

        try:
            result = _build_publish_markdown(stage4_result, metadata)
        except Exception as e:
            _logger.exception(f'Stage5 exception for doc_id={metadata.get("doc_id", "unknown")}: {e}')
            return None, None

        self._save_stage_io(
            'stage5',
            input_data={'stage4_json': json.dumps(stage4_result, ensure_ascii=False), 'metadata': metadata},
            raw_output=result.get('publish_md'),
            messages=[],
        )
        return result, (result.get('publish_md') or None)

    def _stage6_telegram(self, stage4_result: Dict, metadata: Dict, slug: Optional[str] = None) -> Optional[Dict]:
        """Stage 6: Generate telegram text based on stage4."""
        metadata = metadata or {}
        if not stage4_result:
            return None
        
        url = f"https://ke-pasa.es/news/{slug}/" if slug else (metadata.get('url') or metadata.get('link'))
        
        if not url:
            return None

        stage4_json = json.dumps(stage4_result, ensure_ascii=False)

        if _env_flag('ENABLE_VIDEO_GENERATION', default=False):
            messages = stage6_messages(stage4_json, url)
            max_tokens = self.stage6_max_tokens
        else:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a senior SMM editor for a Russian-language news outlet in Spain. "
                        "Write only a compact, factual Telegram news preview. Keep it neutral, "
                        "active, concrete, and free of hype. Use exactly 3 blocks: bold headline, "
                        "2-3 sentence core news paragraph, and 1 short practical consequence. "
                        "Do not add URLs. Return STRICT JSON only: {\"tg_preview\":\"...\"}."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Write a compact Telegram news preview from this final article data.\n\n"
                        f"{stage4_json}\n\nReturn STRICT JSON only: {{\"tg_preview\":\"...\"}}"
                    ),
                },
            ]
            max_tokens = 1000

        self._save_stage_io('stage6',
                           input_data={'stage4_json': stage4_json, 'url': url},
                           messages=messages)
        _log_stage_debug('stage6', self.model, messages, len(stage4_json or ''))

        try:
            _logger.info(f'Stage6 calling OpenAI for doc_id={metadata.get("doc_id", "unknown")}, '
                        f'messages={len(messages)}, max_tokens={max_tokens}')
            text = _chat_completion(
                client=self.client,
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                reasoning_effort='low',
            )
            if not text:
                _logger.error(f'Stage6 returned empty/None for doc_id={metadata.get("doc_id", "unknown")}. text={repr(text)}')
                return None, None
            _logger.info(f'Stage6 success for doc_id={metadata.get("doc_id", "unknown")}, response_len={len(text)}')
        except Exception as e:
            _logger.exception(f'Stage6 exception for doc_id={metadata.get("doc_id", "unknown")}: {e}')
            return None, None

        parsed = _parse_stage_response(text, 'stage6', metadata.get('doc_id', 'unknown'))
        self._save_stage_io('stage6', raw_output=text)
        if not parsed or not isinstance(parsed, dict):
            return parsed, (text or None)

        # Clean up tg_preview formatting
        if tg := parsed.get('tg_preview'):
            if isinstance(tg, str):
                tg = re.sub(r'<br\s*/?>', '\n', tg)
                tg = re.sub(r'\n{3,}', '\n\n', tg)
                parsed['tg_preview'] = tg

        # Clean up video_script formatting
        if script := parsed.get('video_script'):
            if isinstance(script, str):
                script = script.strip()
                # Remove any HTML tags that might have slipped in
                script = re.sub(r'<[^>]+>', '', script)
                # Clean up extra whitespace
                script = re.sub(r'\s+', ' ', script)
                parsed['video_script'] = script

        return parsed, (text or None)
