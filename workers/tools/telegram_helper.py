"""Utility helpers for sending messages to Telegram with Bot client fallback.

Provides small wrapper functions used by PublisherWorker and other code paths.
"""
from __future__ import annotations

import os
import requests
from typing import Optional, Dict, Any
import inspect
import asyncio


def _http_post(token: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f'https://api.telegram.org/bot{token}/{method}'
    resp = requests.post(url, json=payload, timeout=30)
    j = resp.json()
    if not (resp.status_code == 200 and j.get('ok')):
        raise RuntimeError(f'Telegram {method} failed: {j}')
    return j.get('result')


def create_forum_topic(chat_id: str, name: str, token: Optional[str] = None, icon_color: Optional[int] = None) -> Dict[str, Any]:
    """Create a forum topic in a forum-enabled chat (supergroup with topics).

    Returns the created topic (result) or raises on failure.
    """
    token = token or os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('No TELEGRAM_BOT_TOKEN provided')

    # Bot library support
    try:
        from telegram import Bot
        bot = Bot(token=token)
        # python-telegram-bot names this method create_forum_topic (>=13.4/20); use bot.create_forum_topic
        res = bot.create_forum_topic(chat_id=chat_id, name=name, icon_color=icon_color)
        # If library returns a coroutine (async API), run it synchronously when possible
        try:
            if inspect.iscoroutine(res):
                loop = None
                try:
                    loop = asyncio.get_event_loop()
                except Exception:
                    loop = None
                if loop and loop.is_running():
                    # Can't run coroutine synchronously when loop is running; fallback to HTTP
                    raise RuntimeError('Event loop running; falling back to HTTP')
                # run until complete
                return (loop.run_until_complete(res) if loop else asyncio.run(res))
        except Exception:
            # fallback to HTTP path below
            pass
        return res
    except Exception:
        # Fallback to HTTP method name: createForumTopic
        payload = {'chat_id': chat_id, 'name': name}
        if icon_color is not None:
            payload['icon_color'] = int(icon_color)
        return _http_post(token, 'createForumTopic', payload)


def send_message(chat_id: str, text: str, token: Optional[str] = None, parse_mode: str = 'HTML', reply_to_message_id: Optional[int] = None, message_thread_id: Optional[int] = None) -> Dict[str, Any]:
    """Send text message to Telegram. Returns result dict or raises.

    Supports replying to a message via `reply_to_message_id`.
    """
    token = token or os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('No TELEGRAM_BOT_TOKEN provided')

    # Try python-telegram-bot if available
    try:
        from telegram import Bot
        bot = Bot(token=token)
        res = bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id, message_thread_id=message_thread_id)
        try:
            if inspect.iscoroutine(res):
                loop = None
                try:
                    loop = asyncio.get_event_loop()
                except Exception:
                    loop = None
                if loop and loop.is_running():
                    # Can't await here; fall back to HTTP
                    raise RuntimeError('Event loop running; falling back to HTTP')
                return (loop.run_until_complete(res) if loop else asyncio.run(res))
        except Exception:
            # fall back to HTTP below
            pass
        return res
    except Exception:
        # Fallback to HTTP
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
        if reply_to_message_id is not None:
            payload['reply_to_message_id'] = int(reply_to_message_id)
        if message_thread_id is not None:
            payload['message_thread_id'] = int(message_thread_id)
        return _http_post(token, 'sendMessage', payload)


def send_photo(chat_id: str, photo_url: str, caption: Optional[str] = None, token: Optional[str] = None, parse_mode: str = 'HTML', message_thread_id: Optional[int] = None) -> Dict[str, Any]:
    """Send photo by URL to Telegram. Returns result dict or raises."""
    token = token or os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('No TELEGRAM_BOT_TOKEN provided')

    try:
        from telegram import Bot
        bot = Bot(token=token)
        res = bot.send_photo(chat_id=chat_id, photo=photo_url, caption=caption, parse_mode=parse_mode, message_thread_id=message_thread_id)
        try:
            if inspect.iscoroutine(res):
                loop = None
                try:
                    loop = asyncio.get_event_loop()
                except Exception:
                    loop = None
                if loop and loop.is_running():
                    # Can't await here; fall back to HTTP
                    raise RuntimeError('Event loop running; falling back to HTTP')
                return (loop.run_until_complete(res) if loop else asyncio.run(res))
        except Exception:
            # fall back to HTTP below
            pass
        return res
    except Exception:
        payload = {'chat_id': chat_id, 'photo': photo_url}
        if caption:
            payload['caption'] = caption
            payload['parse_mode'] = parse_mode
        if message_thread_id is not None:
            payload['message_thread_id'] = int(message_thread_id)
        return _http_post(token, 'sendPhoto', payload)


