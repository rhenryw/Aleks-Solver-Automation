"""
browser.py — Playwright-based browser automation for ALEKS.

Handles:
  1. Launch browser and login
  2. Navigate to specific activity
  3. Extract question text from the page
  4. Input answers (text fields, multiple choice, dropdowns)
  5. Submit and advance to next question
"""

import logging
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

import config

log = logging.getLogger("browser")


class AleksBrowser:
    """
    Automated browser session for ALEKS.
    
    Usage:
        browser = AleksBrowser()
        browser.launch()
        browser.login("user@email.com", "password")
        browser.navigate_to_activity(10)
        
        while browser.has_question():
            question = browser.read_question()
            browser.input_answer(answer)
            browser.submit()
        
        browser.close()
    """

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        self.screenshots_dir = Path("screenshots")
        self.screenshots_dir.mkdir(exist_ok=True)

    # ─── Lifecycle ──────────────────────────────────────────────────

    def launch(self):
        """Launch browser with human-like settings."""
        log.info("Launching browser...")
        self._playwright = sync_playwright().start()

        self._browser = self._playwright.chromium.launch(
            headless=config.HEADLESS,
            slow_mo=config.SLOW_MO,
        )

        # Context with realistic viewport and user agent
        self._context = self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )

        self.page = self._context.new_page()
        self.page.set_default_timeout(config.TIMEOUT)
        log.info("Browser ready")

    def close(self):
        """Clean shutdown."""
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        log.info("Browser closed")

    def screenshot(self, name: str = "debug"):
        """Save a screenshot for debugging."""
        if self.page and config.SCREENSHOT_ON_ERROR:
            path = self.screenshots_dir / f"{name}.png"
            self.page.screenshot(path=str(path))
            log.info(f"Screenshot saved: {path}")

    # ─── Authentication ─────────────────────────────────────────────

    def login(self, username: str, password: str):
        """
        Log into ALEKS.
        
        ALEKS login flow:
        1. Go to aleks.com
        2. Click "Sign In" or go to login page
        3. Enter username (email) and password
        4. Click login button
        5. Wait for dashboard to load
        """
        log.info(f"Logging in as {username}...")
        self.page.goto(config.ALEKS_LOGIN_URL)
        self.page.wait_for_load_state("networkidle")

        # ALEKS uses various login form selectors — try common ones
        # These selectors may need updating if ALEKS changes their UI
        username_selectors = [
            'input[name="login_data"]',
            'input[name="username"]',
            'input[name="email"]',
            'input[type="email"]',
            '#username',
            '#login_data',
        ]

        password_selectors = [
            'input[name="password"]',
            'input[type="password"]',
            '#password',
        ]

        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            '.login-button',
            '#sign-in-btn',
            'button:has-text("Sign In")',
            'button:has-text("Log In")',
        ]

        # Fill username
        filled = False
        for selector in username_selectors:
            try:
                el = self.page.wait_for_selector(selector, timeout=3000)
                if el:
                    el.click()
                    el.fill(username)
                    filled = True
                    log.info(f"  Username entered via: {selector}")
                    break
            except Exception:
                continue

        if not filled:
            self.screenshot("login_fail_username")
            raise AutomationError("Could not find username field")

        # Fill password
        filled = False
        for selector in password_selectors:
            try:
                el = self.page.wait_for_selector(selector, timeout=3000)
                if el:
                    el.click()
                    el.fill(password)
                    filled = True
                    log.info(f"  Password entered via: {selector}")
                    break
            except Exception:
                continue

        if not filled:
            self.screenshot("login_fail_password")
            raise AutomationError("Could not find password field")

        # Submit
        for selector in submit_selectors:
            try:
                btn = self.page.wait_for_selector(selector, timeout=3000)
                if btn:
                    btn.click()
                    log.info(f"  Login submitted via: {selector}")
                    break
            except Exception:
                continue

        # Wait for dashboard
        self.page.wait_for_load_state("networkidle")
        time.sleep(3)

        # Verify login succeeded
        if "login" in self.page.url.lower():
            self.screenshot("login_failed")
            raise AutomationError("Login failed — still on login page")

        log.info("Login successful")

    # ─── Navigation ─────────────────────────────────────────────────

    def navigate_to_activity(self, activity_id: int):
        """
        Navigate to a specific ALEKS activity.
        
        Strategy:
        1. Look for the activity by its text on the page
        2. Or navigate via the ALEKS assignment/topic list
        """
        activity_name = config.ACTIVITIES.get(activity_id, "")
        if not activity_name:
            raise AutomationError(f"Unknown activity ID: {activity_id}")

        log.info(f"Navigating to: {activity_name}")

        # Wait for page to be ready
        self.page.wait_for_load_state("networkidle")
        time.sleep(2)

        # Strategy 1: Click on activity text directly
        # ALEKS shows topics/activities as clickable items
        search_texts = [
            activity_name,
            activity_name.split(" - ")[1] if " - " in activity_name else activity_name,
        ]

        for text in search_texts:
            try:
                link = self.page.get_by_text(text, exact=False).first
                if link:
                    link.click()
                    self.page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    log.info(f"  Found and clicked: {text}")
                    return
            except Exception:
                continue

        # Strategy 2: Look for topic/assignment links
        try:
            # ALEKS often uses numbered topic links
            topic_links = self.page.query_selector_all('a[class*="topic"], a[class*="activity"]')
            for link in topic_links:
                link_text = link.inner_text()
                if str(activity_id) in link_text or any(t in link_text for t in search_texts):
                    link.click()
                    self.page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    log.info(f"  Found via topic link: {link_text}")
                    return
        except Exception:
            pass

        self.screenshot("nav_failed")
        log.warning(f"Could not auto-navigate to {activity_name}. Navigate manually.")

    # ─── Question Reading ───────────────────────────────────────────

    def has_question(self) -> bool:
        """Check if there's a question on the current page."""
        question_selectors = [
            '.question-content',
            '.problem-text',
            '[class*="question"]',
            '[class*="problem"]',
            '.aleks-question',
            '#question-area',
        ]
        for selector in question_selectors:
            try:
                el = self.page.query_selector(selector)
                if el and el.inner_text().strip():
                    return True
            except Exception:
                continue

        # Fallback: check if any math content is visible
        try:
            math_el = self.page.query_selector('math, .MathJax, [class*="math"], .katex')
            if math_el:
                return True
        except Exception:
            pass

        return False

    def read_question(self) -> str:
        """
        Extract the full question text from the current page.
        
        ALEKS renders math using MathJax/KaTeX. We extract:
        1. The plain text question
        2. Any math expressions (converted to readable format)
        3. Multiple choice options if present
        """
        parts = []

        # Extract main question text
        question_selectors = [
            '.question-content',
            '.problem-text',
            '[class*="question"]',
            '[class*="problem"]',
            '#question-area',
        ]

        for selector in question_selectors:
            try:
                el = self.page.query_selector(selector)
                if el:
                    text = el.inner_text().strip()
                    if text and len(text) > 10:
                        parts.append(text)
                        break
            except Exception:
                continue

        # If no structured selector works, grab the main content area
        if not parts:
            try:
                # Get visible text from the main content area
                body_text = self.page.evaluate("""
                    () => {
                        const main = document.querySelector('main, [role="main"], .content, #content');
                        if (main) return main.innerText;
                        return document.body.innerText.substring(0, 2000);
                    }
                """)
                if body_text:
                    parts.append(body_text[:1500])
            except Exception:
                pass

        # Extract math expressions
        try:
            math_text = self.page.evaluate("""
                () => {
                    const maths = document.querySelectorAll(
                        'math, .MathJax, .katex, [class*="math-expr"]'
                    );
                    return Array.from(maths).map(m => m.textContent || m.alt || '').join(' ');
                }
            """)
            if math_text and math_text.strip():
                parts.append(f"Math: {math_text.strip()}")
        except Exception:
            pass

        # Extract multiple choice options
        try:
            options = self.page.evaluate("""
                () => {
                    const opts = document.querySelectorAll(
                        '[class*="choice"], [class*="option"], [class*="answer-choice"], label'
                    );
                    return Array.from(opts)
                        .map((o, i) => `${String.fromCharCode(65+i)}) ${o.innerText.trim()}`)
                        .filter(t => t.length > 4)
                        .join('\\n');
                }
            """)
            if options:
                parts.append(f"Options:\n{options}")
        except Exception:
            pass

        full_question = "\n".join(parts).strip()
        if not full_question:
            self.screenshot("no_question_found")
            log.warning("Could not extract question text")

        return full_question

    # ─── Answer Input ───────────────────────────────────────────────

    def input_answer(self, answer: str):
        """
        Input the answer into ALEKS.
        
        Detects the input type and uses the appropriate method:
        - Text field: type the answer
        - Multiple choice: click the right option
        - Dropdown: select the value
        """
        answer = answer.strip()
        log.info(f"  Inputting answer: {answer}")

        # Try multiple choice first (single letter A-D)
        if len(answer) == 1 and answer.upper() in "ABCDEFGH":
            if self._click_choice(answer.upper()):
                return

        # Try text input field
        input_selectors = [
            'input[type="text"]:visible',
            'input[class*="answer"]:visible',
            'input[class*="input"]:visible',
            'textarea:visible',
            '[contenteditable="true"]:visible',
            '.answer-input input',
            '#answer-input',
        ]

        for selector in input_selectors:
            try:
                el = self.page.wait_for_selector(selector, timeout=3000)
                if el:
                    el.click()
                    el.fill("")  # Clear first
                    el.type(answer, delay=50)  # Type with slight delay
                    log.info(f"  Typed into: {selector}")
                    return
            except Exception:
                continue

        # Try MathQuill/MathJax input (ALEKS uses these for math entry)
        try:
            math_input = self.page.query_selector('.mq-editable-field, .mathquill-editable')
            if math_input:
                math_input.click()
                self.page.keyboard.type(answer, delay=30)
                log.info("  Typed into MathQuill field")
                return
        except Exception:
            pass

        log.warning(f"  Could not find input field for answer: {answer}")
        self.screenshot("input_failed")

    def _click_choice(self, letter: str) -> bool:
        """Click a multiple choice option by letter (A, B, C, D...)."""
        index = ord(letter) - ord("A")

        choice_selectors = [
            f'[class*="choice"]:nth-child({index + 1})',
            f'[class*="option"]:nth-child({index + 1})',
            f'label:nth-of-type({index + 1})',
            f'input[type="radio"]:nth-of-type({index + 1})',
        ]

        for selector in choice_selectors:
            try:
                el = self.page.query_selector(selector)
                if el:
                    el.click()
                    log.info(f"  Clicked choice {letter} via: {selector}")
                    return True
            except Exception:
                continue

        # Try clicking by text content matching the letter
        try:
            choices = self.page.query_selector_all('[class*="choice"], [class*="option"], label')
            if index < len(choices):
                choices[index].click()
                log.info(f"  Clicked choice {letter} (index {index})")
                return True
        except Exception:
            pass

        return False

    # ─── Submit & Navigate ──────────────────────────────────────────

    def submit(self):
        """Click the submit/check/next button."""
        submit_selectors = [
            'button:has-text("Check")',
            'button:has-text("Submit")',
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button[class*="submit"]',
            'button[class*="check"]',
            'input[type="submit"]',
            '#submit-btn',
            '.submit-button',
        ]

        for selector in submit_selectors:
            try:
                btn = self.page.wait_for_selector(selector, timeout=3000)
                if btn and btn.is_visible():
                    btn.click()
                    log.info(f"  Submitted via: {selector}")
                    self.page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    return
            except Exception:
                continue

        # Fallback: press Enter
        log.info("  No submit button found, pressing Enter")
        self.page.keyboard.press("Enter")
        time.sleep(2)

    def click_next(self):
        """Click 'Next' or 'Continue' to advance to the next question."""
        next_selectors = [
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button:has-text("I am ready")',
            'a:has-text("Next")',
            '.next-button',
            '#next-btn',
        ]

        for selector in next_selectors:
            try:
                btn = self.page.wait_for_selector(selector, timeout=3000)
                if btn and btn.is_visible():
                    btn.click()
                    self.page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    return
            except Exception:
                continue

    def check_result(self) -> str:
        """Check if the answer was correct after submission."""
        try:
            # Look for success/error indicators
            success = self.page.query_selector(
                '[class*="correct"], [class*="success"], .feedback-correct'
            )
            if success:
                return "correct"

            wrong = self.page.query_selector(
                '[class*="incorrect"], [class*="wrong"], [class*="error"], .feedback-incorrect'
            )
            if wrong:
                return "incorrect"
        except Exception:
            pass

        return "unknown"


class AutomationError(Exception):
    """Unrecoverable automation failure."""
    pass
