#!/usr/bin/env python3
"""
Test script to check available fonts in the container
"""

import os
import logging
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_fonts():
    """Test which fonts are available"""
    
    print("=== Font Availability Test ===")
    
    # List of fonts to try
    font_paths = [
        # Windows fonts
        "arial.ttf",
        "Arial.ttf", 
        "C:/Windows/Fonts/arial.ttf",
        # Linux DejaVu fonts (installed in Docker)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        # Ubuntu/Liberation fonts 
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        # Generic Linux fonts
        "/usr/share/fonts/TTF/arial.ttf",
        "/System/Library/Fonts/Arial.ttf",  # macOS
    ]
    
    available_fonts = []
    
    for font_path in font_paths:
        try:
            font = ImageFont.truetype(font_path, 26)
            print(f"✅ Found: {font_path}")
            available_fonts.append(font_path)
        except (OSError, IOError) as e:
            print(f"❌ Not found: {font_path}")
    
    # Test default font
    try:
        default_font = ImageFont.load_default()
        print(f"✅ Default font available")
        available_fonts.append("default")
    except Exception as e:
        print(f"❌ Default font failed: {e}")
    
    print(f"\n=== Summary ===")
    print(f"Available fonts: {len(available_fonts)}")
    for font in available_fonts:
        print(f"  - {font}")
    
    # Test creating text with available font
    if available_fonts:
        print(f"\n=== Text Rendering Test ===")
        try:
            # Use first available font
            if available_fonts[0] == "default":
                font = ImageFont.load_default()
            else:
                font = ImageFont.truetype(available_fonts[0], 26)
            
            # Create test image
            img = Image.new('RGBA', (300, 100), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            test_text = "Тест шрифта / Font test"
            draw.text((10, 10), test_text, font=font, fill=(255, 255, 255, 255))
            
            # Save test image
            output_path = "/tmp/font_test.png"
            img.save(output_path)
            print(f"✅ Text rendering successful, saved to {output_path}")
            
        except Exception as e:
            print(f"❌ Text rendering failed: {e}")

if __name__ == "__main__":
    test_fonts()