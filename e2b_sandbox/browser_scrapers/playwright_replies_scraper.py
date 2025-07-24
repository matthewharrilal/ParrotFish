import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from glob import glob

load_dotenv()

X_USERNAME = os.getenv("X_USERNAME")
X_PASSWORD = os.getenv("X_PASSWORD")
TARGET_HANDLE = os.getenv("TARGET_HANDLE", X_USERNAME)

BROWSER_SETTINGS = {
    "headless": False,
    "viewport": {"width": 1280, "height": 720},
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "locale": "en-US",
    "timezone_id": "America/New_York",
    "geolocation": {"latitude": 40.7128, "longitude": -74.0060},
    "permissions": ["geolocation"],
}

EXTRACTION_SCRIPT = """
(async function() {
  // Helper: sleep for ms milliseconds
  const sleep = ms => new Promise(res => setTimeout(res, ms));

  // Helper: click all 'Show more' buttons in visible articles
  async function expandAllShowMore() {
    let buttons = Array.from(document.querySelectorAll('article button')).filter(
      btn => /show more|show thread/i.test(btn.textContent)
    );
    for (const btn of buttons) {
      try { btn.click(); await sleep(200); } catch (e) {}
    }
  }

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

  // Helper: extract visible reply data from all articles
  async function extractPosts() {
    await expandAllShowMore();
    const articles = document.querySelectorAll('article');
    const posts = [];
    articles.forEach(article => {
      // Author display name and username
      let author = null, username = null;
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

      // Parent tweet (inReplyTo) if present in DOM (for replies)
      let inReplyTo = null;
      const path = window.location.pathname.toLowerCase();
      if (path.includes('replies')) {
        // Look for a parent tweet in a context block above the reply
        const contextElem = article.parentElement?.parentElement?.querySelector('div[aria-label*="Timeline: Conversation"] article');
        if (contextElem) {
          const parentTextElem = contextElem.querySelector('div[data-testid="tweetText"]');
          const parentText = parentTextElem ? parentTextElem.innerText : null;
          const parentTimeElem = contextElem.querySelector('time');
          const parentPermalink = parentTimeElem && parentTimeElem.parentElement.getAttribute('href')
            ? 'https://x.com' + parentTimeElem.parentElement.getAttribute('href')
            : null;
          if (parentText || parentPermalink) {
            inReplyTo = cleanPost({
              text: parentText,
              permalink: parentPermalink
            });
          }
        }
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
        quoted,
        inReplyTo
      }));
    });
    return posts;
  }

  // Robustly detect Replies page and username
  const urlParts = window.location.pathname.split('/').filter(Boolean);
  const username = urlParts[0] || 'unknown';
  const path = window.location.pathname.toLowerCase();
  if (!path.includes('replies')) {
    alert('This script is intended for the Replies page only.');
    return;
  }
  let pageType = 'replies';
  if (path.includes('with_replies')) pageType = 'with_replies';

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
    (await extractPosts()).forEach(post => {
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

  // Output as JSON
  const result = Array.from(allPosts.values());
  console.log("Extracted replies:", result);

  // Download as JSON file with dynamic name
  const filename = `${username}_${pageType}_${dateStr}.json`;
  const blob = new Blob([JSON.stringify(result, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);

  // Return the result for Playwright
  return {
    username,
    pageType,
    dateStr,
    posts: result,
    totalPosts: result.length
  };
})();
"""

