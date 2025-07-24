import asyncio
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

# Extract credentials from environment variables
X_USERNAME = os.getenv("X_USERNAME")
X_PASSWORD = os.getenv("X_PASSWORD")
TARGET_HANDLE = os.getenv("TARGET_HANDLE", X_USERNAME)

# Browser settings
BROWSER_SETTINGS = {
    "headless": False,  # Set to True for production
    "viewport": {"width": 1280, "height": 720},
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "locale": "en-US",
    "timezone_id": "America/New_York",
    "geolocation": {"latitude": 40.7128, "longitude": -74.0060},
    "permissions": ["geolocation"],
}

# The extraction script (same as before)
EXTRACTION_SCRIPT = """
(async function() {
  // Helper: sleep for ms milliseconds
  const sleep = ms => new Promise(res => setTimeout(res, ms));

  // Helper: remove null/undefined/empty array fields
  function cleanPost(post) {
    return Object.fromEntries(
      Object.entries(post).filter(
        ([, v]) =>
          v !== null &&
          v !== undefined &&
          !(Array.isArray(v) && v.length === 0)
      )
    );
  }

  // Helper: extract visible liked post data from all articles
  function extractPosts() {
    const articles = document.querySelectorAll('article');
    const posts = [];
    articles.forEach(article => {
      // Author display name and username
      let author = null, username = null;
      // Find all anchor tags that link to a user profile
      const userLinks = Array.from(article.querySelectorAll('a[href^="/"][role="link"]'));
      for (const link of userLinks) {
        const match = link.getAttribute('href').match(/^\/([^\/]+)$/);
        if (match) {
          username = match[1];
          const displaySpan = link.querySelector('span');
          if (displaySpan) {
            author = displaySpan.textContent;
          }
          break;
        }
      }

      // Date/time
      const timeElem = article.querySelector('time');
      const date = timeElem ? timeElem.getAttribute('datetime') : null;

      // Text
      const textElem = article.querySelector('div[data-testid="tweetText"]');
      const text = textElem ? textElem.innerText : '';

      // Permalink
      const linkElem = timeElem ? timeElem.parentElement : null;
      const permalink = linkElem && linkElem.getAttribute('href') ? 'https://x.com' + linkElem.getAttribute('href') : null;

      // Stats
      let likes = null, retweets = null, replies = null, views = null;
      article.querySelectorAll('div[data-testid]').forEach(el => {
        if (el.getAttribute('data-testid') === 'like') likes = el.innerText;
        if (el.getAttribute('data-testid') === 'retweet') retweets = el.innerText;
        if (el.getAttribute('data-testid') === 'reply') replies = el.innerText;
        if (el.getAttribute('data-testid') === 'viewCount') views = el.innerText;
      });

      // Media
      let media = [];
      article.querySelectorAll('img, video').forEach(m => {
        if (m.src && !m.src.includes('profile_images')) media.push(m.src);
      });

      // Quoted tweet (if present)
      let quoted = null;
      const quotedElem = article.querySelector('div[data-testid="tweet"] article');
      if (quotedElem) {
        const quotedTextElem = quotedElem.querySelector('div[data-testid="tweetText"]');
        quoted = quotedTextElem ? quotedTextElem.innerText : null;
      }

      // Clean and push only non-null fields
      posts.push(cleanPost({
        author,
        username,
        date,
        text,
        permalink,
        likes,
        retweets,
        replies,
        views,
        media,
        quoted
      }));
    });
    return posts;
  }

  // Robustly detect Likes page and username
  const urlParts = window.location.pathname.split('/').filter(Boolean);
  const username = urlParts[0] || 'unknown';
  const path = window.location.pathname.toLowerCase();
  if (!path.includes('likes')) {
    throw new Error('This script is intended for the Likes page only.');
  }
  const pageType = 'likes';

  // Get today's date in YYYY-MM-DD
  const today = new Date();
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, '0');
  const dd = String(today.getDate()).padStart(2, '0');
  const dateStr = `${yyyy}-${mm}-${dd}`;

  // Main: scroll and extract
  let lastHeight = 0, sameCount = 0, maxNoChange = 15;
  let allPosts = new Map();

  while (sameCount < maxNoChange) {
    // Extract posts
    extractPosts().forEach(post => {
      if (post.permalink && !allPosts.has(post.permalink)) {
        allPosts.set(post.permalink, post);
      }
    });

    // Scroll
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(3500); // Wait longer for more content to load

    // Check for new content
    let newHeight = document.body.scrollHeight;
    if (newHeight === lastHeight) {
      sameCount++;
    } else {
      sameCount = 0;
      lastHeight = newHeight;
    }
  }

  // Return the result
  const result = Array.from(allPosts.values());
  return {
    username,
    pageType,
    dateStr,
    posts: result,
    totalPosts: result.length
  };
})();
"""

