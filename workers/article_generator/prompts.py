"""Prompt builders for article translation workflow.

This module loads per-stage prompt JSON files from a `prompts/` directory
located next to this file. Each JSON file contains two keys: "system" and
"user" containing the respective prompt texts. The functions below return
message lists in the same format as before: a system message and a user
message with placeholders replaced.
"""

from pathlib import Path
import json
from typing import List, Dict


PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt_file(filename: str) -> Dict[str, str]:
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    # simple in-memory cache to avoid reading files repeatedly
    if not hasattr(_load_prompt_file, "_cache"):
        _load_prompt_file._cache = {}
    cache = _load_prompt_file._cache
    key = str(path.resolve())
    if key in cache:
        return cache[key]
    text = path.read_text(encoding="utf-8")
    obj = json.loads(text)
    cache[key] = obj
    return obj


def clear_prompt_cache() -> None:
    """Clear the in-memory prompt cache (useful in tests or during development)."""
    if hasattr(_load_prompt_file, "_cache"):
        _load_prompt_file._cache.clear()


def _load_stage(stage: int) -> Dict[str, str]:
    return _load_prompt_file(f"stage{stage}.json")


def _load_eval() -> Dict[str, str]:
    return _load_prompt_file("stage_eval.json")


def stage1_messages(article_text: str) -> List[Dict[str, str]]:
    prompts = _load_stage(1)
    system_prompt = prompts.get("system", "")
    user_template = prompts.get("user", "")
    user_content = user_template.replace("<<ARTICLE_TEXT>>", article_text)
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]


def stage2_messages(draft_json: str) -> List[Dict[str, str]]:
    prompts = _load_stage(2)
    system_prompt = prompts.get("system", "")
    user_template = prompts.get("user", "")
    user_content = user_template.replace("<<DRAFT_JSON>>", draft_json)
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]


def stage3_messages(source_text: str, stage1_json: str, stage2_json: str) -> List[Dict[str, str]]:
    prompts = _load_stage(3)
    system_prompt = prompts.get("system", "")
    user_template = prompts.get("user", "")
    user_content = (user_template
                    .replace("<<SOURCE_TEXT>>", source_text)
                    .replace("<<STAGE1_JSON>>", stage1_json)
                    .replace("<<STAGE2_JSON>>", stage2_json))
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]


def stage4_messages(source_text: str, stage1_json: str, stage2_json: str, stage3_json: str) -> List[Dict[str, str]]:
    prompts = _load_stage(4)
    system_prompt = prompts.get("system", "")
    user_template = prompts.get("user", "")
    user_content = (user_template
                    .replace("<<SOURCE_TEXT>>", source_text)
                    .replace("<<STAGE1_JSON>>", stage1_json)
                    .replace("<<STAGE2_JSON>>", stage2_json)
                    .replace("<<STAGE3_JSON>>", stage3_json))
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]


def stage5_messages(stage4_json: str, tech_meta_json: str) -> List[Dict[str, str]]:
    prompts = _load_stage(5)
    system_prompt = prompts.get("system", "")
    user_template = prompts.get("user", "")
    user_content = (user_template
                    .replace("<<STAGE4_JSON>>", stage4_json)
                    .replace("<<TECH_META>>", tech_meta_json))
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]


def stage6_messages(stage4_json: str, url: str, is_own_site: bool = False) -> List[Dict[str, str]]:
    prompts = _load_stage(6)
    system_prompt = prompts.get("system", "")
    user_template = prompts.get("user", "")
    link_type = "OWN_SITE" if is_own_site else "ORIGINAL"
    user_content = (user_template
                    .replace("<<STAGE4_JSON>>", stage4_json)
                    .replace("<<URL>>", url)
                    .replace("<<LINK_TYPE>>", link_type))
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]


def stage_eval_messages(source_text_es: str, final_tg_text: str) -> List[Dict[str, str]]:
    prompts = _load_eval()
    system_prompt = prompts.get("system", "")
    user_template = prompts.get("user", "")
    user_content = user_template.replace("<<SOURCE_TEXT_ES>>", source_text_es).replace("<<FINAL_TG_TEXT>>", final_tg_text)
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]

