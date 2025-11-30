import json
from typing import Optional, Dict

from .prompts import (
    stage1_messages,
    stage2_messages,
    stage3_messages,
    stage4_messages,
    stage5_messages,
    stage6_messages,
)

# Ensure translator logger prints to console for local debugging
try:
    import logging as _logging
    _tlogger = _logging.getLogger('workers.article_generator.translator')
    if not any(isinstance(h, _logging.StreamHandler) for h in _tlogger.handlers):
        _ch = _logging.StreamHandler()
        _ch.setLevel(_logging.DEBUG)
        _ch.setFormatter(_logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        _tlogger.addHandler(_ch)
except Exception:
    pass


def _get_openai_client():
    try:
        import importlib
        worker_mod = importlib.import_module('workers.article_generator.worker')
        if hasattr(worker_mod, 'get_openai_client'):
            return worker_mod.get_openai_client()
    except Exception:
        pass
    from workers.tools.openai_client import get_openai_client as _go
    return _go()


def _chat_completion(client, model, messages, max_tokens=6000, temperature=0):
    try:
        import importlib
        worker_mod = importlib.import_module('workers.article_generator.worker')
        if hasattr(worker_mod, 'chat_completion'):
            return worker_mod.chat_completion(client, model, messages, max_tokens=max_tokens, temperature=temperature)
    except Exception:
        pass
    from workers.tools.openai_client import chat_completion as _cc
    return _cc(client, model, messages, max_tokens=max_tokens, temperature=temperature)


def _parse_json_from_text(text: str):
    try:
        import importlib
        worker_mod = importlib.import_module('workers.article_generator.worker')
        if hasattr(worker_mod, 'parse_json_from_text'):
            return worker_mod.parse_json_from_text(text)
    except Exception:
        pass
    from workers.tools.openai_client import parse_json_from_text
    return parse_json_from_text(text)


def _save_raw_response(doc_id: str, stage: str, text: str):
    # Previously this function saved the raw model output to disk.
    # Per request, stop writing files and instead log the raw output to the console
    try:
        import logging as _logging
        logger = _logging.getLogger('workers.article_generator.translator')
        # log stage and doc id, then the content at WARNING so it appears in CI logs
        logger.warning('Raw OpenAI output for %s stage=%s:\n%s', doc_id, stage, (text or '')[:20000])
        # If running in GitHub Actions, also write the raw text to the workspace so the workflow
        # can upload it as an artifact and you can download it from the Actions UI.
        try:
            import os
            from pathlib import Path
            gha = os.environ.get('GITHUB_ACTIONS')
            if gha and gha.lower() == 'true':
                gw = os.environ.get('GITHUB_WORKSPACE') or os.getcwd()
                log_dir = Path(gw) / 'logs' / 'openai_raw'
                log_dir.mkdir(parents=True, exist_ok=True)
                import time
                fname = log_dir / f"{doc_id}_{stage}_{int(time.time())}.txt"
                with fname.open('w', encoding='utf-8') as f:
                    f.write(text or '')
                logger.warning('Wrote CI raw OpenAI output to %s', str(fname))
                # Return the saved text for caller use (string)
                return text or None
        except Exception:
            # If writing fails, still return the raw text
            return text or None
        # Default return of raw text
        return text or None
    except Exception:
        return None


class ArticleTranslator:
    """Encapsulates multi-stage translation of article fields to Russian via OpenAI."""

    def __init__(
        self,
        client=None,
        model: str = 'gpt-5-mini',  # Default model
        stage1_max_tokens: int = 8000,
        stage2_max_tokens: int = 8000,
        stage3_max_tokens: int = 8000,
        stage1_temperature: float = 0.2,
        stage2_temperature: float = 0.4,
        stage3_temperature: float = 1.0,
    ) -> None:
        self.client = client if client is not None else _get_openai_client()
        self.model = model
        self.stage1_max_tokens = stage1_max_tokens
        self.stage2_max_tokens = stage2_max_tokens
        self.stage1_temperature = stage1_temperature
        self.stage2_temperature = stage2_temperature
        self.stage3_max_tokens = stage3_max_tokens
        self.stage3_temperature = stage3_temperature

    def _execute_translation_pipeline(self, title: str, description: str, content: str, metadata: Dict) -> tuple:
        """
        Execute 6-stage translation pipeline.
        
        Returns:
            tuple: (stage1, stage2, stage3, stage4, stage5, stage6) or early exit with partial results
        """
        # Build source text for stage3 evaluation
        source_parts = []
        if title:
            source_parts.append(f"Заголовок: {title}")
        if description:
            source_parts.append(f"Описание: {description}")
        if content:
            source_parts.append(f"Текст: {content}")
        source_text = '\n\n'.join(source_parts).strip()

        # STAGE 1: structured analysis
        stage1 = self._stage1_translate(title, description, content, metadata)
        if not stage1 or not isinstance(stage1, dict):
            return (stage1, None, None, None, None, None)

        # STAGE 2: human reportage based on stage1
        stage2 = self._stage2_reporter(stage1, metadata)
        if not stage2 or not isinstance(stage2, dict):
            return (stage1, None, None, None, None, None)

        # STAGE 3: editorial evaluation based on source_text, stage1, stage2
        stage3 = self._stage3_edit_first(stage1, stage2, source_text, metadata)
        if not stage3 or not isinstance(stage3, dict):
            return (stage1, stage2, None, None, None, None)

        # STAGE 4: final article creation based on source_text, stage1, stage2, stage3
        stage4 = self._stage4_edit_final(stage1, stage2, stage3, source_text, metadata)
        if not stage4 or not isinstance(stage4, dict):
            return (stage1, stage2, stage3, None, None, None)

        # STAGE 5: markdown version for site based on stage4
        stage5 = self._stage5_publish_md(stage4, metadata)

        # STAGE 6: telegram text based on stage4 (conditional on score and URL)
        stage6 = None
        try:
            total_score_meta = float(metadata.get('total_score', 0))
        except Exception:
            total_score_meta = 0.0
        if total_score_meta >= 80 and metadata.get('url'):
            # Pass slug from stage5 to stage6
            slug = None
            if stage5 and isinstance(stage5, dict):
                slug = stage5.get('slug')
            stage6 = self._stage6_telegram(stage4, metadata, slug)

        return (stage1, stage2, stage3, stage4, stage5, stage6)

    def _extract_fallback_field(self, field_name: str, stage4: Dict, stage3: Dict, stage2: Dict, stage1: Dict) -> Optional[str]:
        """Extract field value with fallback chain through stages."""
        for stage in (stage4, stage3, stage2, stage1):
            if stage and field_name in stage:
                return stage[field_name]
        return None

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
        """Add optional split fields (title_ru, description_ru, content_ru) with fallback logic."""
        # title_ru with fallback (stage2 and stage4 use 'title', stage3 is evaluation)
        title_ru = stage4.get('title') or stage2.get('title')
        if title_ru:
            final['title_ru'] = title_ru

        # description_ru with fallback (stage2 and stage4 use 'dek', stage3 is evaluation)
        description_ru = stage4.get('dek') or stage2.get('dek')
        if description_ru:
            final['description_ru'] = description_ru

        # content_ru with fallback (stage2 and stage4 use 'body', stage3 is evaluation)
        content_ru = stage4.get('body') or stage2.get('body')
        if content_ru:
            final['content_ru'] = content_ru
        else:
            final['content_ru'] = final.get('translation_ru', '')

    def _merge_stage5_results(self, final: Dict, stage5: Optional[Dict]) -> None:
        """Merge stage5 (markdown) results into final output."""
        if isinstance(stage5, dict):
            publish_md = stage5.get('publish_md')
            if publish_md:
                final['publish_md'] = publish_md
            publish_flags = stage5.get('flags') or []
            if publish_flags:
                combined_flags = list(dict.fromkeys((final.get('flags') or []) + publish_flags))
                final['flags'] = combined_flags
            final['publish_flags'] = publish_flags

    def _merge_stage6_results(self, final: Dict, stage6: Optional[Dict]) -> None:
        """Merge stage6 (telegram) results into final output."""
        if isinstance(stage6, dict):
            tg_preview = stage6.get('tg_preview')
            if tg_preview:
                final['tg_preview'] = tg_preview
            tg_flags = stage6.get('flags') or []
            if tg_flags:
                combined_flags = list(dict.fromkeys((final.get('flags') or []) + tg_flags))
                final['flags'] = combined_flags
            final['tg_flags'] = tg_flags
            final['stage6_telegram'] = stage6

    def translate(self, title: str, description: str, content: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """
        6-stage translation pipeline:
        stage1 - structured analysis (explanation_ru, facts_raw, actors)
        stage2 - human reportage (title, dek, body, facts, entities)
        stage3 - editorial evaluation (scores, rewrite_focus_points, detected_issues)
        stage4 - final article creation (title, dek, body, facts, entities, flags)
        stage5 - markdown for website with YAML frontmatter
        stage6 - telegram preview with HTML markup
        """
        if not self.client:
            return None

        metadata = metadata or {}

        # Execute translation pipeline
        stage1, stage2, stage3, stage4, stage5, stage6 = self._execute_translation_pipeline(title, description, content, metadata)

        # Handle early exits (parse errors or stage failures)
        if not stage1 or not isinstance(stage1, dict):
            return stage1 if isinstance(stage1, dict) else None
        if not stage2:
            return stage1
        if not stage3:
            return stage1  # Return stage1 as fallback
        if not stage4:
            return stage1  # Return stage1 as fallback

        # Build final result
        final = self._build_base_result(stage1, stage2, stage3, stage4)

        # Add optional fields with fallback logic
        self._add_optional_fields(final, stage1, stage2, stage3, stage4)

        # Merge stage5 (markdown) results
        self._merge_stage5_results(final, stage5)

        # Merge stage6 (telegram) results
        self._merge_stage6_results(final, stage6)

        return final

    def _stage1_translate(self, title: str, description: str, content: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        metadata = metadata or {}
        article_parts = []
        if title:
            article_parts.append(f"Заголовок: {title}")
        if description:
            article_parts.append(f"Описание: {description}")
        if content:
            article_parts.append(f"Текст: {content}")

        article_text = '\n\n'.join(article_parts).strip()

        messages = stage1_messages(article_text)

        # diagnostic logging to help debug request issues (400 responses)
        try:
            import logging as _logging
            _log = _logging.getLogger('workers.article_generator.translator')
            try:
                msg_count = len(messages)
            except Exception:
                msg_count = 0
            try:
                snippet = ''
                if msg_count and isinstance(messages, list) and isinstance(messages[-1], dict):
                    c = messages[-1].get('content', '')
                    if not isinstance(c, str):
                        c = str(c)
                    snippet = (c[:300] + '...') if len(c) > 300 else c
            except Exception:
                snippet = '<<unavailable>>'
            _log.debug('Translator stage1: model=%s messages=%d article_text_len=%d snippet=%s', self.model, msg_count, len(article_text or ''), snippet[:300])
        except Exception:
            pass

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage1_max_tokens,
                temperature=self.stage1_temperature,
            )
        except Exception:
            return None

        try:
            parsed = _parse_json_from_text(text or '')
            if parsed is None or not isinstance(parsed, dict):
                # Save raw response for debugging when parse fails
                doc_id = (metadata or {}).get('doc_id', 'unknown')
                raw_text = _save_raw_response(doc_id, 'stage1', text or '')
                # Return a sentinel dict indicating parse failed and include raw text
                if raw_text:
                    return {'_parse_error': True, '_raw_text': raw_text}
                return None
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _stage2_reporter(self, stage1_result: Dict, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Stage 2: Create reporter-style text based on stage1 explanation and facts."""
        metadata = metadata or {}
        draft_json = json.dumps(stage1_result, ensure_ascii=False)

        messages = stage2_messages(draft_json)
        try:
            import logging as _logging
            _log = _logging.getLogger('workers.article_generator.translator')
            try:
                msg_count = len(messages)
            except Exception:
                msg_count = 0
            try:
                snippet = ''
                if msg_count and isinstance(messages, list) and isinstance(messages[-1], dict):
                    c = messages[-1].get('content', '')
                    if not isinstance(c, str):
                        c = str(c)
                    snippet = (c[:300] + '...') if len(c) > 300 else c
            except Exception:
                snippet = '<<unavailable>>'
            _log.debug('Translator stage2: model=%s messages=%d draft_len=%d snippet=%s', self.model, msg_count, len(draft_json or ''), snippet[:300])
        except Exception:
            pass

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=self.stage2_max_tokens,
                temperature=self.stage2_temperature,
            )
        except Exception:
            return None

        try:
            parsed = _parse_json_from_text(text or '')
            if parsed is None or not isinstance(parsed, dict):
                doc_id = metadata.get('doc_id', 'unknown')
                raw_text = _save_raw_response(doc_id, 'stage2', text or '')
                if raw_text:
                    return {'_parse_error': True, '_raw_text': raw_text}
                return None
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _stage3_edit_first(self, stage1_result: Dict, stage2_result: Dict, source_text: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Stage 3: Editorial evaluation based on source_text, stage1, and stage2."""
        if not isinstance(stage2_result, dict):
            return None

        metadata = metadata or {}
        stage1_json = json.dumps(stage1_result, ensure_ascii=False)
        stage2_json = json.dumps(stage2_result, ensure_ascii=False)

        messages = stage3_messages(source_text, stage1_json, stage2_json)
        try:
            import logging as _logging
            _log = _logging.getLogger('workers.article_generator.translator')
            try:
                msg_count = len(messages)
            except Exception:
                msg_count = 0
            try:
                snippet = ''
                if msg_count and isinstance(messages, list) and isinstance(messages[-1], dict):
                    c = messages[-1].get('content', '')
                    if not isinstance(c, str):
                        c = str(c)
                    snippet = (c[:300] + '...') if len(c) > 300 else c
            except Exception:
                snippet = '<<unavailable>>'
            _log.debug('Translator stage3: model=%s messages=%d payload_len=%d snippet=%s', self.model, msg_count, len(stage2_json or ''), snippet[:300])
        except Exception:
            pass

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

        try:
            parsed = _parse_json_from_text(text or '')
            if parsed is None or not isinstance(parsed, dict):
                doc_id = metadata.get('doc_id', 'unknown')
                raw_text = _save_raw_response(doc_id, 'stage3', text or '')
                if raw_text:
                    return {'_parse_error': True, '_raw_text': raw_text}
                return None
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _stage4_edit_final(self, stage1_result: Dict, stage2_result: Dict, stage3_result: Dict, source_text: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        """Stage 4: Final article creation based on source_text, stage1, stage2, and stage3 evaluation."""
        if not isinstance(stage3_result, dict):
            return None

        metadata = metadata or {}
        stage1_json = json.dumps(stage1_result, ensure_ascii=False)
        stage2_json = json.dumps(stage2_result, ensure_ascii=False)
        stage3_json = json.dumps(stage3_result, ensure_ascii=False)

        messages = stage4_messages(source_text, stage1_json, stage2_json, stage3_json)
        try:
            import logging as _logging
            _log = _logging.getLogger('workers.article_generator.translator')
            try:
                msg_count = len(messages)
            except Exception:
                msg_count = 0
            try:
                snippet = ''
                if msg_count and isinstance(messages, list) and isinstance(messages[-1], dict):
                    c = messages[-1].get('content', '')
                    if not isinstance(c, str):
                        c = str(c)
                    snippet = (c[:300] + '...') if len(c) > 300 else c
            except Exception:
                snippet = '<<unavailable>>'
            _log.debug('Translator stage4: model=%s messages=%d payload_len=%d snippet=%s', self.model, msg_count, len(stage3_json or ''), snippet[:300])
        except Exception:
            pass

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

        try:
            parsed = _parse_json_from_text(text or '')
            if parsed is None or not isinstance(parsed, dict):
                doc_id = metadata.get('doc_id', 'unknown')
                raw_text = _save_raw_response(doc_id, 'stage4', text or '')
                if raw_text:
                    return {'_parse_error': True, '_raw_text': raw_text}
                return None
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _stage5_publish_md(self, stage4_result: Dict, metadata: Dict) -> Optional[Dict]:
        """Stage 5: Generate markdown article for website based on stage4."""
        if not isinstance(stage4_result, dict):
            return None

        metadata = metadata or {}

        # Build tech_meta for frontmatter
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
        try:
            import logging as _logging
            _log = _logging.getLogger('workers.article_generator.translator')
            try:
                msg_count = len(messages)
            except Exception:
                msg_count = 0
            try:
                snippet = ''
                if msg_count and isinstance(messages, list) and isinstance(messages[-1], dict):
                    c = messages[-1].get('content', '')
                    if not isinstance(c, str):
                        c = str(c)
                    snippet = (c[:300] + '...') if len(c) > 300 else c
            except Exception:
                snippet = '<<unavailable>>'
            _log.debug('Translator stage5: model=%s messages=%d payload_len=%d snippet=%s', self.model, msg_count, len(stage4_json or ''), snippet[:300])
        except Exception:
            pass

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

        # Stage5 returns raw Markdown, not JSON
        if text:
            result = {'publish_md': text.strip()}
            # Extract slug from YAML frontmatter for use in Stage 6
            try:
                import re
                slug_match = re.search(r'^slug:\s*(.+?)\s*$', text, re.MULTILINE)
                if slug_match:
                    result['slug'] = slug_match.group(1).strip()
            except Exception:
                pass
            return result
        return None

    def _stage6_telegram(self, stage4_result: Dict, metadata: Dict, slug: Optional[str] = None) -> Optional[Dict]:
        """Stage 6: Generate telegram text based on stage4."""
        if not isinstance(stage4_result, dict):
            return None

        metadata = metadata or {}
        
        # Use slug to build ke-pasa.es URL if available, otherwise fall back to original URL
        is_own_site = False
        if slug:
            url = f"https://ke-pasa.es/news/{slug}/"
            is_own_site = True
        else:
            url = metadata.get('url') or metadata.get('link')
        
        if not url:
            return None

        stage4_json = json.dumps(stage4_result, ensure_ascii=False)

        messages = stage6_messages(stage4_json, url, is_own_site)

        try:
            import logging as _logging
            _log = _logging.getLogger('workers.article_generator.translator')
            try:
                msg_count = len(messages)
            except Exception:
                msg_count = 0
            try:
                snippet = ''
                if msg_count and isinstance(messages, list) and isinstance(messages[-1], dict):
                    c = messages[-1].get('content', '')
                    if not isinstance(c, str):
                        c = str(c)
                    snippet = (c[:300] + '...') if len(c) > 300 else c
            except Exception:
                snippet = '<<unavailable>>'
            _log.debug('Translator stage6: model=%s messages=%d payload_len=%d snippet=%s', self.model, msg_count, len(stage4_json or ''), snippet[:300])
        except Exception:
            pass

        try:
            text = _chat_completion(
                self.client,
                self.model,
                messages,
                max_tokens=600,
                temperature=0.6,
            )
        except Exception:
            return None

        try:
            parsed = _parse_json_from_text(text or '')
            if parsed is None or not isinstance(parsed, dict):
                doc_id = metadata.get('doc_id', 'unknown')
                raw_text = _save_raw_response(doc_id, 'stage6', text or '')
                if raw_text:
                    return {'_parse_error': True, '_raw_text': raw_text}
                return None

            # Post-process tg_preview so stored preview doesn't contain <br> tags
            try:
                tg = parsed.get('tg_preview') if isinstance(parsed, dict) else None
                if isinstance(tg, str):
                    # replace common <br> variants with newlines
                    tg2 = tg.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
                    try:
                        # prefer using normalization helper if available
                        from workers.tools.telegram_helper import _normalize_newlines
                        tg2 = _normalize_newlines(tg2)
                    except Exception:
                        # fallback: collapse multiple blank lines
                        import re as _re
                        tg2 = _re.sub(r'\n{3,}', '\n\n', tg2)
                    parsed['tg_preview'] = tg2
            except Exception:
                # non-fatal: leave parsed as-is
                pass

            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
