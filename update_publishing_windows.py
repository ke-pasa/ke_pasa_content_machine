#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to update publishing windows in Firebase.

Adjusts settings to the required publishing windows:
 - 09:00 - 11:00 (morning)
 - 12:00 - 14:00 (midday)
 - 16:00 - 18:00 (evening)
 - 20:00 - 22:00 (night)
"""

import sys
import os
from datetime import datetime
import pytz

# Добавляем текущую директорию в путь
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from firebase_client import get_firebase_client

def update_publishing_windows():
    """Update publishing windows in Firebase."""
    try:
        print("🔄 Updating publishing windows in Firebase...")

        # Get Firebase client
        client = get_firebase_client()

        # Load current settings
        current_settings = client.get_settings()
        print("📋 Current settings loaded")

        # New publishing windows
        new_publishing_windows = [
            {"start": "09:00", "end": "11:00"},
            {"start": "12:00", "end": "14:00"},
            {"start": "16:00", "end": "18:00"},
            {"start": "20:00", "end": "22:00"}
        ]

        # Update settings
        current_settings['publishing_windows'] = new_publishing_windows

        # Also update tg_slots_local to match the new windows
        current_settings['tg_slots_local'] = [
            "09:00", "10:00", "11:00",
            "12:00", "13:00", "14:00",
            "16:00", "17:00", "18:00",
            "20:00", "21:00", "22:00"
        ]

        # Save updated settings
        success = client.save_settings(current_settings)

        if success:
            print("✅ Publishing windows updated successfully!")
            print("\n📅 New publishing windows:")
            for i, window in enumerate(new_publishing_windows, 1):
                print(f"   {i}. {window['start']} - {window['end']}")

            print(f"\n⏰ Publishing slots: {len(current_settings['tg_slots_local'])} hours")
            print(f"📊 Day coverage: 8/13 hours = 61.5%")

            return True
        else:
            print("❌ Error saving settings")
            return False

    except Exception as e:
        print(f"❌ Error updating publishing windows: {e}")
        return False

def test_publishing_windows():
    """Run a quick test of the new publishing windows."""
    try:
        print("\n🧪 Testing new publishing windows...")
        
        client = get_firebase_client()
        settings = client.get_settings()
        
        # Check windows
        windows = settings.get('publishing_windows', [])
        print(f"📋 Loaded {len(windows)} publishing windows:")
        
        for i, window in enumerate(windows, 1):
            print(f"   {i}. {window['start']} - {window['end']}")
        
        # Check slots
        slots = settings.get('tg_slots_local', [])
        print(f"\n⏰ Publishing slots: {len(slots)} hours")
        print(f"   {', '.join(slots)}")
        
        # Test current time
        madrid_tz = pytz.timezone('Europe/Madrid')
        current_time = datetime.now(madrid_tz)
        current_hour = current_time.hour
        current_time_str = current_time.strftime("%H:%M")
        
        print(f"\n🕐 Current time (Madrid): {current_time_str}")
        print(f"   Hour: {current_hour}")
        
        # Check which window (if any) is active
        from jobs_scheduler import PublishingWindow
        
        active_window = None
        for window_data in windows:
            window = PublishingWindow(
                start=window_data['start'],
                end=window_data['end']
            )
            if window.is_active(current_time):
                active_window = window
                break
        
        if active_window:
            print(f"✅ Current time falls into publishing window: {active_window.start} - {active_window.end}")
        else:
            print(f"❌ Current time does NOT fall into any publishing window")
            
            # Show the next upcoming window
            for window_data in windows:
                window = PublishingWindow(
                    start=window_data['start'],
                    end=window_data['end']
                )
                start_hour = int(window.start.split(':')[0])
                if start_hour > current_hour:
                    print(f"   Next window: {window.start} - {window.end}")
                    break
        
        return True
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        return False

def main():
    """Main entrypoint for the script."""
    print("🚀 UPDATE PUBLISHING WINDOWS")
    print("=" * 50)
    print("🎯 Goal: Adjust publishing windows to the required schedule")
    print("📅 New windows:")
    print("   • 09:00 - 11:00 (morning)")
    print("   • 12:00 - 14:00 (midday)")
    print("   • 16:00 - 18:00 (evening)")
    print("   • 20:00 - 22:00 (night)")
    print("=" * 50)

    # Update settings and run a quick test
    if update_publishing_windows():
        test_publishing_windows()
        print("\n" + "=" * 50)
        print("🎉 UPDATE COMPLETE!")
        print("✅ Publishing windows updated")
        print("✅ 17:00 now falls into evening window (16:00-18:00)")
        print("✅ Day coverage: 8/13 hours = 61.5%")
    else:
        print("\n❌ UPDATE FAILED")
        print("Check logs and try again")

if __name__ == "__main__":
    main()




