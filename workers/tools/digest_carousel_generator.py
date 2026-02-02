"""
Instagram Carousel Generator for Evening Digest
Creates 6-slide carousel: 1 title slide + 5 news slides
"""
import os
import sys
import logging
import requests
from typing import List, Dict, Optional
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

_logger = logging.getLogger('workers.tools.digest_carousel_generator')


def _get_font_path(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """
    Get font in a cross-platform way
    
    Args:
        font_name: Font name (e.g., 'arial', 'arialbd')
        size: Font size
        
    Returns:
        ImageFont object
    """
    font_paths = []
    
    if sys.platform == 'win32':
        # Windows
        font_paths = [
            f"C:\\Windows\\Fonts\\{font_name}.ttf",
            f"{font_name}.ttf"
        ]
    else:
        # Linux/Unix
        font_paths = [
            f"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # DejaVu (common on Linux)
            f"/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Liberation
            f"/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",  # MS fonts if installed
            f"/System/Library/Fonts/Helvetica.ttc",  # macOS
            f"{font_name}.ttf"  # Try relative
        ]
    
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except:
            continue
    
    # Fallback to default
    _logger.warning(f"Font '{font_name}' not found, using default")
    return ImageFont.load_default()


class DigestCarouselGenerator:
    """Generate Instagram carousel slides for evening digest"""
    
    def __init__(self, output_dir: str = "output/carousel"):
        """
        Initialize carousel generator
        
        Args:
            output_dir: Directory to save generated slides
        """
        self.output_dir = output_dir
        self.slide_size = (1080, 1080)  # Instagram square format
        
        # Create output directory if doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        _logger.info(f"DigestCarouselGenerator initialized, output: {output_dir}")
    
    def generate_carousel_slides(
        self, 
        title_image_path: str,
        news_items: List[Dict],
        digest_title: str = "Испания, вечерний дайджест"
    ) -> List[Dict[str, str]]:
        """
        Generate complete carousel: 1 title + 5 news slides
        
        Args:
            title_image_path: Path to Telegram-generated title image
            news_items: List of 5 news items with 'image_url', 'title_ru', and 'url'
            digest_title: Title text for first slide
            
        Returns:
            List of dicts with 'path' and 'caption' for each slide (6 slides total)
        """
        try:
            slides = []
            
            # Slide 1: Title slide with digest title
            _logger.info("Creating title slide...")
            title_slide = self._create_title_slide(title_image_path, digest_title)
            
            if title_slide:
                title_path = os.path.join(self.output_dir, "slide_01_title.jpg")
                title_slide.save(title_path, quality=95, optimize=True)
                slides.append({
                    'path': title_path,
                    'caption': digest_title
                })
                _logger.info(f"✓ Title slide created: {title_path}")
            else:
                _logger.error("Failed to create title slide")
                return []
            
            # Slides 2-6: News slides (5 news items)
            news_items = news_items[:5]  # Ensure max 5 items
            
            for idx, news in enumerate(news_items, start=2):
                _logger.info(f"Creating news slide {idx}/6...")
                
                news_slide = self._create_news_slide(
                    image_url=news.get('image_url'),
                    title=news.get('title_ru', ''),
                    slide_number=idx - 1  # 1-5 for news numbering
                )
                
                if news_slide:
                    slide_path = os.path.join(self.output_dir, f"slide_{idx:02d}.jpg")
                    news_slide.save(slide_path, quality=95, optimize=True)
                    
                    # Build caption: title + URL
                    title = news.get('title_ru', '')
                    url = news.get('url', '')
                    caption = f"{title}\n\n{url}" if url else title
                    
                    slides.append({
                        'path': slide_path,
                        'caption': caption
                    })
                    _logger.info(f"✓ News slide {idx-1} created: {title[:50]}...")
                else:
                    _logger.warning(f"Failed to create slide for news {idx-1}")
            
            _logger.info(f"✓ Carousel complete: {len(slides)} slides generated")
            return slides
            
        except Exception as e:
            _logger.error(f"Failed to generate carousel: {e}", exc_info=True)
            return []
    
    def _create_title_slide(self, image_path: str, title_text: str) -> Optional[Image.Image]:
        """
        Create title slide from existing Telegram image + title text
        
        Args:
            image_path: Path to Telegram-generated title image
            title_text: Title text to overlay (e.g., "Испания, вечерний дайджест")
            
        Returns:
            PIL Image object or None if failed
        """
        try:
            # Load existing title image
            if not os.path.exists(image_path):
                _logger.error(f"Title image not found: {image_path}")
                return None
            
            img = Image.open(image_path)
            
            # Resize to Instagram square format
            img = self._resize_to_square(img)
            
            # Add semi-transparent overlay for text readability
            overlay = Image.new('RGBA', self.slide_size, (0, 0, 0, 100))  # Dark overlay
            img = img.convert('RGBA')
            img = Image.alpha_composite(img, overlay)
            img = img.convert('RGB')
            
            # Draw title text at bottom
            draw = ImageDraw.Draw(img)
            
            # Load font using cross-platform helper
            font = _get_font_path("arial", 60)
            
            # Calculate text position (centered at bottom)
            bbox = draw.textbbox((0, 0), title_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            text_x = (self.slide_size[0] - text_width) // 2
            text_y = self.slide_size[1] - text_height - 80  # 80px padding from bottom
            
            # Draw text with outline for better visibility
            # Outline
            for offset_x in [-2, 0, 2]:
                for offset_y in [-2, 0, 2]:
                    if offset_x != 0 or offset_y != 0:
                        draw.text((text_x + offset_x, text_y + offset_y), 
                                title_text, fill='black', font=font)
            
            # Main text
            draw.text((text_x, text_y), title_text, fill='white', font=font)
            
            return img
            
        except Exception as e:
            _logger.error(f"Failed to create title slide: {e}", exc_info=True)
            return None
    
    def _create_news_slide(
        self, 
        image_url: str, 
        title: str, 
        slide_number: int
    ) -> Optional[Image.Image]:
        """
        Create news slide: background image + title overlay + number
        
        Args:
            image_url: URL to article image from database
            title: News title (title_ru)
            slide_number: Slide number (1-5)
            
        Returns:
            PIL Image object or None if failed
        """
        try:
            # Download image from URL
            _logger.info(f"Downloading image: {image_url}")
            response = requests.get(image_url, timeout=15)
            response.raise_for_status()
            
            img = Image.open(BytesIO(response.content))
            
            # Resize to square
            img = self._resize_to_square(img)
            
            # Add dark overlay for text readability
            overlay = Image.new('RGBA', self.slide_size, (0, 0, 0, 120))
            img = img.convert('RGBA')
            img = Image.alpha_composite(img, overlay)
            img = img.convert('RGB')
            
            # Draw text
            draw = ImageDraw.Draw(img)
            
            # Load font for number
            font_number = _get_font_path("arialbd", 90)
            
            # Draw slide number in top-left corner
            number_text = f"#{slide_number}"
            
            # Number outline
            for offset_x in [-3, 0, 3]:
                for offset_y in [-3, 0, 3]:
                    if offset_x != 0 or offset_y != 0:
                        draw.text((50 + offset_x, 50 + offset_y), 
                                number_text, fill='black', font=font_number)
            
            # Number main text
            draw.text((50, 50), number_text, fill='white', font=font_number)
            
            # Add title text at the bottom
            if title:
                try:
                    # Load font for title
                    font_title = _get_font_path("arialbd", 40)
                    
                    # Wrap title text to multiple lines
                    max_width = self.slide_size[0] - 100  # 50px margin on each side
                    wrapped_lines = []
                    words = title.split()
                    current_line = []
                    
                    for word in words:
                        test_line = ' '.join(current_line + [word])
                        bbox = draw.textbbox((0, 0), test_line, font=font_title)
                        if bbox[2] - bbox[0] <= max_width:
                            current_line.append(word)
                        else:
                            if current_line:
                                wrapped_lines.append(' '.join(current_line))
                                current_line = [word]
                            else:
                                wrapped_lines.append(word)
                    
                    if current_line:
                        wrapped_lines.append(' '.join(current_line))
                    
                    # Limit to 4 lines max
                    wrapped_lines = wrapped_lines[:4]
                    
                    # Calculate total height
                    line_height = 50
                    total_height = len(wrapped_lines) * line_height
                    start_y = self.slide_size[1] - total_height - 80  # 80px from bottom
                    
                    # Draw each line with outline
                    for i, line in enumerate(wrapped_lines):
                        y = start_y + (i * line_height)
                        
                        # Center the text
                        bbox = draw.textbbox((0, 0), line, font=font_title)
                        text_width = bbox[2] - bbox[0]
                        x = (self.slide_size[0] - text_width) // 2
                        
                        # Black outline for readability
                        for offset_x in [-2, 0, 2]:
                            for offset_y in [-2, 0, 2]:
                                if offset_x != 0 or offset_y != 0:
                                    draw.text((x + offset_x, y + offset_y), 
                                            line, fill='black', font=font_title)
                        
                        # White main text
                        draw.text((x, y), line, fill='white', font=font_title)
                        
                except Exception as title_e:
                    _logger.warning(f"Failed to add title text: {title_e}")
            
            return img
            
        except Exception as e:
            _logger.error(f"Failed to create news slide: {e}", exc_info=True)
            return None
    
    def _resize_to_square(self, img: Image.Image) -> Image.Image:
        """
        Resize image to square format (1080x1080) with center crop
        
        Args:
            img: Input image
            
        Returns:
            Resized square image
        """
        width, height = img.size
        
        # Already square
        if width == height:
            return img.resize(self.slide_size, Image.Resampling.LANCZOS)
        
        # Crop to square (center crop)
        if width > height:
            # Landscape -> crop sides
            left = (width - height) // 2
            img = img.crop((left, 0, left + height, height))
        else:
            # Portrait -> crop top/bottom
            top = (height - width) // 2
            img = img.crop((0, top, width, top + width))
        
        return img.resize(self.slide_size, Image.Resampling.LANCZOS)


__all__ = ['DigestCarouselGenerator']