def post_eval_comment(chat_id: str, eval_json: Dict[str, Any], raw_text: Optional[str] = None, sent: Optional[Dict[str, Any]] = None, token: Optional[str] = None, max_len: int = 1000) -> Optional[Dict[str, Any]]:
    """Post evaluation as a forum comment where possible.

    Behavior:
    - Try to post into the channel's linked discussion group when `sent` is a channel post.
    - Else, try to create a forum topic and post into it.
    - If both fail, do nothing (no reply or thread posting fallback).

    Returns the Telegram result dict when a message was sent, or a structured error dict when posting failed.
    """
    token = token or os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('No TELEGRAM_BOT_TOKEN provided')

    # No posting into existing threads: we will only attempt channel-linked discussion
    # or create a forum topic. This intentionally avoids replying inside threads.

    # Prepare text to send
    text_to_send = raw_text or ''
    try:
        import json as _json
        if not text_to_send:
            text_to_send = _json.dumps(eval_json, ensure_ascii=False, indent=2)
    except Exception:
        if not text_to_send:
            text_to_send = str(eval_json)

    brief = None
    try:
        brief = f"Оценка перевода: {eval_json.get('total_score_percent') if isinstance(eval_json, dict) else 'N/A'}% — подробности в базе."
    except Exception:
        brief = "Оценка перевода: подробности в базе."

    # If we have a thread id, post there
    # Special case: if this was a channel post, attempt to post into the channel's linked discussion group
    try:
        # determine if sent indicates a channel post
        is_channel = False
        channel_username = None
        channel_id = None
        if isinstance(sent, dict):
            chat_info = sent.get('chat') or sent.get('sender_chat') or {}
            if isinstance(chat_info, dict) and chat_info.get('type') == 'channel':
                is_channel = True
                channel_username = chat_info.get('username')
                channel_id = chat_info.get('id')
        if is_channel:
            # Try to get linked_chat_id from getChat
            try:
                res = _http_post(token, 'getChat', {'chat_id': chat_id})
            except Exception:
                res = None
            linked_chat_id = None
            if isinstance(res, dict):
                linked_chat_id = res.get('linked_chat_id')

            if linked_chat_id:
                # construct a brief comment and include a link to the channel post if possible
                post_link = None
                try:
                    if channel_username:
                        # public channel link
                        post_id = None
                        try:
                            post_id = sent.get('message_id') or (sent.get('message') or {}).get('message_id') or (sent.get('result') or {}).get('message_id')
                        except Exception:
                            post_id = None
                        if post_id:
                            post_link = f"https://t.me/{channel_username}/{post_id}"
                    else:
                        # private channel — use internal c/ link form if possible
                        post_id = None
                        try:
                            post_id = sent.get('message_id') or (sent.get('message') or {}).get('message_id') or (sent.get('result') or {}).get('message_id')
                        except Exception:
                            post_id = None
                        if post_id and isinstance(channel_id, int):
                            # transform -100<id> to numeric for c/ links: remove -100 prefix
                            cid = str(channel_id)
                            if cid.startswith('-100'):
                                short = cid[4:]
                                post_link = f"https://t.me/c/{short}/{post_id}"

                except Exception:
                    post_link = None

                comment_text = brief
                if post_link:
                    comment_text = f"{brief}\n\n{post_link}"

                try:
                    if len(text_to_send or '') > max_len:
                        return send_message(linked_chat_id, comment_text, token=token)
                    # include the full eval text when it's short
                    return send_message(linked_chat_id, (text_to_send if len(text_to_send or '') <= max_len else comment_text), token=token)
                except Exception as e:
                    return {'error': 'post_failed', 'reason': str(e)}
    except Exception:
        # non-fatal, continue to normal flow
        pass

    
    # Note: intentionally skipping posting into existing threads
    # Else try to create a forum topic and post there
    try:
        topic = create_forum_topic(chat_id, name=f"Оценка перевода", token=token)
        topic_id = None
        try:
            topic_id = getattr(topic, 'message_thread_id', None) or (topic or {}).get('message_thread_id')
        except Exception:
            topic_id = None

        if topic_id:
            try:
                if len(text_to_send or '') > max_len:
                    return send_message(chat_id, brief, token=token, message_thread_id=topic_id)
                return send_message(chat_id, text_to_send, token=token, message_thread_id=topic_id)
            except Exception as e:
                return {'error': 'post_failed', 'reason': str(e)}
    except Exception:
        # creation failed — per request, do not fallback to replying
        return {'error': 'create_topic_failed', 'reason': 'topic creation failed or API not supported'}

    return None