class PlaywrightRepliesScraper:
    def __init__(self, username=None, password=None, target_handle=None):
        self.username = username or X_USERNAME
        self.password = password or X_PASSWORD
        self.target_handle = target_handle or TARGET_HANDLE
        self.browser = None
        self.page = None
    
    async def setup_browser(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=BROWSER_SETTINGS["headless"]
        )
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
        print(f"Logging in as {self.username}...")
        await self.page.goto("https://x.com/login")
        await self.page.wait_for_load_state("networkidle")
        try:
            username_input = await self.page.wait_for_selector(
                'input[autocomplete="username"], input[placeholder*="username"], input[placeholder*="email"], input[placeholder*="phone"]',
                timeout=10000
            )
            await username_input.fill(self.username)
            next_button = await self.page.wait_for_selector(
                'div[role="button"]:has-text("Next"), div[role="button"]:has-text("Continue"), button:has-text("Next"), button:has-text("Continue")',
                timeout=5000
            )
            await next_button.click()
            await self.page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Username step failed: {e}")
            try:
                username_input = await self.page.wait_for_selector('input[autocomplete="username"]', timeout=5000)
                await username_input.fill(self.username)
            except:
                pass
        try:
            password_input = await self.page.wait_for_selector(
                'input[type="password"], input[autocomplete="current-password"]',
                timeout=10000
            )
            await password_input.fill(self.password)
            login_button = await self.page.wait_for_selector(
                'div[role="button"]:has-text("Log in"), button:has-text("Log in"), div[data-testid="LoginButton"]',
                timeout=5000
            )
            await login_button.click()
        except Exception as e:
            print(f"Password step failed: {e}")
            raise
        try:
            await self.page.wait_for_selector(
                '[data-testid="SideNav_AccountSwitcher_Button"], [data-testid="AppTabBar_Home_Link"], nav',
                timeout=15000
            )
            print("Login successful!")
        except Exception as e:
            print(f"Login verification failed: {e}")
            if await self.page.locator('text=Two-factor authentication').count() > 0:
                print("2FA required - please handle manually")
                await self.page.pause()
            else:
                raise Exception("Login failed - could not verify successful login")
    
    async def navigate_to_replies(self):
        print(f"🧭 Navigating to {self.target_handle}'s replies page...")
        try:
            print(f"📍 Step 1: Going to profile replies page...")
            await self.page.goto(f"https://x.com/{self.target_handle}/with_replies")
            await self.page.wait_for_load_state("networkidle")
            print(f"✅ Replies page loaded: {self.page.url}")
            await self.page.wait_for_timeout(3000)
            current_url = self.page.url
            print(f"📍 Current URL: {current_url}")
            if "/replies" in current_url.lower():
                print("✅ Already on replies page!")
                await self.page.wait_for_timeout(2000)
                return
            replies_tab_selectors = [
                'a[href*="/replies"]',
                'nav a:has-text("Replies")',
                '[data-testid="primaryColumn"] a:has-text("Replies")',
                'a:has-text("Replies")',
                '[role="tab"]:has-text("Replies")'
            ]
            replies_tab = None
            for i, selector in enumerate(replies_tab_selectors, 1):
                try:
                    print(f"🔍 Trying selector {i}/{len(replies_tab_selectors)}: {selector}")
                    replies_tab = await self.page.wait_for_selector(selector, timeout=5000)
                    if replies_tab and await replies_tab.is_visible():
                        print(f"✅ Found replies tab with selector: {selector}")
                        break
                    else:
                        print(f"❌ Tab found but not visible: {selector}")
                        replies_tab = None
                except Exception as e:
                    print(f"❌ Selector failed: {selector} - {e}")
                    continue
            if replies_tab:
                print(f"🖱️  Clicking replies tab...")
                await replies_tab.click()
                await self.page.wait_for_load_state("networkidle")
                await self.page.wait_for_timeout(3000)
                print(f"✅ Clicked replies tab, new URL: {self.page.url}")
            else:
                print("⚠️  No replies tab found, trying direct URL...")
                await self.page.goto(f"https://x.com/{self.target_handle}/replies")
                await self.page.wait_for_load_state("networkidle")
                await self.page.wait_for_timeout(3000)
                print(f"✅ Direct navigation completed: {self.page.url}")
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
            print("🎉 Navigation to replies page completed!")
        except Exception as e:
            print(f"❌ Navigation failed: {e}")
            print(f"📍 Current URL: {self.page.url}")
            print("🔄 Attempting to continue anyway...")
    
    async def execute_extraction_script(self):
        print("🚀 Starting extraction script execution...")
        print(f"📍 Current URL: {self.page.url}")
        max_retries = 5
        for attempt in range(max_retries):
            try:
                print(f"📝 Extraction attempt {attempt + 1}/{max_retries}")
                print("=" * 50)
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
                    await self.page.wait_for_timeout(5000)
                else:
                    print("💥 All extraction attempts failed")
                    raise Exception(f"Extraction failed after {max_retries} attempts: {e}")
    
    async def _handle_extraction_error(self):
        print("🔧 Attempting to recover from extraction error...")
        try:
            print("🔄 Refreshing page...")
            await self.page.reload()
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(3000)
            if await self.page.locator('text=Log in').count() > 0:
                print("⚠️  Lost login session, attempting to re-login...")
                await self.login()
                await self.navigate_to_replies()
        except Exception as e:
            print(f"⚠️  Recovery attempt failed: {e}")
    
    async def _execute_script_with_multiple_methods(self):
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
    
    async def _execute_via_evaluate(self):
        print("⚡ Executing script directly...")
        current_url = self.page.url
        if "compose" in current_url.lower():
            print("⚠️  Page navigated to compose, trying to go back...")
            await self.page.go_back()
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(3000)
        return await self.page.evaluate(EXTRACTION_SCRIPT)
    
    async def _execute_via_devtools(self):
        print("🔧 Using CDP for script execution...")
        try:
            cdp = await self.page.context.new_cdp_session(self.page)
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
        print("📜 Injecting script tag...")
        current_url = self.page.url
        if "compose" in current_url.lower():
            print("⚠️  Page navigated to compose, trying to go back...")
            await self.page.go_back()
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(3000)
        await self.page.evaluate(f"""
            const script = document.createElement('script');
            script.textContent = `{EXTRACTION_SCRIPT}`;
            document.head.appendChild(script);
        """)
        await self.page.wait_for_timeout(5000)
        result = await self.page.evaluate("window.lastExtractionResult || null")
        if result:
            return result
        return await self._extract_from_page()
    
    async def _extract_from_page(self):
        print("🔄 Fallback: extracting data directly from page...")
        posts = await self.page.evaluate("""
            const articles = document.querySelectorAll('article');
            const posts = [];
            articles.forEach(article => {
                const textElem = article.querySelector('div[data-testid=\"tweetText\"]');
                const timeElem = article.querySelector('time');
                const userLinks = article.querySelectorAll('a[href^=\"/\"][role=\"link\"]');
                let username = null, author = null;
                for (const link of userLinks) {
                    const match = link.getAttribute('href').match(/^\/(.+)$/);
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
                pageType: 'replies',
                dateStr: new Date().toISOString().split('T')[0],
                posts: posts,
                totalPosts: posts.length
            };
        """)
        return posts
    
    async def save_results(self, results):
        if not results or not results.get('posts'):
            print("No results to save")
            return None
        output_dir = Path("extracted_data")
        output_dir.mkdir(exist_ok=True)
        filename = f"{results['username']}_{results['pageType']}_{results['dateStr']}.json"
        filepath = output_dir / filename
        # Remove previous file for same user/pageType/date
        pattern = f"{results['username']}_{results['pageType']}_{results['dateStr']}.json"
        for oldfile in glob(str(output_dir / pattern)):
            try:
                os.remove(oldfile)
            except Exception as e:
                print(f"Could not remove old file {oldfile}: {e}")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Results saved to: {filepath}")
        return filepath
    
    async def run(self):
        try:
            await self.setup_browser()
            await self.login()
            await self.navigate_to_replies()
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
    scraper = PlaywrightRepliesScraper()
    result = await scraper.run()
    if result["success"]:
        print(f"✅ Scraping completed successfully!")
        print(f"📁 Results saved to: {result['filepath']}")
        print(f"📊 Total posts extracted: {result['total_posts']}")
    else:
        print(f"❌ Scraping failed: {result['error']}")

if __name__ == "__main__":
    asyncio.run(main()) 