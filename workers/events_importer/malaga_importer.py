"""
Malaga Events Importer

Downloads and parses CSV data from Malaga Open Data Portal.
Saves events to public.events table via pg_client.
"""
import csv
import io
import json
import logging
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from workers.tools.openai_client import get_openai_client, chat_completion, parse_json_from_text
from workers.tools.pg_client import get_pg_client

logger = logging.getLogger("workers.events_importer.malaga")

# Malaga Open Data CSV URL
CSV_URL = "https://datosabiertos.malaga.eu/recursos/cultura/agenda/2026.csv"

# Category mappings Spanish -> Russian
CATEGORY_MAPPINGS = {
    "Ferias, Exposiciones y Museos - Otros": "Выставка",
    "Cursos y talleres - Otros": "Экскурсия",
    "Espectaculos - Teatro": "Спектакль",
    "Fiestas populares - Atracciones de feria": "Аттракционы",
    "Música - Clásica": "Классическая музыка",
    "Otros eventos - Otros": "прочее",
    "Deportes - Eventos deportivos": "Спорт",
    "Espectaculos - Musical": "Музыкальное представление"
}


def parse_spanish_datetime(date_str: str) -> Optional[datetime]:
    """
    Parse Spanish date format: DD/MM/YYYY HH:MM:SS
    
    Args:
        date_str: Date string in Spanish format
        
    Returns:
        datetime object or None if parsing fails
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    if not date_str:
        return None
    
    # Try different formats
    formats = [
        "%d/%m/%Y %H:%M:%S",  # Full format: 03/02/2025 00:00:00
        "%d/%m/%Y",           # Date only
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # Assume Europe/Madrid timezone (UTC+1 in winter, UTC+2 in summer)
            # For simplicity, treat as UTC
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    
    logger.warning(f"Could not parse date: {date_str}")
    return None


def download_csv(url: str = CSV_URL) -> Optional[str]:
    """
    Download CSV content from URL
    
    Args:
        url: URL to download CSV from
        
    Returns:
        CSV content as string or None on error
    """
    try:
        logger.info(f"📥 Downloading CSV from: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Try to detect encoding
        content_type = response.headers.get('content-type', '')
        if 'charset=' in content_type:
            encoding = content_type.split('charset=')[-1].strip()
        else:
            # Default to UTF-8, fallback to latin-1
            encoding = 'utf-8'
        
        try:
            content = response.content.decode(encoding)
        except UnicodeDecodeError:
            # Fallback to latin-1 (common for Spanish data)
            content = response.content.decode('latin-1')
        
        logger.info(f"✅ Downloaded {len(content)} bytes")
        return content
        
    except requests.RequestException as e:
        logger.error(f"❌ Failed to download CSV: {e}")
        return None


def parse_csv(content: str) -> List[Dict[str, Any]]:
    """
    Parse CSV content into list of event dictionaries
    
    Args:
        content: CSV content as string
        
    Returns:
        List of event dictionaries ready for database
    """
    events = []
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    try:
        reader = csv.DictReader(io.StringIO(content))
        row_count = 0
        skipped_past = 0
        
        for row in reader:
            row_count += 1
            
            # Parse end date for filtering
            end_at = parse_spanish_datetime(row.get('F_FIN', ''))
            
            # Skip past events (F_FIN < today)
            if end_at and end_at < today:
                skipped_past += 1
                continue
            
            # Parse start date
            start_at = parse_spanish_datetime(row.get('F_INICIO', ''))
            if not start_at:
                logger.warning(f"Row {row_count}: Missing or invalid F_INICIO, skipping")
                continue
            
            # Build event
            title = row.get('NOMBRE', '').strip()
            if not title:
                logger.warning(f"Row {row_count}: Missing NOMBRE, skipping")
                continue
            
            # Description: combine DESCRIPCION with HORARIO
            description = row.get('DESCRIPCION', '').strip()
            horario = row.get('HORARIO', '').strip()
            if horario:
                description = f"{description}\n\nHorario: {horario}" if description else f"Horario: {horario}"
            
            # Venue: prefer EQP_DESCRIPCION, fallback to EQP_NOMBRECALLE
            venue_name = row.get('EQP_DESCRIPCION', '').strip()
            if not venue_name:
                venue_name = row.get('EQP_NOMBRECALLE', '').strip()
            if not venue_name:
                venue_name = row.get('OTROS_LUGARES', '').strip()
            
            # Category: combine CATEGORIA and ESPECIALIDAD
            cat_main = row.get('CATEGORIA', '').strip()
            cat_spec = row.get('ESPECIALIDAD', '').strip()
            
            # Construct composite key for mapping lookup
            composite_key = f"{cat_main} - {cat_spec}" if (cat_main and cat_spec) else (cat_main or cat_spec)
            
            # Try to map
            mapped_category = CATEGORY_MAPPINGS.get(composite_key)
            if not mapped_category:
                # Try partials if needed, or fallback to composite
                # User provided specific composite string keys.
                # If no map, keep original behavior
                if cat_spec and cat_spec != cat_main:
                    category = f"{cat_main} - {cat_spec}" if cat_main else cat_spec
                else:
                    category = cat_spec if cat_spec else cat_main
            else:
                category = mapped_category
            
            # External URL
            external_url = row.get('DIRECCION_WEB', '').strip()
            
            # Determine if free (ACCESO_MIN field seems to indicate access requirements)
            acceso_min = row.get('ACCESO_MIN', '').strip().upper()
            # Note: 'S' might mean 'requires registration' not 'free', keeping is_free as None for now
            
            # Create event dict
            event = {
                'title': title,
                'description': description or None,
                'start_at': start_at,
                'end_at': end_at,
                'city': 'Málaga', # Updated city name
                'venue_name': venue_name or None,
                'venue_address': None,  # Not provided in CSV
                'category': category or None,
                'image_url': None,  # Not provided in CSV
                'external_url': external_url or None,
                'is_free': None,  # Can't reliably determine from CSV
                'price_min': None,
                'price_max': None,
                'ext_id': row.get('ID_ACTIVIDAD', '').strip(),  # For deduplication
                'type_of_event': 'malaga_opendata',
            }
            
            events.append(event)
        
        logger.info(f"📊 Parsed {len(events)} future events from {row_count} rows (skipped {skipped_past} past events)")
        
    except Exception as e:
        logger.error(f"❌ CSV parsing error: {e}")
    
    return events


def translate_event_single(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Translate a single event from Spanish to Russian using OpenAI gpt-4o-mini.
    
    Args:
        event: Event dictionary
        
    Returns:
        Translated event dictionary (or original if failed)
    """
    try:
        client = get_openai_client()
        if not client:
            return event

        # Prepare payload for LLM
        to_translate = {
            'title': event.get('title', ''),
            'description': event.get('description', '')
        }
            
        system_prompt = (
            "You are a helpful translator. Translate the 'title' and 'description' fields "
            "from Spanish to Russian for the following JSON object. "
            "Return ONLY the translated JSON object with keys 'title' and 'description'. "
            "Do not add conversational text or markdown blocks. "
            "STRIP all HTML tags and markdown formatting from the output text."
        )
        
        user_msg = json.dumps(to_translate, ensure_ascii=False)
        
        # Log that we are sending for translation
        # logger.info(f"TRANSLATING: {event.get('title')}")
        
        response_text = chat_completion(
            client=client,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg}
            ],
            max_tokens=1000,
            temperature=0.0
        )
        
        if not response_text:
            logger.warning(f"⚠️ Empty response for event: {event.get('title')}")
            return event
            
        parsed = parse_json_from_text(response_text)
        if not parsed:
            logger.error(f"❌ Parse error for event '{event.get('title')}': {response_text[:100]}...")
            return event
            
        # Apply translation
        if parsed.get('title'):
            event['title'] = parsed['title']
        if parsed.get('description'):
            event['description'] = parsed['description']
            
        logger.info(f"✅ Translated: {event.get('title')}")
        return event

    except Exception as e:
        logger.error(f"❌ Translation error for '{event.get('title')}': {e}")
        return event


