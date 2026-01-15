"""
Digest Worker (migrated to workers.digest)
"""
import sys
import os
import time
import json
import logging
import argparse
import importlib
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat
from datetime import datetime, timezone
from pathlib import Path
from croniter import croniter
import uuid

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from workers.tools.telegram_helper import send_message
from workers.tools.facebook_helper import post_facebook

# Configuration (local to package)
CONFIG_FILE = Path(__file__).parent / "digest_config.json"
STATE_FILE = Path(__file__).parent / "digest_state.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("workers.digest")

class DigestWorker:
    def __init__(self):
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.telegram_token:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set")
            
    def load_config(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
        return {"jobs": []}

    def load_state(self):
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_state(self, state):
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def execute_digest(self, script_module: str) -> str:
        """Dynamically imports module and calls generate_digest()"""
        try:
            logger.debug(f"Importing digest module {script_module}")
            module = importlib.import_module(script_module)
            importlib.reload(module)
            if hasattr(module, 'generate_digest'):
                try:
                    return module.generate_digest()
                except Exception as e:
                    logger.error(f"Error while running generate_digest(): {e}")
                    raise
            else:
                logger.error(f"Module {script_module} has no generate_digest function")
        except Exception:
            import traceback
            traceback.print_exc()
            logger.exception(f"Error executing script {script_module}")
        return None

    def _markdown_to_telegram_html(self, text: str) -> str:
        if not text:
            return ""
        import re
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        text = re.sub(r'^#+\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
        text = re.sub(r'^\s*\*\s+(.+)$', r'• \1', text, flags=re.MULTILINE)
        return text

    def _html_to_plain_text(self, html: str) -> str:
        """Конвертирует HTML в обычный текст для Facebook."""
        if not html:
            return ""
        import re
        # Убираем HTML теги
        text = re.sub(r'<b>(.*?)</b>', r'\1', html)
        text = re.sub(r'<i>(.*?)</i>', r'\1', text)
        text = re.sub(r'<a href="(.*?)">(.*?)</a>', r'\2', text)
        text = re.sub(r'<.*?>', '', text)
        # Убираем HTML entities
        text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        return text.strip()

    def _post_to_facebook(self, content: str):
        """Публикует дайджест в Facebook."""
        try:
            html_content = self._markdown_to_telegram_html(content)
            plain_text = self._html_to_plain_text(html_content)
            
            logger.info("Posting digest to Facebook...")
            result = post_facebook(
                message=plain_text,
                image_url=None  # Дайджест без изображения
            )
            
            if result and result.get('id'):
                logger.info(f"✅ Posted digest to Facebook: {result.get('id')}")
                return result
            else:
                logger.error(f"❌ Facebook post failed: {result}")
                return None
        except Exception as e:
            logger.error(f"❌ Error posting to Facebook: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _maybe_save_translation(self, job: dict, content: str):
        """If job or env enables saving translations, write content to a file.

        Saves into SAVE_TRANSLATIONS_DIR if set, otherwise into workers/digest/translations.
        Ensures a .gitignore exists in the translations folder so files are not accidentally committed.
        Returns path string or None.
        """
        if not content:
            return None

        save_flag = False
        try:
            save_flag = bool(job.get('save_translations', False))
        except Exception:
            save_flag = False

        if not save_flag:
            save_flag = os.getenv('SAVE_TRANSLATIONS', 'false').lower() in ('1', 'true', 'yes')
        if not save_flag:
            return None

        out_dir = os.getenv('SAVE_TRANSLATIONS_DIR')
        if out_dir:
            out_path = Path(out_dir)
        else:
            out_path = Path(__file__).parent / 'translations'

        try:
            out_path.mkdir(parents=True, exist_ok=True)
            # create a .gitignore so translations are not committed
            gi = out_path / '.gitignore'
            try:
                if not gi.exists():
                    gi.write_text("*\n!.gitignore\n", encoding='utf-8')
            except Exception:
                logger.debug('Could not write .gitignore in translations folder')

            job_id = job.get('id', 'unknown')
            ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            uid = uuid.uuid4().hex[:8]
            filename = out_path / f"{job_id}_{ts}_{uid}.md"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"💾 Saved translation for job '{job_id}' -> {filename}")
            return str(filename)
        except Exception as e:
            logger.error(f"Failed to save translation file: {e}")
            return None

    def publish_content(self, content: str, channels: list):
        if not content:
            logger.warning("No content generated to publish")
            return {}

        html_content = self._markdown_to_telegram_html(content)
        results = {}
        
        # Публикуем в Telegram
        for channel in channels:
            try:
                logger.info(f"Sending digest to {channel}...")
                res = send_message(channel, html_content, token=self.telegram_token, parse_mode='HTML')
                results[channel] = res
                logger.info(f"✅ Sent to {channel}")
            except Exception as e:
                results[channel] = None
                logger.error(f"❌ Failed to send to {channel}: {e}")
        
        # Публикуем в Facebook
        fb_result = self._post_to_facebook(content)
        results['facebook'] = fb_result
        
        return results

    def republish_content(self, content: str, republish_channels: list, original_results: dict = None):
        """Republish content as a user using Telethon to the provided channels.

        Requires TELETHON_API_ID and TELETHON_API_HASH env vars and a valid
        Telethon session file (or an already-authorized session name).
        """
        if not republish_channels:
            return

        api_id = os.getenv('TELETHON_API_ID')
        api_hash = os.getenv('TELETHON_API_HASH')
        session_name = os.getenv('TELETHON_SESSION', 'republish_session')

        if not api_id or not api_hash:
            logger.warning("Telethon credentials not set; skipping republish")
            return

        if TelegramClient is None:
            logger.error("Telethon not installed; cannot republish")
            return

        try:
            api_id_int = int(api_id)
        except Exception:
            logger.error("Invalid TELETHON_API_ID")
            return

        # If we have original send results, try to pick a source message to forward
        source_msg = None
        source_chat = None
        if original_results:
            for ch, res in (original_results or {}).items():
                if not res:
                    continue
                # extract message id and chat id robustly
                try:
                    msg_id = res.get('message_id') or (res.get('message') or {}).get('message_id')
                except Exception:
                    msg_id = None
                try:
                    chat_info = res.get('chat') or res.get('sender_chat') or {}
                    chat_id = chat_info.get('id') if isinstance(chat_info, dict) else None
                    # fallback: if chat id not present, use channel username if available
                    if not chat_id:
                        chat_id = chat_info.get('username') if isinstance(chat_info, dict) else None
                except Exception:
                    chat_id = None

                if msg_id and chat_id:
                    source_msg = int(msg_id)
                    source_chat = chat_id
                    break

        if not source_msg or not source_chat:
            logger.warning("No source message available to forward; skipping republish")
            return

        try:
            import asyncio

            async def _forward_async():
                async with TelegramClient(session_name, api_id_int, api_hash) as client:
                    try:
                        authorized = await client.is_user_authorized()
                        if not authorized:
                            logger.warning("Telethon client not authorized; skipping republish")
                            return

                        # Build list of target groups from the user's dialogs (exclude source and specific exceptions)
                        exclude_usernames = set()
                        # normalize source_chat to username if possible (could be id or username)
                        if isinstance(source_chat, str) and source_chat.startswith('@'):
                            exclude_usernames.add(source_chat.lstrip('@'))
                        elif isinstance(source_chat, str):
                            exclude_usernames.add(source_chat)

                        # Always exclude the main channel used for publishing (spain_kepasa)
                        exclude_usernames.add('spain_kepasa')

                        logger.info(f"Scanning user dialogs to find groups (excluding: {exclude_usernames})...")
                        targets = []  # Groups where forward is possible
                        send_only_targets = []  # Groups where only send_message is possible
                        
                        async for dialog in client.iter_dialogs():
                            ent = dialog.entity
                            uname = getattr(ent, 'username', None)
                            is_group = False
                            if isinstance(ent, Channel):
                                is_group = not getattr(ent, 'broadcast', False)
                            elif isinstance(ent, Chat):
                                is_group = True

                            if not is_group:
                                continue

                            # Skip excluded usernames
                            if uname and uname in exclude_usernames:
                                logger.debug(f"Skipping excluded group: @{uname}")
                                continue

                            # Check if we can forward or only send messages
                            can_send = True
                            can_forward = True
                            
                            if isinstance(ent, Channel):
                                banned_rights = getattr(ent, 'banned_rights', None)
                                if banned_rights:
                                    # banned_rights.send_messages == True means CANNOT send messages
                                    send_messages_banned = getattr(banned_rights, 'send_messages', False)
                                    if send_messages_banned:
                                        # Can't send regular messages, but we'll still try (might work for forwards)
                                        can_send = False
                                        can_forward = True  # We'll try forwarding anyway
                                        logger.debug(f"Group {uname or ent.id}: send_messages=true (banned), will try forward")

                            # Prefer username (with @) for target, else use id
                            target_id = f"@{uname}" if uname else ent.id
                            
                            # Add to appropriate list
                            if can_send:
                                targets.append(target_id)  # Normal groups - try forward
                            else:
                                send_only_targets.append(target_id)  # Restricted - try forward, fallback to send

                        logger.info(f"Found {len(targets)} groups for normal forward and {len(send_only_targets)} restricted groups to try")

                        # Get the original message text in case we need to copy it
                        original_message = None
                        try:
                            original_message = await client.get_messages(source_chat, ids=source_msg)
                        except Exception as e:
                            logger.warning(f"Could not fetch original message: {e}")

                        # Perform forwards for groups where it's normally allowed
                        for target in targets:
                            try:
                                logger.info(f"Forwarding message {source_msg} from {source_chat} to {target} as user...")
                                await client.forward_messages(target, source_msg, source_chat)
                                logger.info(f"✅ Forwarded to {target}")
                            except Exception as forward_error:
                                logger.error(f"Failed to forward to {target}: {forward_error}")
                                
                                # Try to send as regular message if forward failed
                                if original_message and original_message.text:
                                    try:
                                        logger.info(f"Attempting to send as regular message to {target}...")
                                        await client.send_message(target, original_message.text, link_preview=False)
                                        logger.info(f"✅ Sent as regular message to {target}")
                                    except Exception as send_error:
                                        logger.error(f"Failed to send regular message to {target}: {send_error}")
                        
                        # Try forwarding to restricted groups (where send_messages is banned)
                        # Sometimes forward works even when regular messages don't
                        if send_only_targets:
                            for target in send_only_targets:
                                try:
                                    logger.info(f"Trying forward to restricted group {target}...")
                                    await client.forward_messages(target, source_msg, source_chat)
                                    logger.info(f"✅ Forwarded to restricted group {target}")
                                except Exception as forward_error:
                                    logger.warning(f"Forward to restricted group {target} failed: {forward_error}")
                                    
                                    # Try sending as regular message anyway
                                    if original_message and original_message.text:
                                        try:
                                            logger.info(f"Attempting to send message to restricted group {target}...")
                                            await client.send_message(target, original_message.text, link_preview=False)
                                            logger.info(f"✅ Sent message to restricted group {target}")
                                        except Exception as send_error:
                                            logger.error(f"Cannot send to restricted group {target}: {send_error}")
                    except Exception as e:
                        logger.error(f"Telethon forward error: {e}")

            asyncio.run(_forward_async())
        except Exception as e:
            logger.error(f"Telethon error: {e}")

    def run_immediate(self, job_id, target_channel=None):
        logger.info(f"🚀 Manual run for job: {job_id}")
        config = self.load_config()
        job = next((j for j in config.get('jobs', []) if j['id'] == job_id), None)
        
        if not job:
            logger.error(f"Job {job_id} not found in config")
            return
        # Run the job: generate, publish, and optionally republish
        content = self.execute_digest(job['script_module'])
        if content:
            # Save translation/content if enabled (safe, with .gitignore)
            try:
                self._maybe_save_translation(job, content)
            except Exception:
                logger.debug('Failed to save translation in run_immediate')
            channels = [target_channel] if target_channel else job.get('channels', [])
            publish_results = self.publish_content(content, channels)
            # Republish as user if configured
            repub = job.get('republish', [])
            if repub:
                # Convert Markdown to HTML for Telethon and forward original message
                html_content = self._markdown_to_telegram_html(content)
                self.republish_content(html_content, repub, original_results=publish_results)
        else:
            logger.error("Failed to generate content")

    def run_daemon(self):
        logger.info("🕒 Starting Digest Worker Daemon")
        
        while True:
            try:
                config = self.load_config()
                state = self.load_state()
                now_utc = datetime.now(timezone.utc)
                logger.info(f"✓ Checking schedules at {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                
                for job in config.get('jobs', []):
                    if not job.get('enabled'):
                        logger.debug(f"  - Job '{job.get('id', 'unknown')}' is disabled, skipping")
                        continue
                    
                    job_id = job['id']
                    cron_expr = job['cron_schedule']
                    
                    if croniter.match(cron_expr, now_utc):
                        logger.info(f"  ⏰ Schedule matched for '{job_id}' ({cron_expr})")
                        last_run_iso = state.get(job_id, {}).get('last_run_iso')
                        already_run = False
                        if last_run_iso:
                            last_dt = datetime.fromisoformat(last_run_iso)
                            if (now_utc - last_dt).total_seconds() < 65:
                                already_run = True
                                logger.info(f"  ⏭️  Skipping '{job_id}' - already ran recently")
                                
                        if not already_run:
                            logger.info(f"  ▶️  Executing '{job_id}'...")
                            content = self.execute_digest(job['script_module'])
                            if content:
                                # Save translation/content if enabled for scheduled runs
                                try:
                                    self._maybe_save_translation(job, content)
                                except Exception:
                                    logger.debug('Failed to save translation in scheduled run')

                                publish_results = self.publish_content(content, job['channels'])
                                # Republish to additional channels as user if requested
                                repub = job.get('republish', [])
                                if repub:
                                    html_content = self._markdown_to_telegram_html(content)
                                    self.republish_content(html_content, repub, original_results=publish_results)
                                if job_id not in state: state[job_id] = {}
                                state[job_id]['last_run_iso'] = now_utc.isoformat()
                                self.save_state(state)
                                logger.info(f"  ✅ Completed '{job_id}'")
                    else:
                        iter_cron = croniter(cron_expr, now_utc)
                        next_run = iter_cron.get_next(datetime)
                        logger.info(f"  - Job '{job_id}' ({cron_expr}): next run at {next_run.strftime('%Y-%m-%d %H:%M UTC')}")

            except Exception as e:
                logger.error(f"Daemon loop error: {e}")
            
            sleep_time = 60 - time.time() % 60
            time.sleep(sleep_time)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Digest Worker")
    parser.add_argument("--run-now", help="ID of job to run immediately")
    parser.add_argument("--target-channel", help="Override target channel for immediate run")
    
    args = parser.parse_args()
    
    worker = DigestWorker()
    
    if args.run_now:
        worker.run_immediate(args.run_now, args.target_channel)
    else:
        worker.run_daemon()
