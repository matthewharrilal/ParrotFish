#!/usr/bin/env python3
"""
Test script for the Playwright-based X.com likes scraper.
This script tests the scraper without actually running it to verify setup.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the e2b_sandbox directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'e2b_sandbox'))

def test_imports():
    """Test that all required modules can be imported"""
    print("🔍 Testing imports...")
    
    try:
        from browser_scrapers.playwright_likes_scraper import PlaywrightLikesScraper
        print("✅ PlaywrightLikesScraper imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import PlaywrightLikesScraper: {e}")
        return False
    
    try:
        from browser_scrapers.playwright_likes_scraper_headless import HeadlessLikesScraper
        print("✅ HeadlessLikesScraper imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import HeadlessLikesScraper: {e}")
        return False
    
    return True

def test_environment():
    """Test that environment variables are set"""
    print("\n🔍 Testing environment variables...")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    username = os.getenv("X_USERNAME")
    password = os.getenv("X_PASSWORD")
    
    if username:
        print(f"✅ X_USERNAME is set: {username}")
    else:
        print("❌ X_USERNAME is not set")
        return False
    
    if password:
        print(f"✅ X_PASSWORD is set: {'*' * len(password)}")
    else:
        print("❌ X_PASSWORD is not set")
        return False
    
    return True

def test_playwright_installation():
    """Test that Playwright is properly installed"""
    print("\n🔍 Testing Playwright installation...")
    
    try:
        from playwright.async_api import async_playwright
        print("✅ Playwright async_api imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Playwright: {e}")
        print("💡 Try running: playwright install")
        return False
    
    return True

async def test_browser_launch():
    """Test that we can launch a browser"""
    print("\n🔍 Testing browser launch...")
    
    try:
        from playwright.async_api import async_playwright
        
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Test a simple page load
        await page.goto("https://example.com")
        title = await page.title()
        
        await browser.close()
        await playwright.stop()
        
        print(f"✅ Browser launched successfully, loaded: {title}")
        return True
        
    except Exception as e:
        print(f"❌ Browser launch failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 Testing Playwright X.com Likes Scraper Setup")
    print("=" * 50)
    
    # Test imports
    if not test_imports():
        print("\n❌ Import tests failed")
        return
    
    # Test environment
    if not test_environment():
        print("\n❌ Environment tests failed")
        print("💡 Make sure you have a .env file with X_USERNAME and X_PASSWORD")
        return
    
    # Test Playwright installation
    if not test_playwright_installation():
        print("\n❌ Playwright installation test failed")
        return
    
    # Test browser launch
    if asyncio.run(test_browser_launch()):
        print("\n✅ All tests passed! The scraper should work correctly.")
        print("\n📝 To run the scraper:")
        print("   python e2b_sandbox/browser_scrapers/playwright_likes_scraper.py")
        print("   python e2b_sandbox/browser_scrapers/playwright_likes_scraper_headless.py")
        print("   python examples/playwright_likes_example.py")
    else:
        print("\n❌ Browser launch test failed")

if __name__ == "__main__":
    main() 