#!/usr/bin/env python3
"""
Example script demonstrating the Playwright-based X.com likes scraper.
This avoids browser-use quota consumption by using Playwright directly.
"""

import asyncio
import sys
import os

# Add the parent directory to the path so we can import our scraper
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from e2b_sandbox.browser_scrapers.playwright_likes_scraper import PlaywrightLikesScraper

async def example_usage():
    """Example of how to use the PlaywrightLikesScraper"""
    
    # Method 1: Use environment variables (recommended)
    print("=== Method 1: Using environment variables ===")
    scraper1 = PlaywrightLikesScraper()
    result1 = await scraper1.run()
    
    if result1["success"]:
        print(f"✅ Success! Found {result1['total_posts']} posts")
        print(f"📁 Saved to: {result1['filepath']}")
    else:
        print(f"❌ Failed: {result1['error']}")
    
    # Method 2: Pass credentials directly
    print("\n=== Method 2: Passing credentials directly ===")
    # Uncomment and modify these lines to use direct credentials
    # scraper2 = PlaywrightLikesScraper(
    #     username="your_username",
    #     password="your_password", 
    #     target_handle="target_user"
    # )
    # result2 = await scraper2.run()
    
    # Method 3: Scrape different user's likes
    print("\n=== Method 3: Scraping different user's likes ===")
    # Uncomment to scrape a different user's likes
    # scraper3 = PlaywrightLikesScraper(target_handle="elonmusk")
    # result3 = await scraper3.run()

if __name__ == "__main__":
    print("🚀 Starting Playwright X.com Likes Scraper Example")
    print("Make sure you have set X_USERNAME and X_PASSWORD in your .env file")
    print("=" * 60)
    
    asyncio.run(example_usage()) 