"""
Instagram Image Processor
Prepares images for Instagram posts: resizes to 4:5 (1080x1350) and adds title overlay
"""
from __future__ import annotations

import os
import sys
import logging
import requests
import tempfile
from typing import Optional, Tuple
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

logger = logging.getLogger(__name__)


def _get_bebas_font(size: int) -> ImageFont.FreeTypeFont:
    """
    Get Bebas Neue font in a cross-platform way
    
    Args:
        size: Font size
        
    Returns:
        ImageFont object
    """
    font_paths = []
    
    if sys.platform == 'win32':
        # Windows - check common font locations
        font_paths = [
            "C:\\Windows\\Fonts\\BebasNeue-Regular.ttf",
            "C:\\Windows\\Fonts\\bebas-neue-bold.ttf",
            "C:\\Windows\\Fonts\\BebasNeue.ttf",
            "C:\\Windows\\Fonts\\BEBAS.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",  # Fallback to Arial Bold
        ]
    else:
        # Linux/Unix
        font_paths = [
            "/usr/share/fonts/truetype/bebas-neue/BebasNeue-Regular.ttf",  # Docker installed
            "/usr/share/fonts/truetype/bebas-neue/BebasNeue.ttf",
            "/usr/share/fonts/BebasNeue-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Fallback
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Fallback
        ]
    
    for path in font_paths:
        try:
            # Use BOLD style weight for Bebas Neue
            font = ImageFont.truetype(path, size)
            logger.info(f"✓ Loaded font: {path}")
            return font
        except Exception:
            continue
    
    # Ultimate fallback to default font
    logger.warning(f"Bebas Neue font not found, using default font")
    return ImageFont.load_default()


def _download_image(url: str) -> Optional[str]:
    """
    Download image from URL to temporary file
    
    Args:
        url: Image URL
        
    Returns:
        Path to temporary file, or None on failure
    """
    try:
        logger.info(f"📥 Downloading image: {url[:80]}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Create temporary file
        suffix = Path(url.split('?')[0]).suffix or '.jpg'
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_file.write(response.content)
        temp_file.close()
        
        logger.info(f"✓ Image downloaded: {temp_file.name}")
        return temp_file.name
    except Exception as e:
        logger.error(f"❌ Failed to download image: {e}")
        return None


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.Draw) -> list:
    """
    Wrap text to fit within max_width
    
    Args:
        text: Text to wrap
        font: Font to use
        max_width: Maximum width in pixels
        draw: ImageDraw object for text measurement
        
    Returns:
        List of text lines
    """
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        width = bbox[2] - bbox[0]
        
        if width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                # Single word is too long, add it anyway
                lines.append(word)
    
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines


def process_image_for_instagram(
    image_url: str,
    title: str,
    output_path: Optional[str] = None
) -> Optional[str]:
    """
    Process image for Instagram: resize to 4:5 (1080x1350) and add title overlay
    
    Args:
        image_url: URL of the source image
        title: Title text to overlay on image
        output_path: Optional output path (generates temp file if not provided)
        
    Returns:
        Path to processed image file, or None on failure
    """
    temp_input = None
    
    try:
        # Download image if URL
        if image_url.startswith(('http://', 'https://')):
            temp_input = _download_image(image_url)
            if not temp_input:
                return None
            image_path = temp_input
        else:
            image_path = image_url
            
        if not os.path.exists(image_path):
            logger.error(f"Image file not found: {image_path}")
            return None
        
        logger.info("🎨 Processing image for Instagram...")
        
        # Open image
        img = Image.open(image_path)
        
        # Convert to RGB if necessary (handle RGBA, P mode, etc.)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        # Target size: 1080x1350 (4:5 ratio)
        target_width = 1080
        target_height = 1350
        target_ratio = target_width / target_height  # 0.8
        
        # Calculate current ratio
        current_ratio = img.width / img.height
        
        # Crop to 4:5 ratio first, then resize
        if current_ratio > target_ratio:
            # Image is too wide - crop width
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        elif current_ratio < target_ratio:
            # Image is too tall - crop height
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))
        
        # Resize to final dimensions
        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
        logger.info(f"✓ Image resized to {target_width}x{target_height}")
        
        # Add semi-transparent overlay at bottom for text readability
        overlay = Image.new('RGBA', (target_width, target_height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        
        # Draw gradient-like overlay at bottom (darker at bottom)
        overlay_height = 500  # Height of text area
        for y in range(overlay_height):
            alpha = int(180 * (y / overlay_height))  # Gradient from 0 to 180
            overlay_draw.rectangle(
                [(0, target_height - overlay_height + y), (target_width, target_height - overlay_height + y + 1)],
                fill=(0, 0, 0, alpha)
            )
        
        # Composite overlay onto image
        img = img.convert('RGBA')
        img = Image.alpha_composite(img, overlay)
        img = img.convert('RGB')
        
        # Draw title text
        draw = ImageDraw.Draw(img)
        
        # Get Bebas Neue font (size 50, bold effect via stroke)
        font_size = 50
        font = _get_bebas_font(font_size)
        
        # Wrap text to fit width (with padding)
        max_text_width = target_width - 100  # 50px padding on each side
        lines = _wrap_text(title, font, max_text_width, draw)
        
        # Calculate total text height
        line_spacing = 10
        total_text_height = 0
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            total_text_height += (bbox[3] - bbox[1]) + line_spacing
        
        # Position text at bottom with padding
        text_y = target_height - total_text_height - 80  # 80px from bottom
        
        # Draw each line
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            text_x = (target_width - text_width) // 2  # Center horizontally
            
            # Draw text with stroke for bold effect and better visibility
            stroke_width = 3
            
            # Draw stroke (outline)
            draw.text(
                (text_x, text_y),
                line,
                font=font,
                fill='white',
                stroke_width=stroke_width,
                stroke_fill='black'
            )
            
            text_y += text_height + line_spacing
        
        logger.info(f"✓ Title overlay added: '{title[:50]}...'")
        
        # Save processed image
        if not output_path:
            output_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            output_path = output_file.name
            output_file.close()
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        
        # Save with high quality
        img.save(output_path, 'JPEG', quality=95, optimize=True)
        logger.info(f"✅ Instagram image saved: {output_path}")
        
        return output_path
        
    except Exception as e:
        logger.error(f"❌ Failed to process image for Instagram: {e}", exc_info=True)
        return None
        
    finally:
        # Clean up temporary downloaded file
        if temp_input and os.path.exists(temp_input):
            try:
                os.unlink(temp_input)
            except Exception:
                pass


def cleanup_temp_image(image_path: str) -> bool:
    """
    Delete temporary image file
    
    Args:
        image_path: Path to image file
        
    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        if image_path and os.path.exists(image_path):
            os.unlink(image_path)
            logger.info(f"🧹 Cleaned up temporary image: {image_path}")
            return True
        return False
    except Exception as e:
        logger.warning(f"⚠️ Failed to cleanup temporary image {image_path}: {e}")
        return False
