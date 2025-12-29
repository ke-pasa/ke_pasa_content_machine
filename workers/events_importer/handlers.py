"""
RSS Feed Handlers for Events Importer

Each handler is a function that takes feed data and returns a list of event dicts.
"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger("workers.events_importer.handlers")


def default_handler(feed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Default RSS feed handler - extracts basic event info from RSS entries
    
    Args:
        feed_data: Parsed RSS feed data with 'entries' list
        
    Returns:
        List of event dictionaries ready for database insertion
    """
    events = []
    
    for entry in feed_data.get('entries', []):
        event = {
            'title': entry.get('title'),
            'description': entry.get('summary') or entry.get('description'),
            'start_at': entry.get('published') or entry.get('start_date'),
            'end_at': entry.get('end_date'),
            'city': entry.get('city') or 'Unknown',
            'venue_name': entry.get('venue') or entry.get('location'),
            'venue_address': entry.get('address'),
            'category': entry.get('category'),
            'image_url': entry.get('image') or entry.get('media_url'),
            'external_url': entry.get('link'),
            'is_free': entry.get('is_free', False),
            'price_min': entry.get('price_min'),
            'price_max': entry.get('price_max'),
        }
        
        # Only add if we have required fields
        if event['title'] and event['start_at'] and event['city']:
            events.append(event)
            logger.info(f"  📌 Extracted event: {event['title'][:50]}...")
        else:
            logger.warning(f"  ⚠️ Skipping entry - missing required fields")
    
    return events


# Registry of available handlers
HANDLERS = {
    'default_handler': default_handler,
    'malaga_handler': None, # Lazy loaded to avoid circular imports if needed, or import at top
}

def get_handler(handler_name: str):
    """
    Get handler function by name
    
    Args:
        handler_name: Name of the handler
        
    Returns:
        Handler function or None if not found
    """
    if handler_name == 'malaga_handler':
        from workers.events_importer.malaga_importer import malaga_handler
        return malaga_handler
        
    handler = HANDLERS.get(handler_name)
    if not handler:
        logger.warning(f"⚠️ Handler '{handler_name}' not found, using default_handler")
        return default_handler
    return handler