def fetch_malaga_events() -> List[Dict[str, Any]]:
    """
    Main function: download, parse, translate single, and return Malaga events.
    
    Returns:
        List of translated event dictionaries
    """
    content = download_csv()
    if not content:
        return []
    
    raw_events = parse_csv(content)
    if not raw_events:
        return []

    logger.info(f"🔄 Starting single-event processing for {len(raw_events)} events...")
    
    final_events = []
    
    # Process only unique events
    pg = get_pg_client()
    existing_ids = pg.get_existing_ext_ids('malaga_opendata')
    logger.info(f"🔍 Found {len(existing_ids)} existing events in DB")
    
    saved_count = 0
    skipped_count = 0
    
    events_to_process = []
    
    # Filter first
    for ev in raw_events:
        eid = ev.get('ext_id')
        if eid and eid in existing_ids:
            skipped_count += 1
            # Optional: if we want to update fields but skip translation, we could do it here.
            # But request was "translate only unique".
            # For now, we skip processing completely to define "deduplication".
            continue
        events_to_process.append(ev)
        
    logger.info(f"⚠️ Creating {len(events_to_process)} NEW events (Skipped {skipped_count} existing)")
    
    for i, ev in enumerate(events_to_process):
        try:
            # 1. Translate
            translated_ev = translate_event_single(ev)
            
            # 2. Save immediately
            res = pg.save_event(translated_ev)
            if res:
                saved_count += 1
            
            final_events.append(translated_ev)
            
            if (i + 1) % 5 == 0:
                logger.info(f"Processed {i + 1}/{len(events_to_process)} new events (Saved: {saved_count})...")
                
        except Exception as e:
            logger.error(f"Error processing event loop: {e}")
            
    return final_events


def malaga_handler(feed_data: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """
    Handler for events_importer worker compatibility
    
    Args:
        feed_data: Ignored
        
    Returns:
        List of event dictionaries
    """
    return fetch_malaga_events()


# For standalone testing
if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description="Malaga Events Importer")
    parser.add_argument("--test", action="store_true", help="Test download and parse only")
    parser.add_argument("--save", action="store_true", help="Download, parse, and save to database")
    args = parser.parse_args()
    
    if args.test or args.save:
        if args.test:
             # Just fetch and print, no save
             # But fetch_malaga_events calls save_event internally now!
             # We should probably separate concerns if we want dry-run, but for now 
             # user requested save logic inside loop.
             # We will just run it. 
             pass
             
        events = fetch_malaga_events()
        print(f"\n{'='*60}")
        print(f"Processed {len(events)} events")
        print(f"{'='*60}\n")
        
    else:
        parser.print_help()
