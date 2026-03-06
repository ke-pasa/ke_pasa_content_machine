#!/usr/bin/env python3
"""
Check if required fonts are installed
Useful for CI/CD and troubleshooting
"""
import sys
import os
from pathlib import Path

def check_fonts():
    """Check if Bebas Neue and fallback fonts are available"""
    
    print("=" * 60)
    print("Font Installation Check")
    print("=" * 60)
    
    fonts_found = []
    fonts_missing = []
    
    # Windows paths
    windows_paths = [
        "C:\\Windows\\Fonts\\BebasNeue-Regular.ttf",
        "C:\\Windows\\Fonts\\BEBAS.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",  # Fallback
    ]
    
    # Linux paths
    linux_paths = [
        "/usr/share/fonts/truetype/bebas-neue/BebasNeue-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Fallback
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Fallback
    ]
    
    paths_to_check = windows_paths if sys.platform == 'win32' else linux_paths
    
    print(f"\nPlatform: {sys.platform}")
    print(f"Checking {len(paths_to_check)} font paths...\n")
    
    for font_path in paths_to_check:
        if os.path.exists(font_path):
            fonts_found.append(font_path)
            print(f"✅ FOUND: {font_path}")
        else:
            fonts_missing.append(font_path)
            print(f"❌ MISSING: {font_path}")
    
    print("\n" + "=" * 60)
    print(f"Summary: {len(fonts_found)} found, {len(fonts_missing)} missing")
    print("=" * 60)
    
    # Check if at least one font is available
    if fonts_found:
        print(f"\n✅ OK: At least one font is available")
        print(f"   Primary: {fonts_found[0]}")
        return True
    else:
        print("\n⚠️ WARNING: No fonts found!")
        print("\nInstallation instructions:")
        if sys.platform == 'win32':
            print("  Windows: Download from https://fonts.google.com/specimen/Bebas+Neue")
            print("           Right-click .ttf → Install for all users")
        else:
            print("  Linux/Docker: Font should be auto-installed in Dockerfile.base")
            print("                Run: docker-compose build")
        return False

def check_pil_fonts():
    """Check if PIL can load fonts"""
    try:
        from PIL import ImageFont
        print("\n" + "=" * 60)
        print("PIL Font Loading Test")
        print("=" * 60)
        
        # Try to load a font
        try:
            if sys.platform == 'win32':
                font = ImageFont.truetype("C:\\Windows\\Fonts\\arialbd.ttf", 50)
            else:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
            print("✅ PIL can load TrueType fonts")
            return True
        except Exception as e:
            print(f"⚠️ PIL font loading issue: {e}")
            # Try default font
            font = ImageFont.load_default()
            print("⚠️ Using default font (basic functionality only)")
            return False
            
    except ImportError:
        print("❌ PIL/Pillow not installed!")
        print("   Run: pip install Pillow")
        return False

if __name__ == "__main__":
    print("\n🔍 Checking font installation for Instagram image processing...\n")
    
    fonts_ok = check_fonts()
    pil_ok = check_pil_fonts()
    
    print("\n" + "=" * 60)
    if fonts_ok and pil_ok:
        print("✅ ALL CHECKS PASSED")
        print("=" * 60)
        sys.exit(0)
    else:
        print("⚠️ SOME CHECKS FAILED")
        print("=" * 60)
        print("\nImage processing will use fallback fonts.")
        print("For best results, install Bebas Neue font.")
        sys.exit(1)
