import json
from typing import Optional, Dict

from .prompts import (
    stage1_messages,
    stage2_messages,
    stage3_messages,
    stage4_messages,
)


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


def _chat_completion(client, model, messages, max_tokens=1200, temperature=0):
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
    try:
        import time
        from pathlib import Path
        log_dir = Path(__file__).parent.parent.parent / 'logs' / 'openai_raw'
        log_dir.mkdir(parents=True, exist_ok=True)
        fname = log_dir / f"{doc_id}_{stage}_{int(time.time())}.txt"
        with fname.open('w', encoding='utf-8') as f:
            f.write(text or '')
        import logging as _logging
        _logging.getLogger('workers.article_generator.translator').warning('Saved raw OpenAI output for %s stage=%s to %s', doc_id, stage, str(fname))
    except Exception:
        pass


class ArticleTranslator:
    """Encapsulates multi-stage translation of article fields to Russian via OpenAI."""

    def __init__(
        self,
        client=None,
        model: str = 'gpt-5-mini',
        stage1_max_tokens: int = 1600,
        stage2_max_tokens: int = 1600,
        stage3_max_tokens: int = 1600,
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

    def translate(self, title: str, description: str, content: str, metadata: Optional[Dict] = None) -> Optional[Dict]:
        if not self.client:
            return None

        metadata = metadata or {}

        stage1 = self._stage1_translate(title, description, content)
        if not stage1 or not isinstance(stage1, dict):
            return stage1 if isinstance(stage1, dict) else None

        stage2 = self._stage2_edit(stage1)
        if not stage2 or not isinstance(stage2, dict):
            return stage1

        stage3 = self._stage3_publish(stage2, metadata)

        stage4 = None
        try:
            total_score_meta = float(metadata.get('total_score', 0))
        except Exception:
            total_score_meta = 0.0
        if total_score_meta >= 80 and metadata.get('url'):
            stage4 = self._stage4_telegram(stage2, metadata)

        # Ensure required fields present and fill fallbacks
        final = {
            'translation_ru': stage2.get('translation_ru') or stage1.get('translation_ru') or '',
            'notes': stage2.get('notes') or stage1.get('notes') or [],
            'flags': stage2.get('flags') or [],
            'lang_detected': stage2.get('lang_detected') or stage1.get('lang_detected') or 'es',
            'editorial_result': stage2,
        }

        # Provide optional split fields for compatibility
        if 'title_ru' in stage2:
            final['title_ru'] = stage2['title_ru']
        elif 'title_ru' in stage1:
            final['title_ru'] = stage1['title_ru']

        if 'description_ru' in stage2:
            final['description_ru'] = stage2['description_ru']
        elif 'description_ru' in stage1:
            final['description_ru'] = stage1['description_ru']

        if 'content_ru' in stage2:
            final['content_ru'] = stage2['content_ru']
        elif 'content_ru' in stage1:
            final['content_ru'] = stage1['content_ru']
        else:
            final['content_ru'] = final['translation_ru']

        if isinstance(stage3, dict):
            publish_md = stage3.get('publish_md')
            if publish_md:
                final['publish_md'] = publish_md
            publish_flags = stage3.get('flags') or []
            if publish_flags:
                combined_flags = list(dict.fromkeys((final.get('flags') or []) + publish_flags))
                final['flags'] = combined_flags
            final['publish_flags'] = publish_flags

        if isinstance(stage4, dict):
            tg_preview = stage4.get('tg_preview')
            if tg_preview:
                final['tg_preview'] = tg_preview
            tg_flags = stage4.get('flags') or []
            if tg_flags:
                combined_flags = list(dict.fromkeys((final.get('flags') or []) + tg_flags))
                final['flags'] = combined_flags
            final['tg_flags'] = tg_flags

        return final

    def _stage1_translate(self, title: str, description: str, content: str) -> Optional[Dict]:
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
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _stage4_telegram(self, stage2_result: Dict, metadata: Dict) -> Optional[Dict]:
        if not isinstance(stage2_result, dict):
            return None

        metadata = metadata or {}
        url = metadata.get('url') or metadata.get('link')
        if not url:
            return None

        payload = {
            'title': stage2_result.get('title_ru') or stage2_result.get('title') or '',
            'body': stage2_result.get('content_ru') or stage2_result.get('translation_ru') or '',
            'url': url,
        }

        stage2_json = json.dumps(payload, ensure_ascii=False)

        messages = stage4_messages(stage2_json)

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
            _log.debug('Translator stage4: model=%s messages=%d payload_len=%d snippet=%s', self.model, msg_count, len(stage2_json or ''), snippet[:300])
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
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _stage2_edit(self, stage1_result: Dict) -> Optional[Dict]:
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
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _stage3_publish(self, stage2_result: Dict, metadata: Dict) -> Optional[Dict]:
        if not isinstance(stage2_result, dict):
            return None

        metadata = metadata or {}

        article_payload = {
            'title': stage2_result.get('title_ru') or stage2_result.get('title') or '',
            'dek': stage2_result.get('description_ru') or stage2_result.get('dek') or '',
            'body': stage2_result.get('content_ru') or stage2_result.get('translation_ru') or '',
            'flags': stage2_result.get('flags') or [],
        }

        source_line = 'Источник: не указан'
        url = metadata.get('url') or metadata.get('link')
        source_name = metadata.get('source') or metadata.get('source_name')
        published_at = metadata.get('published_at') or metadata.get('pub_date') or metadata.get('published')
        if url:
            details = []
            if source_name:
                details.append(str(source_name))
            if published_at:
                details.append(str(published_at))
            if details:
                source_line = f"Источник: {url} ({', '.join(details)})"
            else:
                source_line = f"Источник: {url}"

        article_payload['source_line'] = source_line

        stage2_json = json.dumps(article_payload, ensure_ascii=False)

        messages = stage3_messages(stage2_json, source_line)
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
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