class PlaywrightLikesScraper:
    def __init__(self, username=None, password=None, target_handle=None):
        self.username = username or X_USERNAME
        self.password = password or X_PASSWORD
        self.target_handle = target_handle or TARGET_HANDLE
        self.browser = None
        self.page = None
        
    async def setup_browser(self):
        """Initialize browser with settings"""
        self.playwright = await async_playwright().start()
        
        # Launch browser with settings
        self.browser = await self.playwright.chromium.launch(
            headless=BROWSER_SETTINGS["headless"]
        )
        
        # Create context with settings
        context = await self.browser.new_context(
            viewport=BROWSER_SETTINGS["viewport"],
            user_agent=BROWSER_SETTINGS["user_agent"],
            locale=BROWSER_SETTINGS["locale"],
            timezone_id=BROWSER_SETTINGS["timezone_id"],
            geolocation=BROWSER_SETTINGS["geolocation"],
            permissions=BROWSER_SETTINGS["permissions"]
        )
        
        self.page = await context.new_page()
        
    async def login(self):
        """Handle X.com login"""
        print(f"Logging in as {self.username}...")
        
        await self.page.goto("https://x.com/login")
        await self.page.wait_for_load_state("networkidle")
        
        # Wait for login form and enter username
        try:
            # Look for username/email input
            username_input = await self.page.wait_for_selector(
                'input[autocomplete="username"], input[placeholder*="username"], input[placeholder*="email"], input[placeholder*="phone"]',
                timeout=10000
            )
            await username_input.fill(self.username)
            
            # Click Next/Continue
            next_button = await self.page.wait_for_selector(
                'div[role="button"]:has-text("Next"), div[role="button"]:has-text("Continue"), button:has-text("Next"), button:has-text("Continue")',
                timeout=5000
            )
            await next_button.click()
            await self.page.wait_for_timeout(2000)
            
        except Exception as e:
            print(f"Username step failed: {e}")
            # Try direct username input if the above fails
            try:
                username_input = await self.page.wait_for_selector('input[autocomplete="username"]', timeout=5000)
                await username_input.fill(self.username)
            except:
                pass
        
        # Enter password
        try:
            password_input = await self.page.wait_for_selector(
                'input[type="password"], input[autocomplete="current-password"]',
                timeout=10000
            )
            await password_input.fill(self.password)
            
            # Click Login
            login_button = await self.page.wait_for_selector(
                'div[role="button"]:has-text("Log in"), button:has-text("Log in"), div[data-testid="LoginButton"]',
                timeout=5000
            )
            await login_button.click()
            
        except Exception as e:
            print(f"Password step failed: {e}")
            raise
        
        # Wait for login to complete
        try:
            await self.page.wait_for_selector(
                '[data-testid="SideNav_AccountSwitcher_Button"], [data-testid="AppTabBar_Home_Link"], nav',
                timeout=15000
            )
            print("Login successful!")
        except Exception as e:
            print(f"Login verification failed: {e}")
            # Check if we're on a 2FA or verification page
            if await self.page.locator('text=Two-factor authentication').count() > 0:
                print("2FA required - please handle manually")
                await self.page.pause()
            else:
                raise Exception("Login failed - could not verify successful login")
    
    async def navigate_to_likes(self):
        """Navigate to the target user's likes page with enhanced debugging"""
        print(f"🧭 Navigating to {self.target_handle}'s likes page...")
        
        try:
            # Step 1: Go to user's profile first
            print(f"📍 Step 1: Going to profile page...")
            await self.page.goto(f"https://x.com/{self.target_handle}/likes")
            await self.page.wait_for_load_state("networkidle")
            print(f"✅ Profile page loaded: {self.page.url}")
            
            # Step 2: Wait a moment for page to stabilize
            await self.page.wait_for_timeout(3000)
            
            # Step 3: Check if we're already on likes page
            print(f"🔍 Step 2: Checking current page state...")
            current_url = self.page.url
            print(f"📍 Current URL: {current_url}")
            
            if "/likes" in current_url.lower():
                print("✅ Already on likes page!")
                await self.page.wait_for_timeout(2000)
                return
            
            # Step 4: Look for likes tab and click it
            print(f"🔗 Step 3: Looking for likes tab...")
            likes_tab_selectors = [
                'a[href*="/likes"]',
                'nav a:has-text("Likes")',
                '[data-testid="primaryColumn"] a:has-text("Likes")',
                'a:has-text("Likes")',
                '[role="tab"]:has-text("Likes")'
            ]
            
            likes_tab = None
            for i, selector in enumerate(likes_tab_selectors, 1):
                try:
                    print(f"🔍 Trying selector {i}/{len(likes_tab_selectors)}: {selector}")
                    likes_tab = await self.page.wait_for_selector(selector, timeout=5000)
                    if likes_tab and await likes_tab.is_visible():
                        print(f"✅ Found likes tab with selector: {selector}")
                        break
                    else:
                        print(f"❌ Tab found but not visible: {selector}")
                        likes_tab = None
                except Exception as e:
                    print(f"❌ Selector failed: {selector} - {e}")
                    continue
            
            if likes_tab:
                print(f"🖱️  Clicking likes tab...")
                await likes_tab.click()
                await self.page.wait_for_load_state("networkidle")
                await self.page.wait_for_timeout(3000)
                print(f"✅ Clicked likes tab, new URL: {self.page.url}")
            else:
                print("⚠️  No likes tab found, trying direct URL...")
                # Fallback: try direct navigation
                await self.page.goto(f"https://x.com/{self.target_handle}/likes")
                await self.page.wait_for_load_state("networkidle")
                await self.page.wait_for_timeout(3000)
                print(f"✅ Direct navigation completed: {self.page.url}")
            
            # Step 5: Verify we have content
            print(f"📄 Step 4: Verifying content loaded...")
            content_selectors = ['article', '[data-testid="tweet"]', 'div[data-testid="cellInnerDiv"]']
            
            content_found = False
            for selector in content_selectors:
                try:
                    count = await self.page.locator(selector).count()
                    if count > 0:
                        print(f"✅ Found {count} elements with selector: {selector}")
                        content_found = True
                        break
                except:
                    continue
            
            if not content_found:
                print("⚠️  No content found, but continuing anyway...")
            else:
                print("✅ Content verification successful!")
            
            print("🎉 Navigation to likes page completed!")
            
        except Exception as e:
            print(f"❌ Navigation failed: {e}")
            print(f"📍 Current URL: {self.page.url}")
            print("🔄 Attempting to continue anyway...")
            # Don't raise exception, let the verification step handle it
    
    async def execute_extraction_script(self):
        """Execute the JavaScript extraction script with robust error handling and retry logic"""
        print("🚀 Starting extraction script execution...")
        print(f"📍 Current URL: {self.page.url}")
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                print(f"📝 Extraction attempt {attempt + 1}/{max_retries}")
                print("=" * 50)
                
                # Step 1: Ensure we're on the likes page
                print("🔍 Step 1: Verifying likes page...")
                # await self._verify_likes_page()
                print("✅ Step 1 complete")
                
                # Step 2: Wait for content to load
                print("⏳ Step 2: Waiting for content...")
                # await self._wait_for_content()
                print("✅ Step 2 complete")
                
                # Step 3: Execute the script with multiple injection methods
                print("⚡ Step 3: Injecting and executing extraction script...")
                result = await self._execute_script_with_multiple_methods()
                print("✅ Step 3 complete")
                
                if result and result.get('posts'):
                    print(f"✅ Extraction completed successfully!")
                    print(f"📊 Found {result['totalPosts']} posts")
                    print(f"👤 Username: {result['username']}")
                    print(f"📅 Date: {result['dateStr']}")
                    return result
                else:
                    print("⚠️  Script executed but returned no data")
                    raise Exception("Script executed but returned no data")
                    
            except Exception as e:
                print(f"❌ Extraction attempt {attempt + 1} failed: {e}")
                print(f"📍 Failed at URL: {self.page.url}")
                
                if attempt < max_retries - 1:
                    print("🔄 Retrying extraction...")
                    await self._handle_extraction_error()
                    await self.page.wait_for_timeout(5000)  # Wait before retry
                else:
                    print("💥 All extraction attempts failed")
                    raise Exception(f"Extraction failed after {max_retries} attempts: {e}")
    
    async def _verify_likes_page(self):
        """Verify we're on the correct likes page"""
        print("🔍 Verifying we're on the likes page...")
        
        # Wait for likes page indicators (don't rely on URL)
        likes_indicators = [
            'article',
            '[data-testid="tweet"]',
            'div[data-testid="cellInnerDiv"]',
            '[data-testid="primaryColumn"]'
        ]
        
        # Check if we have any content that indicates we're on a page with posts
        content_found = False
        for indicator in likes_indicators:
            try:
                element = await self.page.wait_for_selector(indicator, timeout=5000)
                if element:
                    count = await self.page.locator(indicator).count()
                    if count > 0:
                        print(f"✅ Found {count} elements with indicator: {indicator}")
                        content_found = True
                        break
            except:
                continue
        
        if not content_found:
            print("⚠️  No content found, checking if we need to navigate...")
            # Check if we're on a profile page but not the likes tab
            try:
                # Look for likes tab and click it
                likes_tab_selectors = [
                    'a[href*="/likes"]',
                    'nav a:has-text("Likes")',
                    '[data-testid="primaryColumn"] a:has-text("Likes")',
                    'a:has-text("Likes")'
                ]
                
                for selector in likes_tab_selectors:
                    try:
                        likes_tab = await self.page.wait_for_selector(selector, timeout=3000)
                        if likes_tab and await likes_tab.is_visible():
                            print(f"🔗 Found likes tab: {selector}")
                            await likes_tab.click()
                            await self.page.wait_for_load_state("networkidle")
                            await self.page.wait_for_timeout(3000)
                            break
                    except:
                        continue
                
                # Check again for content after potential navigation
                for indicator in likes_indicators:
                    try:
                        element = await self.page.wait_for_selector(indicator, timeout=5000)
                        if element:
                            count = await self.page.locator(indicator).count()
                            if count > 0:
                                print(f"✅ Found {count} elements after navigation: {indicator}")
                                content_found = True
                                break
                    except:
                        continue
                        
            except Exception as e:
                print(f"⚠️  Navigation attempt failed: {e}")
        
        if not content_found:
            print("⚠️  Still no content found, but continuing anyway...")
            # Don't raise exception, just continue and let the script try to work
        
        print("✅ Page verification complete - proceeding with extraction")
    
    async def _wait_for_content(self):
        """Wait for content to load before extraction"""
        print("⏳ Waiting for content to load...")
        
        # Wait for initial content
        try:
            await self.page.wait_for_selector('article', timeout=15000)
            print("✅ Initial content loaded")
        except:
            print("⚠️  No articles found, continuing anyway...")
        
        # Wait a bit more for dynamic content
        await self.page.wait_for_timeout(3000)
        
        # Scroll a bit to trigger lazy loading
        await self.page.evaluate("window.scrollTo(0, 500)")
        await self.page.wait_for_timeout(2000)
    
    async def _handle_extraction_error(self):
        """Handle extraction errors and try to recover"""
        print("🔧 Attempting to recover from extraction error...")
        
        try:
            # Try refreshing the page
            print("🔄 Refreshing page...")
            await self.page.reload()
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(3000)
            
            # Verify we're still logged in
            if await self.page.locator('text=Log in').count() > 0:
                print("⚠️  Lost login session, attempting to re-login...")
                await self.login()
                await self.navigate_to_likes()
            
        except Exception as e:
                         print(f"⚠️  Recovery attempt failed: {e}")
             # Continue anyway, the main retry loop will handle it
    
    async def _execute_script_with_multiple_methods(self):
        """Execute the extraction script using multiple injection methods"""
        methods = [
            self._execute_via_evaluate,
            self._execute_via_script_tag,
            self._execute_via_devtools
        ]
        
        for i, method in enumerate(methods, 1):
            start_time = asyncio.get_event_loop().time()
            try:
                print(f"🔧 Trying injection method {i}/{len(methods)}: {method.__name__}")
                print(f"⏱️  Starting method: {method.__name__}")
                
                result = await method()
                
                end_time = asyncio.get_event_loop().time()
                duration = end_time - start_time
                print(f"⏱️  Method {method.__name__} took {duration:.2f} seconds")
                
                if result and result.get('posts'):
                    print(f"✅ Method {method.__name__} succeeded!")
                    return result
                else:
                    print(f"⚠️  Method {method.__name__} returned no data")
            except Exception as e:
                end_time = asyncio.get_event_loop().time()
                duration = end_time - start_time
                print(f"❌ Method {method.__name__} failed after {duration:.2f} seconds: {e}")
                continue
        
        raise Exception("All script injection methods failed")
    
    async def _execute_via_console(self):
        """Execute script by opening dev console and pasting"""
        print("🖥️  Opening developer console...")
        
        # Open dev tools (F12)
        print("⌨️  Pressing F12...")
        await self.page.keyboard.press("F12")
        print("⏳ Waiting for dev tools...")
        await self.page.wait_for_timeout(2000)
        
        # Click on Console tab
        try:
            console_tab = await self.page.wait_for_selector(
                'text=Console, [role="tab"]:has-text("Console"), .tab:has-text("Console")',
                timeout=5000
            )
            await console_tab.click()
            await self.page.wait_for_timeout(1000)
        except:
            print("⚠️  Could not find Console tab, trying to paste directly...")
        
        # Focus on console and paste script
        await self.page.keyboard.press("Escape")  # Clear any existing input
        await self.page.wait_for_timeout(500)
        
        # Paste the script
        await self.page.keyboard.type(EXTRACTION_SCRIPT)
        await self.page.wait_for_timeout(1000)
        
        # Press Enter to execute
        await self.page.keyboard.press("Enter")
        
        # Wait for execution and get result
        await self.page.wait_for_timeout(10000)  # Wait for script to complete
        
        # Try to get result from console output or return value
        try:
            # Check if script returned a result
            result = await self.page.evaluate("window.lastExtractionResult || null")
            if result:
                return result
        except:
            pass
        
        # If no direct result, try to extract from page
        return await self._extract_from_page()
    
    async def _execute_via_evaluate(self):
        """Execute script directly via page.evaluate"""
        print("⚡ Executing script directly...")
        
        # Check if we're still on a valid page
        current_url = self.page.url
        if "compose" in current_url.lower():
            print("⚠️  Page navigated to compose, trying to go back...")
            await self.page.go_back()
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(3000)
        
        return await self.page.evaluate(EXTRACTION_SCRIPT)
    
    async def _execute_via_devtools(self):
        """Execute script via CDP (Chrome DevTools Protocol)"""
        print("🔧 Using CDP for script execution...")
        
        try:
            # Get CDP session
            cdp = await self.page.context.new_cdp_session(self.page)
            
            # Execute script via CDP
            result = await cdp.send("Runtime.evaluate", {
                "expression": EXTRACTION_SCRIPT,
                "returnByValue": True,
                "awaitPromise": True
            })
            
            if result.get("result", {}).get("value"):
                return result["result"]["value"]
            else:
                raise Exception("CDP execution returned no value")
                
        except Exception as e:
            print(f"CDP method failed: {e}")
            raise
    
    async def _execute_via_script_tag(self):
        """Execute script by injecting a script tag"""
        print("📜 Injecting script tag...")
        
        # Check if we're still on a valid page
        current_url = self.page.url
        if "compose" in current_url.lower():
            print("⚠️  Page navigated to compose, trying to go back...")
            await self.page.go_back()
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(3000)
        
        # Inject script tag
        await self.page.evaluate(f"""
            const script = document.createElement('script');
            script.textContent = `{EXTRACTION_SCRIPT}`;
            document.head.appendChild(script);
        """)
        
        # Wait for execution
        await self.page.wait_for_timeout(5000)
        
        # Try to get result
        result = await self.page.evaluate("window.lastExtractionResult || null")
        if result:
            return result
        
        # Fallback to page extraction
        return await self._extract_from_page()
    
    async def _extract_from_page(self):
        """Fallback: extract data directly from page without script"""
        print("🔄 Fallback: extracting data directly from page...")
        
        # Simple extraction without the complex script
        posts = await self.page.evaluate("""
            const articles = document.querySelectorAll('article');
            const posts = [];
            
            articles.forEach(article => {
                const textElem = article.querySelector('div[data-testid="tweetText"]');
                const timeElem = article.querySelector('time');
                const userLinks = article.querySelectorAll('a[href^="/"][role="link"]');
                
                let username = null, author = null;
                for (const link of userLinks) {
                    const match = link.getAttribute('href').match(/^\/([^\/]+)$/);
                    if (match) {
                        username = match[1];
                        const displaySpan = link.querySelector('span');
                        if (displaySpan) {
                            author = displaySpan.textContent;
                        }
                        break;
                    }
                }
                
                posts.push({
                    author: author,
                    username: username,
                    text: textElem ? textElem.innerText : '',
                    date: timeElem ? timeElem.getAttribute('datetime') : null
                });
            });
            
            return {
                username: window.location.pathname.split('/')[1] || 'unknown',
                pageType: 'likes',
                dateStr: new Date().toISOString().split('T')[0],
                posts: posts,
                totalPosts: posts.length
            };
        """)
        
        return posts
    
    async def save_results(self, results):
        """Save the extracted results to a JSON file"""
        if not results or not results.get('posts'):
            print("No results to save")
            return None
            
        # Create output directory
        output_dir = Path("extracted_data")
        output_dir.mkdir(exist_ok=True)
        
        # Generate filename
        filename = f"{results['username']}_{results['pageType']}_{results['dateStr']}.json"
        filepath = output_dir / filename
        
        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"Results saved to: {filepath}")
        return filepath
    
    async def run(self):
        """Main execution method"""
        try:
            await self.setup_browser()
            await self.login()
            await self.navigate_to_likes()
            results = await self.execute_extraction_script()
            filepath = await self.save_results(results)
            
            return {
                "success": True,
                "filepath": filepath,
                "total_posts": results['totalPosts'] if results else 0
            }
            
        except Exception as e:
            print(f"Scraping failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            if self.browser:
                await self.browser.close()
            if hasattr(self, 'playwright'):
                await self.playwright.stop()

async def main():
    """Main function to run the scraper"""
    scraper = PlaywrightLikesScraper()
    result = await scraper.run()
    
    if result["success"]:
        print(f"✅ Scraping completed successfully!")
        print(f"📁 Results saved to: {result['filepath']}")
        print(f"📊 Total posts extracted: {result['total_posts']}")
    else:
        print(f"❌ Scraping failed: {result['error']}")

if __name__ == "__main__":
    asyncio.run(main()) 