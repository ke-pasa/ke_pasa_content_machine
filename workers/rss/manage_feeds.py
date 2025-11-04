"""
RSS Feed Management Utility

Utility for manual RSS feed management:
- View statistics (working, not working, outdated)
- Restore feeds from problem lists back to feeds.txt
- Manual validation of specific feeds
- Merge problem lists
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Colors for Windows console
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'

def read_feeds(filepath):
    """Read feeds from file, excluding comments and empty lines"""
    if not os.path.exists(filepath):
        return []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

def write_feeds(filepath, feeds, header=None):
    """Write feeds to file with header"""
    with open(filepath, 'w', encoding='utf-8') as f:
        if header:
            f.write(f"# {header}\n")
        else:
            f.write("# RSS feeds\n")
        f.write(f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Total: {len(feeds)}\n")
        f.write("#\n\n")
        for feed in sorted(feeds):
            f.write(feed + '\n')

def show_statistics():
    """Show statistics for all feed files"""
    print(f"\n{Colors.BOLD}📊 RSS Feeds Statistics{Colors.END}")
    print("=" * 60)
    
    # Main feeds
    main_feeds = read_feeds('workers/rss/feeds.txt')
    print(f"{Colors.GREEN}✅ Working feeds:{Colors.END} {len(main_feeds)}")
    
    # Not working
    not_working = read_feeds('feeds_not_working.txt')
    print(f"{Colors.RED}❌ Not working feeds:{Colors.END} {len(not_working)}")
    
    # Outdated
    outdated = read_feeds('feeds_outdated.txt')
    print(f"{Colors.YELLOW}📅 Outdated feeds:{Colors.END} {len(outdated)}")
    
    print("=" * 60)
    print(f"{Colors.BOLD}Total feeds tracked:{Colors.END} {len(main_feeds) + len(not_working) + len(outdated)}")

def list_feeds(filepath, title):
    """List all feeds from file"""
    feeds = read_feeds(filepath)
    
    print(f"\n{Colors.BOLD}{title}{Colors.END}")
    print("=" * 60)
    
    if not feeds:
        print(f"{Colors.YELLOW}No feeds found{Colors.END}")
        return
    
    for i, feed in enumerate(feeds, 1):
        print(f"{i:3d}. {feed}")
    
    print("=" * 60)
    print(f"Total: {len(feeds)}")

def restore_feed():
    """Restore feed from problem list back to main list"""
    print(f"\n{Colors.BOLD}🔄 Restore Feed{Colors.END}")
    print("=" * 60)
    
    # Show problem feeds
    not_working = read_feeds('feeds_not_working.txt')
    outdated = read_feeds('feeds_outdated.txt')
    
    all_problematic = list(set(not_working + outdated))
    
    if not all_problematic:
        print(f"{Colors.YELLOW}No problematic feeds to restore{Colors.END}")
        return
    
    print("\nProblematic feeds:")
    for i, feed in enumerate(all_problematic, 1):
        status = []
        if feed in not_working:
            status.append(f"{Colors.RED}NOT WORKING{Colors.END}")
        if feed in outdated:
            status.append(f"{Colors.YELLOW}OUTDATED{Colors.END}")
        print(f"{i:3d}. {feed} ({', '.join(status)})")
    
    # Get user input
    try:
        choice = input(f"\nEnter feed number to restore (1-{len(all_problematic)}) or 'q' to quit: ").strip()
        
        if choice.lower() == 'q':
            return
        
        index = int(choice) - 1
        if 0 <= index < len(all_problematic):
            feed_to_restore = all_problematic[index]
            
            # Read current main feeds
            main_feeds = read_feeds('workers/rss/feeds.txt')
            
            if feed_to_restore in main_feeds:
                print(f"{Colors.YELLOW}Feed already in main list{Colors.END}")
                return
            
            # Add to main list
            main_feeds.append(feed_to_restore)
            write_feeds('workers/rss/feeds.txt', main_feeds, "RSS feeds - Automatically cleaned")
            
            # Remove from problem lists
            if feed_to_restore in not_working:
                not_working.remove(feed_to_restore)
                write_feeds('feeds_not_working.txt', not_working, "Problematic RSS feeds")
            
            if feed_to_restore in outdated:
                outdated.remove(feed_to_restore)
                write_feeds('feeds_outdated.txt', outdated, "Problematic RSS feeds")
            
            print(f"{Colors.GREEN}✅ Feed restored successfully{Colors.END}")
            print(f"Feed: {feed_to_restore}")
        else:
            print(f"{Colors.RED}Invalid choice{Colors.END}")
    except ValueError:
        print(f"{Colors.RED}Invalid input{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.END}")

def add_feed():
    """Add new feed to main list"""
    print(f"\n{Colors.BOLD}➕ Add New Feed{Colors.END}")
    print("=" * 60)
    
    feed_url = input("Enter RSS feed URL: ").strip()
    
    if not feed_url:
        print(f"{Colors.RED}URL cannot be empty{Colors.END}")
        return
    
    if not feed_url.startswith('http'):
        print(f"{Colors.RED}URL must start with http:// or https://{Colors.END}")
        return
    
    # Read current feeds
    main_feeds = read_feeds('workers/rss/feeds.txt')
    
    if feed_url in main_feeds:
        print(f"{Colors.YELLOW}Feed already exists in main list{Colors.END}")
        return
    
    # Add feed
    main_feeds.append(feed_url)
    write_feeds('workers/rss/feeds.txt', main_feeds, "RSS feeds - Automatically cleaned")
    
    print(f"{Colors.GREEN}✅ Feed added successfully{Colors.END}")
    print(f"Feed: {feed_url}")

def remove_feed():
    """Remove feed from main list"""
    print(f"\n{Colors.BOLD}🗑️  Remove Feed{Colors.END}")
    print("=" * 60)
    
    main_feeds = read_feeds('workers/rss/feeds.txt')
    
    if not main_feeds:
        print(f"{Colors.YELLOW}No feeds to remove{Colors.END}")
        return
    
    # Show feeds
    for i, feed in enumerate(main_feeds, 1):
        print(f"{i:3d}. {feed}")
    
    # Get user input
    try:
        choice = input(f"\nEnter feed number to remove (1-{len(main_feeds)}) or 'q' to quit: ").strip()
        
        if choice.lower() == 'q':
            return
        
        index = int(choice) - 1
        if 0 <= index < len(main_feeds):
            feed_to_remove = main_feeds[index]
            main_feeds.pop(index)
            
            write_feeds('workers/rss/feeds.txt', main_feeds, "RSS feeds - Automatically cleaned")
            
            print(f"{Colors.GREEN}✅ Feed removed successfully{Colors.END}")
            print(f"Feed: {feed_to_remove}")
        else:
            print(f"{Colors.RED}Invalid choice{Colors.END}")
    except ValueError:
        print(f"{Colors.RED}Invalid input{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.END}")

def main():
    """Main menu"""
    while True:
        print(f"\n{Colors.BOLD}🔧 RSS Feed Management Utility{Colors.END}")
        print("=" * 60)
        print("1. Show statistics")
        print("2. List working feeds")
        print("3. List not working feeds")
        print("4. List outdated feeds")
        print("5. Restore feed from problem list")
        print("6. Add new feed")
        print("7. Remove feed")
        print("0. Exit")
        print("=" * 60)
        
        choice = input("\nSelect option: ").strip()
        
        if choice == '0':
            print(f"{Colors.GREEN}Goodbye!{Colors.END}")
            break
        elif choice == '1':
            show_statistics()
        elif choice == '2':
            list_feeds('workers/rss/feeds.txt', '✅ Working Feeds')
        elif choice == '3':
            list_feeds('feeds_not_working.txt', '❌ Not Working Feeds')
        elif choice == '4':
            list_feeds('feeds_outdated.txt', '📅 Outdated Feeds')
        elif choice == '5':
            restore_feed()
        elif choice == '6':
            add_feed()
        elif choice == '7':
            remove_feed()
        else:
            print(f"{Colors.RED}Invalid option{Colors.END}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.END}")
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.END}")
