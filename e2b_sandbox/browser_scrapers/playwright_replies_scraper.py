"""
SCHEMA DOCUMENTATION
--------------------
| Field              | Type           | Description                                 |
|--------------------|----------------|---------------------------------------------|
| id                 | string         | Unique identifier of the tweet/post         |
| parent_id          | string/null    | Parent tweet's ID, if reply                 |
| author             | string         | Display name                                |
| username           | string         | Handle                                      |
| text               | string         | Full post content (all textual and inline content) |
| permalink          | string         | Full status URL                             |
| date               | string         | ISO 8601 timestamp                          |
| media              | array[string]  | Media absolute URLs                         |
| retweet            | object/null    | Embedded retweeted/quoted tweet (recursively)|
| reply_chain        | array[object]  | Ancestor tweets (in order, root-first)      |
| replying_to        | string/null    | Reply target handle/context                 |
| perplexity_context | object/null    | Embedded @AskPerplexity context (if exists) |
| poll               | object/null    | Poll details, if present                    |
| status             | string/null    | "unavailable" if deleted/protected         |
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
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
async () => {
  const sleep = ms => new Promise(res => setTimeout(res, ms));

  function omitNulls(obj) {
    if (Array.isArray(obj)) {
      return obj.map(omitNulls);
    } else if (obj && typeof obj === 'object') {
      const out = {};
      for (const k in obj) {
        if (obj[k] !== null && obj[k] !== undefined) {
          out[k] = omitNulls(obj[k]);
        }
      }
      return out;
    } else {
      return obj;
    }
  }

  async function expandAllShowMore() {
    let buttons = Array.from(document.querySelectorAll('article button')).filter(
      btn => /show more|show thread/i.test(btn.textContent)
    );
    for (const btn of buttons) {
      try { btn.click(); await sleep(200); } catch (e) {}
    }
  }

  // Expand any "Show more" in a specific article
  async function expandShowMoreInArticle(article) {
    const showMoreBtn = article.querySelector('button[role="button"]:not([aria-disabled="true"])');
    if (showMoreBtn && /show more|show thread/i.test(showMoreBtn.innerText)) {
      showMoreBtn.click();
      await sleep(200);
    }
  }

  function extractIdFromPermalink(permalink) {
    if (!permalink) return null;
    const match = permalink.match(/status\/(\d+)/);
    return match ? match[1] : null;
  }

  // Robust author/username extraction
  function extractAuthorUsername(article, fallbackUsername, fallbackAuthor) {
    let results = [];
    const anchors = Array.from(article.querySelectorAll('a[role="link"][href^="/"]'));
    for (const anchor of anchors) {
      const usernameMatch = anchor.getAttribute('href').replace('/', '');
      const displaySpans = anchor.querySelectorAll('span');
      let displaySpan = displaySpans[displaySpans.length - 1];
      if (displaySpan && displaySpan.textContent.trim() &&
          usernameMatch && !['home', 'explore', 'messages', 'notifications'].includes(usernameMatch.toLowerCase())) {
        results.push({username: usernameMatch, author: displaySpan.textContent});
      }
    }
    // Prefer the result whose username matches expected username; fallback to first non-overlay span.
    let chosen = (fallbackUsername && results.find(r => r.username === fallbackUsername)) || results[0];
    if (chosen) return chosen;
    // Fallback: first visible span not labeled as overlay/status
    const overlayLabels = ["You reposted", "Pinned", "Promoted", "Reposted", "Retweeted"];
    const allSpans = Array.from(article.querySelectorAll('span'));
    for (const span of allSpans) {
      const txt = span.textContent.trim();
      if (txt && !overlayLabels.some(lab => txt.includes(lab))) {
        return {username: fallbackUsername || null, author: txt};
      }
    }
    // If not found, fallback to known profile information
    if (fallbackUsername && fallbackAuthor) return {username: fallbackUsername, author: fallbackAuthor};
    return {username: null, author: null};
  }

  async function extractTweetFromArticle(article, warnings, recursionDepth = 0, seen = new Set(), fallbackUsername = null, fallbackAuthor = null) {
    if (!article) return null;
    await expandShowMoreInArticle(article);
    // Extract id and permalink early for cycle detection
    const timeElem = article.querySelector('time');
    const linkElem = timeElem ? timeElem.parentElement : null;
    const permalink = linkElem && linkElem.getAttribute('href') ? 'https://x.com' + linkElem.getAttribute('href') : null;
    const id = extractIdFromPermalink(permalink);
    const uniqueKey = id || permalink || article.innerText.slice(0, 30);
    if (seen.has(uniqueKey)) {
      warnings.push({ message: 'Cycle detected in thread/quote structure', id, permalink });
      return null;
    }
    if (recursionDepth > 5) {
      warnings.push({ message: 'Max recursion depth exceeded', id, permalink });
      return null;
    }
    seen.add(uniqueKey);
    // Robust author/username extraction
    const {author, username} = extractAuthorUsername(article, fallbackUsername, fallbackAuthor);
    if (!username) warnings.push({ message: 'Missing username', articleText: article.innerText });
    if (!author) warnings.push({ message: 'Missing author', articleText: article.innerText });
    const date = timeElem ? timeElem.getAttribute('datetime') : null;
    // Extract full visible text from tweetText div
    const textElem = article.querySelector('div[data-testid="tweetText"]');
    const text = textElem ? textElem.innerText : '';
    if (!id) warnings.push({ message: 'Missing tweet ID', articleText: text });
    let media = [];
    article.querySelectorAll('img, video').forEach(m => {
      if (m.src && !m.src.includes('profile_images')) media.push(m.src);
    });
    let poll = null;
    const pollElem = article.querySelector('[role="group"] [aria-label*="poll"]');
    if (pollElem) {
      const options = Array.from(pollElem.querySelectorAll('div[role="button"]')).map(opt => opt.innerText);
      poll = { options };
    }
    // --- Robust extraction of embedded quote tweets ---
    // Find all nested <article> elements inside div[data-testid='tweet'] (quote tweet cards)
    let retweet = null;
    const quotedElems = article.querySelectorAll('div[data-testid="tweet"] article');
    if (quotedElems.length > 0) {
      // Expand all show more buttons in quoted tweets before extraction
      for (const quoted of quotedElems) {
        await expandShowMoreInArticle(quoted);
      }
      // Recursively extract the first quoted tweet as the main retweet
      retweet = await extractTweetFromArticle(quotedElems[0], warnings, recursionDepth + 1, new Set(seen), username, author);
      // If more than one quoted article is present, log a warning
      if (quotedElems.length > 1) {
        warnings.push({ message: 'Multiple quoted articles found in quote card', id, permalink, quotedCount: quotedElems.length });
      }
      // If a quote card is visually present but retweet is still null, log a warning
      if (!retweet) {
        warnings.push({ message: 'Quote card present but retweet extraction failed', id, permalink });
      }
    } else {
      // If a quote card is visually present (e.g., by selector), but no article found, log a warning
      const quoteCard = article.querySelector('div[data-testid="tweet"]');
      if (quoteCard) {
        warnings.push({ message: 'Quote card visually present but no <article> found', id, permalink });
      }
    }
    // --- End robust quote tweet extraction ---
    // Recursively extract reply_chain (all ancestors)
    let reply_chain = [];
    let parent_id = null;
    let replying_to = null;
    let current = article;
    let replySeen = new Set(seen);
    while (current) {
      let parent = null;
      const contextElem = current.parentElement?.parentElement?.querySelector('div[aria-label*="Timeline: Conversation"] article');
      if (contextElem && contextElem !== current && !replySeen.has(contextElem)) {
        parent = contextElem;
      } else {
        let prev = current.previousElementSibling;
        while (prev) {
          if (prev.tagName === 'ARTICLE' && !replySeen.has(prev)) {
            parent = prev;
            break;
          }
          prev = prev.previousElementSibling;
        }
      }
      if (parent && !replySeen.has(parent)) {
        const parentObj = await extractTweetFromArticle(parent, warnings, recursionDepth + 1, new Set(replySeen), username, author);
        if (parentObj) reply_chain.unshift(parentObj);
        replySeen.add(parent);
        current = parent;
      } else {
        break;
      }
    }
    if (reply_chain.length > 0) {
      parent_id = reply_chain[reply_chain.length - 1].id || null;
    }
    const header = Array.from(article.querySelectorAll('span, div')).find(el => /replying to/i.test(el.textContent));
    replying_to = header ? header.textContent.trim() : null;
    // Perplexity context (bottom-most @AskPerplexity reply)
    let perplexity_context = null;
    let root = article;
    while (root.nextElementSibling) {
      if (root.nextElementSibling.tagName === 'ARTICLE') {
        root = root.nextElementSibling;
      } else {
        break;
      }
    }
    const textElemRoot = root.querySelector('div[data-testid="tweetText"]');
    const textRoot = textElemRoot ? textElemRoot.innerText : '';
    if (/@AskPerplexity/i.test(textRoot)) {
      perplexity_context = await extractTweetFromArticle(root, warnings, recursionDepth + 1, new Set(seen), username, author);
    }
    let status = null;
    if (!id) status = 'unavailable';
    let result = {
      id,
      parent_id,
      author,
      username,
      text,
      permalink,
      date,
      media: media || [],
      retweet,
      reply_chain: reply_chain || [],
      replying_to,
      perplexity_context,
      poll,
      status
    };
    return omitNulls(result);
  }

  // Extract composer text if present
  function extractComposerText() {
    const composer = document.querySelector('div[role="textbox"]');
    if (composer && composer.innerText.trim()) {
      return composer.innerText;
    }
    return null;
  }

  let lastHeight = 0, sameCount = 0, maxNoChange = 15;
  let allPosts = new Map();
  let warnings = [];
  while (sameCount < maxNoChange) {
    await expandAllShowMore();
    const articles = document.querySelectorAll('article');
    for (const article of articles) {
      const postObj = await extractTweetFromArticle(article, warnings, 0, new Set());
      if (postObj && postObj.id && !allPosts.has(postObj.id)) {
        allPosts.set(postObj.id, postObj);
      } else if (postObj && postObj.permalink && !allPosts.has(postObj.permalink)) {
        allPosts.set(postObj.permalink, postObj);
      }
    }
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(3500);
    let newHeight = document.body.scrollHeight;
    if (newHeight === lastHeight) {
      sameCount++;
    } else {
      sameCount = 0;
      lastHeight = newHeight;
    }
  }
  const postsArr = Array.from(allPosts.values()).map(omitNulls);
  let username = postsArr.length > 0 ? postsArr[0].username : null;
  let pageType = 'replies';
  let dateStr = null;
  if (postsArr.length > 0 && postsArr[0].date) {
    dateStr = postsArr[0].date.split('T')[0];
  }
  // Extract composer text if present
  const composer_text = extractComposerText();
  return { posts: postsArr, totalPosts: postsArr.length, username, pageType, dateStr, composer_text };
}
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
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"📍 Step 1: Going to profile replies page (attempt {attempt+1})...")
                await self.page.goto(f"https://x.com/{self.target_handle}/with_replies")
                await self.page.wait_for_load_state("networkidle")
                print(f"✅ Replies page loaded: {self.page.url}")
                await self.page.wait_for_timeout(3000)
                # Wait for a robust replies-specific selector
                print("🔍 Waiting for replies content to load...")
                await self.page.wait_for_selector('article', timeout=20000)
                print("✅ At least one reply article found.")
                return
            except PlaywrightTimeoutError:
                print(f"⚠️  Timeout waiting for replies content (attempt {attempt+1})")
                if attempt < max_retries - 1:
                    print("🔄 Retrying navigation...")
                    await self.page.reload()
                    await self.page.wait_for_timeout(3000)
                else:
                    print("❌ Navigation failed after retries. Proceeding anyway.")
                    return
            except Exception as e:
                print(f"❌ Navigation error: {e}")
                if attempt < max_retries - 1:
                    print("🔄 Retrying navigation...")
                    await self.page.reload()
                    await self.page.wait_for_timeout(3000)
                else:
                    print("❌ Navigation failed after retries. Proceeding anyway.")
                    return

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
                    print(f"👤 Username: {result.get('username')}")
                    return result
                else:
                    print("⚠️  Script executed but returned no data")
                    raise Exception("Script executed but returned no data")
            except Exception as e:
                if 'Execution context was destroyed' in str(e):
                    print(f"⚠️  Execution context destroyed (likely due to navigation/reload). Retrying after short wait...")
                    await self.page.wait_for_timeout(5000)
                    continue
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
            try:
                print(f"🔧 Trying injection method {i}/{len(methods)}: {method.__name__}")
                print(f"⏱️  Starting method: {method.__name__}")
                result = await method()
                if result and result.get('posts'):
                    print(f"✅ Method {method.__name__} succeeded!")
                    return result
                else:
                    print(f"⚠️  Method {method.__name__} returned no data")
            except Exception as e:
                if 'Execution context was destroyed' in str(e):
                    print(f"⚠️  Execution context destroyed during {method.__name__}. Retrying...")
                    await self.page.wait_for_timeout(3000)
                    continue
                print(f"❌ Method {method.__name__} failed: {e}")
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
        # Only inject a valid function body, not an illegal return statement
        script_body = EXTRACTION_SCRIPT.strip()
        if script_body.startswith('async () => {'):
            script_body = script_body[len('async () => {'):-1].strip()
        await self.page.evaluate(f'(async () => {{ {script_body} }})')
        await self.page.wait_for_timeout(5000)
        # Try to get result
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
    
    def omit_nulls(obj):
        if isinstance(obj, dict):
            return {k: omit_nulls(v) for k, v in obj.items() if v is not None}
        elif isinstance(obj, list):
            return [omit_nulls(i) for i in obj]
        else:
            return obj

    async def save_results(self, results):
        if not results or not results.get('posts'):
            print("No results to save")
            return None
        output_dir = Path("extracted_data")
        output_dir.mkdir(exist_ok=True)
        filename = f"{results['username']}_{results['pageType']}_{results['dateStr']}.json"
        filepath = output_dir / filename
        # Remove previous file for same user/pageType/date
        username = results.get('username')
        if not username and results.get('posts'):
            username = results['posts'][0].get('username', 'unknown')
        pageType = results.get('pageType', 'replies')
        dateStr = results.get('dateStr')
        if not dateStr and results.get('posts'):
            first_date = results['posts'][0].get('date')
            if first_date:
                dateStr = first_date.split('T')[0]
        pattern = f"{username}_{pageType}_{dateStr}.json"
        for oldfile in glob(str(output_dir / pattern)):
            try:
                os.remove(oldfile)
            except Exception as e:
                print(f"Could not remove old file {oldfile}: {e}")
        # Add root-level metadata
        scrape_metadata = {
            "scrape_timestamp": datetime.utcnow().isoformat() + 'Z',
            "code_version": "1.0.0",  # Update as needed
            "user": username,
            "pageType": pageType,
            "dateStr": dateStr,
            "warnings": results.get('warnings', []),
            "totalPosts": results.get('totalPosts', len(results.get('posts', [])))
        }
        # Omit nulls from posts and metadata
        output = omit_nulls({ **scrape_metadata, "posts": results['posts'] })
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
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
                "total_posts": results.get('totalPosts', len(results.get('posts', []))),
                "username": results.get('username'),
                "pageType": results.get('pageType'),
                "dateStr": results.get('dateStr')
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