#!/usr/bin/env python3
"""
RSS Worker dependencies check for GitHub Actions
"""

import sys
import subprocess
import importlib.util


def check_package(package_name, import_name=None):
    """Check package installation"""
    if import_name is None:
        import_name = package_name.replace('-', '_')
    
    try:
        spec = importlib.util.find_spec(import_name)
        if spec is not None:
            module = importlib.import_module(import_name)
            version = getattr(module, '__version__', 'unknown')
            print(f"✅ {package_name}: {version}")
            return True
        else:
            print(f"❌ {package_name}: not found")
            return False
    except ImportError as e:
        print(f"❌ {package_name}: import error - {e}")
        return False


def main():
    """Main check function"""
    print("🔍 Checking RSS Worker dependencies...")
    print("=" * 50)
    
    # List of packages to check
    packages = [
        ('feedparser', 'feedparser'),
        ('requests', 'requests'),
        ('beautifulsoup4', 'bs4'),
        ('readability-lxml', 'readability'),
        ('python-dateutil', 'dateutil'),
        ('python-slugify', 'slugify'),
        ('python-dotenv', 'dotenv'),
        ('lxml', 'lxml'),
        ('typing-extensions', 'typing_extensions'),
        ('certifi', 'certifi'),
        ('charset-normalizer', 'charset_normalizer'),
        ('urllib3', 'urllib3')
    ]
    
    success_count = 0
    total_count = len(packages)
    
    for package_name, import_name in packages:
        if check_package(package_name, import_name):
            success_count += 1
    
    print("=" * 50)
    print(f"📊 Result: {success_count}/{total_count} packages installed")
    
    if success_count == total_count:
        print("✅ All dependencies installed correctly!")
        return 0
    else:
        print("❌ Some dependencies are missing.")
        print("\nTo install run:")
        print("pip install -r workers/rss/requirements.txt")
        return 1


if __name__ == "__main__":
    sys.exit(main())