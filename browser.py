"""
browser.py — Playwright-based browser automation for ALEKS.

Handles:
  1. Launch browser and login
  2. Navigate to specific activity
  3. Extract question text from the page
  4. Submit and advance to next question
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

        user_data_dir = str(Path(config.__file__).parent / "browser_profile")

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=config.HEADLESS,
            slow_mo=config.SLOW_MO,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            # 1820×1024 shows the same content area as a 1366×768 window at 75% zoom
            # without any CSS/device-scale tricks that break getBoundingClientRect().
            viewport={"width": 1820, "height": 1024},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )

        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self.page.set_default_timeout(config.TIMEOUT)
        log.info("Browser ready")

    def close(self):
        """Clean shutdown."""
        if self._context:
            self._context.close()
        elif self._browser:
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

        # ALEKS login forms — the page has 3 variants:
        #   1. Standalone /login page form  (#login_name_alone)
        #   2. Header dropdown form         (#login_name_full)
        #   3. Mobile form                  (#login_name_mobile)
        # The submit "button" is actually a <div class="login_button">.
        username_selectors = [
            '#login_name_alone',            # Standalone /login page
            '#login_name_full',             # Header dropdown
            '#login_name_mobile',           # Mobile layout
            'input.login_name',             # Class fallback (all variants)
            'input[name="username"]',       # Generic name attr
            'input[autocomplete="username"]',
        ]

        password_selectors = [
            '#login_pass_alone',            # Standalone /login page
            '#login_pass_full',             # Header dropdown
            '#login_pass_mobile',           # Mobile layout
            'input.login_password',         # Class fallback
            'input[name="password"]',       # Generic name attr
            'input[type="password"]',       # Type fallback
        ]

        submit_selectors = [
            '#login_container .login_button',  # Standalone page submit div
            '.login_form .login_button',       # Any form's submit div
            'div.login_button',                # Generic div submit
            'button[type="submit"]',           # Standard button fallback
            'input[type="submit"]',            # Standard input fallback
            'button:has-text("Log In")',        # English text
            'button:has-text("Iniciar sesión")',  # Spanish text
            'button:has-text("ACCESO")',        # LATAM variant
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
        submitted = False
        for selector in submit_selectors:
            try:
                btn = self.page.wait_for_selector(selector, timeout=3000)
                if btn:
                    btn.click()
                    log.info(f"  Login submitted via: {selector}")
                    submitted = True
                    break
            except Exception:
                continue

        # Fallback: submit the form directly via JavaScript
        if not submitted:
            try:
                self.page.evaluate("""
                    () => {
                        const form = document.querySelector(
                            '#login_container form.login_form, '
                            + 'form#login_full, '
                            + 'form#login_mobile'
                        );
                        if (form) form.submit();
                    }
                """)
                log.info("  Login submitted via JS form.submit()")
            except Exception:
                # Last resort: press Enter
                self.page.keyboard.press("Enter")
                log.info("  Login submitted via Enter key")

        # Wait for dashboard
        self.page.wait_for_load_state("networkidle")
        time.sleep(3)

        # Verify login succeeded
        if "login" in self.page.url.lower():
            self.screenshot("login_failed")
            raise AutomationError("Login failed — still on login page")

        log.info("Login successful")

    # ─── Class Selection ────────────────────────────────────────────

    def get_active_classes(self) -> list[dict]:
        """
        Read the active classes from the 'Mis clases' dashboard.
        Returns a list of dicts: [{"name": "...", "index": 0}, ...]
        """
        self.page.wait_for_load_state("networkidle")
        time.sleep(3)

        page_title = self.page.title()
        page_url = self.page.url
        log.info(f"  Page: {page_title} ({page_url})")

        # ALEKS class cards are NOT standard <a> tags — they are custom
        # JavaScript-rendered div/span elements with click handlers.
        # Use page.evaluate to dump ALL visible elements with their tag info.
        classes = self.page.evaluate(r"""
            () => {
                const results = [];

                // Scan ALL elements in document order between
                // "Clases Activas" and "Clases Inactivas" sections
                const allElements = Array.from(document.querySelectorAll('*'));
                let inActiveSection = false;

                for (const el of allElements) {
                    const fullText = el.textContent.trim();

                    // Check direct text nodes for section headings
                    const directText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join(' ');

                    // Start collecting after "Clases Activas"
                    if (!inActiveSection) {
                        if (/Clases Activas|Active Classes/i.test(directText) ||
                            /^(Clases Activas|Active Classes)\s*\(\d+\)$/i.test(fullText)) {
                            inActiveSection = true;
                            continue;
                        }
                    }

                    // Stop at "Clases Inactivas"
                    if (inActiveSection) {
                        if (/Clases Inactivas|Inactive Classes/i.test(directText) ||
                            /^(Clases Inactivas|Inactive Classes)\s*\(\d+\)$/i.test(fullText)) {
                            break;
                        }

                        // Look for ANY clickable element with class-like text
                        // ALEKS uses divs/spans with onclick, not <a> tags
                        const ownText = (el.innerText || '').trim();
                        const tag = el.tagName;

                        // Class names contain course codes + group identifiers
                        if (ownText && ownText.length > 15 && ownText.length < 200 &&
                            !/Agregar|Cambiar|detalles|privacidad|términos|Instructor|Institución|Acceso|Progreso|ACTUALES|OCULTAS/i.test(ownText.substring(0, 40))) {
                            // Only look at "leaf" clickable elements (not huge containers)
                            const childLinks = el.querySelectorAll('a, [onclick], [role="link"], [role="button"]');
                            const isLeaf = el.children.length < 5;
                            const hasClickHandler = el.onclick || el.getAttribute('onclick') || 
                                                     el.getAttribute('role') === 'link' ||
                                                     el.getAttribute('role') === 'button' ||
                                                     el.style.cursor === 'pointer' ||
                                                     tag === 'A' || tag === 'BUTTON';
                            
                            if (isLeaf && (hasClickHandler || tag === 'DIV' || tag === 'SPAN' || tag === 'A')) {
                                // Check if this looks like a class name (has Group/Grupo or course code)
                                if (/Group|Grupo|[A-Z]{2}\d{4}/i.test(ownText)) {
                                    results.push({
                                        name: ownText.substring(0, 100),
                                        index: results.length,
                                        tag: tag,
                                    });
                                }
                            }
                        }
                    }
                }

                if (results.length > 0) return results;

                // Debug: dump ALL visible elements between the sections
                // to help diagnose what the class card element looks like
                const debug = [];
                let inSection = false;
                for (const el of allElements) {
                    const ft = el.textContent.trim();
                    const dt = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join(' ');

                    if (!inSection && (/Clases Activas/i.test(dt) || /^Clases Activas\s*\(\d+\)$/i.test(ft))) {
                        inSection = true; continue;
                    }
                    if (inSection && (/Clases Inactivas/i.test(dt) || /^Clases Inactivas\s*\(\d+\)$/i.test(ft))) {
                        break;
                    }
                    if (inSection) {
                        const it = (el.innerText || '').trim();
                        if (it && it.length > 5 && it.length < 200) {
                            debug.push({
                                tag: el.tagName,
                                cls: (typeof el.className === 'string' ? el.className : '').substring(0, 40),
                                text: it.substring(0, 80),
                                children: el.children.length,
                            });
                        }
                    }
                }
                return [{name: '__DEBUG__', items: debug}];
            }
        """)

        # Handle debug output
        if (classes and len(classes) == 1 and
                isinstance(classes[0], dict) and classes[0].get('name') == '__DEBUG__'):
            log.warning("  Could not detect class cards. Elements in active section:")
            for item in classes[0].get('items', [])[:25]:
                log.warning(f"    <{item['tag']}> cls=\"{item.get('cls','')}\" "
                            f"children={item['children']} → {item['text'][:50]}")
            return []

        log.info(f"  Found {len(classes)} active class(es)")
        for c in classes:
            log.info(f"    • {c['name']} ({c.get('tag', '?')})")

        return classes

    def select_class(self, _class_index: int = 0, class_name: str = "") -> bool:
        """
        Click on an active class to enter it.
        
        Args:
            class_index: Which class to select (0-based) when multiple exist.
            class_name: The class name text to click (from get_active_classes).
        
        Returns True if a class was selected, False otherwise.
        """
        log.info("Selecting class...")
        self.page.wait_for_load_state("networkidle")
        time.sleep(2)

        # Strategy 1: Click by exact class name text (works for any element type)
        if class_name:
            try:
                # Use a short unique substring to avoid matching containers
                # The class name from get_active_classes might be multi-line,
                # so try the first line (the course title)
                search = class_name.split('\n')[0].strip()
                if len(search) > 20:
                    search = search[:50]  # Use a reasonable prefix

                el = self.page.get_by_text(search, exact=False).first
                if el.count() > 0:
                    el.click()
                    log.info(f"  Entered class via text match: {search}")
                    self.page.wait_for_load_state("networkidle")
                    time.sleep(3)
                    return True
            except Exception as e:
                log.info(f"  Text match failed: {e}")

        # Strategy 2: Click any visible element containing "Group" or "Grupo"
        for search_text in ["Group 1", "Grupo 1", "Group", "Grupo"]:
            try:
                # Search ALL elements, not just <a> tags
                el = self.page.get_by_text(search_text, exact=False).first
                if el.count() > 0:
                    el.click()
                    log.info(f"  Entered class via '{search_text}' text match")
                    self.page.wait_for_load_state("networkidle")
                    time.sleep(3)
                    return True
            except Exception:
                pass

        # Strategy 3: JS click on any element with course-code pattern
        clicked = self.page.evaluate(r"""
            () => {
                const allElements = Array.from(document.querySelectorAll('*'));
                for (const el of allElements) {
                    const text = (el.innerText || '').trim();
                    // Look for course code patterns like "EM2026" or "Group 153"
                    if (text && text.length > 10 && text.length < 150 &&
                        /[A-Z]{2}\d{4}/.test(text) && 
                        /Group|Grupo/i.test(text) &&
                        el.children.length < 5) {
                        el.click();
                        return text.substring(0, 80);
                    }
                }
                return null;
            }
        """)

        if clicked:
            log.info(f"  Entered class via JS: {clicked}")
            self.page.wait_for_load_state("networkidle")
            time.sleep(3)
            return True

        log.warning("  Could not find any class to select")
        self.screenshot("class_selection_failed")
        return False

    # ─── Navigation ─────────────────────────────────────────────────

    def navigate_to_activity(self, activity_id: int):
        """
        Navigate to a specific ALEKS activity via the Assignments sidebar.

        Flow:
        1. Click "Assignments" in the left sidebar
        2. Wait for the assignment list to load
        3. Find the search/filter input and type the activity name
        4. Click the matching activity item
        """
        activity_name = config.ACTIVITIES.get(activity_id, "")
        if not activity_name:
            raise AutomationError(f"Unknown activity ID: {activity_id}")


        log.info(f"Navigating to: {activity_name}")

        # ── Step 1: Open hamburger menu, then click "Assignments" ────
        self.page.wait_for_load_state("networkidle")
        time.sleep(1)

        # Open the sidebar via the hamburger (≡) button
        hamburger_selectors = [
            '[aria-label*="menu" i]',
            '[aria-label*="menú" i]',
            '[title*="menu" i]',
            '[title*="menú" i]',
            'button[aria-label*="menu" i]',
            'button[aria-label*="navigation" i]',
            'a[aria-label*="menu" i]',
            '[class*="hamburger"]',
            '[id*="menu"]',
            '[class*="menu-toggle"]',
            '[class*="nav-toggle"]',
            'button.Navbar__menu__button',
            'button:has(svg)',           # icon-only button
            'button.MuiIconButton-root', # Material UI icon button
        ]
        # Wait for the dashboard to finish loading before probing the menu
        try:
            self.page.wait_for_selector('[title*="menu" i], button:has(svg)', timeout=10_000)
            time.sleep(1) # Extra buffer for react hydration
        except Exception:
            pass

        for sel in hamburger_selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    time.sleep(1)
                    log.info(f"  Opened hamburger menu ({sel})")
                    break
            except Exception:
                continue

        # "Actividades" in Spanish, "Assignments" in English
        assignments_selectors = [
            'a:has-text("Actividades")',
            'li:has-text("Actividades")',
            'a:has-text("Assignments")',
            'li:has-text("Assignments")',
            '[class*="nav"] >> text=Actividades',
            'text=Actividades',
            'text=Assignments',
        ]
        clicked_sidebar = False
        for sel in assignments_selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    self.page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    log.info("  Clicked 'Actividades' in sidebar")
                    clicked_sidebar = True
                    break
            except Exception:
                continue

        if not clicked_sidebar:
            log.warning("  Could not click sidebar 'Actividades' — trying URL fragment")
            current_url = self.page.url.split("#")[0]
            self.page.goto(current_url + "#assignmentList")
            self.page.wait_for_load_state("networkidle")
            time.sleep(2)

        # If no activities are visible, click "Mostrar próximas actividades"
        try:
            toggle = self.page.locator(
                'text=Mostrar próximas actividades, text=Show upcoming activities'
            ).first
            if toggle.is_visible():
                toggle.click()
                time.sleep(1)
                log.info("  Toggled 'Mostrar próximas actividades'")
        except Exception:
            pass

        # ── Step 2: Click the magnifier / search button ─────────────
        magnifier_selectors = [
            '[aria-label*="search" i]',
            '[aria-label*="buscar" i]',
            '[title*="search" i]',
            '[title*="buscar" i]',
            'button[aria-label*="search" i]',
            'button[aria-label*="buscar" i]',
            '[class*="search"] button',
            '[class*="search-icon"]',
            'button:has([class*="search"])',
            'button:has(svg[class*="search" i])',
            # generic: any small button that contains an svg (icon button) near the list
            '[class*="assignment"] button:has(svg)',
            '[class*="list"] button:has(svg)',
            # Sometimes ALEKS uses "filter" instead of search
            '[aria-label*="filter" i]',
            '[aria-label*="filtro" i]',
        ]
        for sel in magnifier_selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    time.sleep(1)
                    log.info(f"  Clicked magnifier / search button ({sel})")
                    break
            except Exception:
                continue

        # ── Step 3: Find the now-visible search input and paste ──────
        search_selectors = [
            'input[placeholder*="search" i]',
            'input[placeholder*="filter" i]',
            'input[placeholder*="buscar" i]',
            'input[type="search"]',
            'input[class*="search"]',
            'input[class*="filter"]',
            '[class*="search"] input',
            '[class*="filter"] input',
            'input:visible',
        ]
        search_input = None
        for sel in search_selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    search_input = el
                    log.info(f"  Found search input via: {sel}")
                    break
            except Exception:
                continue

        if search_input:
            search_input.click()
            search_input.fill(str(activity_id))   # type only the number
            time.sleep(1.5)
            log.info(f"  Pasted activity number '{activity_id}' into search bar")
        else:
            log.warning("  Search input not found after clicking magnifier")

        # ── Step 5: Click the activity link in the results table ────────
        time.sleep(1)  # let results render

        # Use JS to find the smallest visible element whose text starts with "Activity N"
        time.sleep(1)
        rect = self.page.evaluate(f"""
            () => {{
                const tag = "Activity {activity_id}";
                const SKIP = new Set(['HTML','BODY','TABLE','THEAD','TBODY','TR','SCRIPT','STYLE']);
                let best = null;
                let bestArea = Infinity;
                const all = Array.from(document.querySelectorAll('*'));
                for (const el of all) {{
                    if (SKIP.has(el.tagName)) continue;
                    // Use textContent for matching (no layout side effects)
                    const t = (el.textContent || '').trim();
                    if (!t.startsWith(tag)) continue;
                    if (el.offsetWidth === 0 || el.offsetHeight === 0) continue;
                    const area = el.offsetWidth * el.offsetHeight;
                    if (area < bestArea) {{
                        bestArea = area;
                        best = el;
                    }}
                }}
                if (!best) return null;
                const r = best.getBoundingClientRect();
                return {{ x: r.left, y: r.top, w: r.width, h: r.height, tag: best.tagName }};
            }}
        """)

        if rect:
            cx = rect["x"] + rect["w"] / 2
            cy = rect["y"] + rect["h"] / 2
            log.info(f"  Found <{rect['tag']}> at ({cx:.0f},{cy:.0f}) — clicking")
            self.page.mouse.click(cx, cy)
            time.sleep(2)
            return

        self.screenshot("nav_failed")
        log.warning(f"Could not find activity element. Check screenshots/nav_failed.png")

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

    def get_attempt_info(self) -> dict:
        """
        Read attempt information from the ALEKS page.

        ALEKS shows "Attempt X of 3" (or "Intento X de 3") ONLY when a
        question was previously answered incorrectly.  First attempts never
        show this text.

        Returns:
            {
                "attempt":  int  – current attempt number (1-3), 0 if not found
                "max":      int  – max attempts (usually 3), 0 if not found
                "is_retry": bool – True when attempt > 1 (question was wrong before)
            }
        """
        import re as _re

        try:
            body_text = self.page.evaluate(
                "() => (document.body.innerText || '').substring(0, 5000)"
            )

            patterns = [
                # "Question Attempt: 3 of 3"  ← actual ALEKS header format
                r'[Aa]ttempt[:\s]+(\d+)\s+(?:of|from)\s+(\d+)',
                # "Intento: 2 de 3"
                r'[Ii]ntento[:\s]+(\d+)\s+de\s+(\d+)',
                # "Attempt 2/3" or "Attempt: 2/3"
                r'[Aa]ttempt[:\s]+(\d+)/(\d+)',
                r'[Ii]ntento[:\s]+(\d+)/(\d+)',
                # "2 of 3 attempts"
                r'(\d+)\s+(?:of|de|from)\s+(\d+)\s+[Aa]ttempts?',
                r'(\d+)\s+de\s+(\d+)\s+[Ii]ntentos?',
            ]

            for pattern in patterns:
                m = _re.search(pattern, body_text)
                if m:
                    attempt = int(m.group(1))
                    max_att = int(m.group(2))
                    log.info(f"  Attempt info detected: {attempt}/{max_att}")
                    return {"attempt": attempt, "max": max_att, "is_retry": attempt > 1}

        except Exception as e:
            log.warning(f"  get_attempt_info failed: {e}")

        return {"attempt": 0, "max": 0, "is_retry": False}

    def get_current_question_number(self) -> int:
        """
        Read the current question number from the ALEKS page header.

        ALEKS always shows "Question X of 14" (or "Pregunta X de 14") in the
        top bar. This is more reliable than inspecting nav-bubble CSS state.

        Returns the question number, or 0 if it cannot be determined.
        """
        try:
            num = self.page.evaluate(r"""
                () => {
                    const text = document.body.innerText || '';
                    // "Question 4 of 14", "Pregunta 4 de 14", "Q4/14"
                    const m = text.match(
                        /(?:Question|Pregunta|Q\.?)\s+(\d+)\s+(?:of|de|\/)\s+\d+/i
                    );
                    if (m) return parseInt(m[1], 10);
                    return 0;
                }
            """)
            if num and num > 0:
                return int(num)
        except Exception as e:
            log.warning(f"  get_current_question_number failed: {e}")
        return 0

    def get_bubble_status(self, question_num: int) -> str:
        """
        DOM-based color check for question bubble N.

        Finds the nav bubble element by its number text, then reads the
        computed background-color of the element (or its nearest colored
        ancestor) directly from the DOM — no screenshots, no pixel math,
        no hardcoded positions.

        Returns:
          'correct'   — green  (✓ answered right)
          'incorrect' — red    (✗ answered wrong, may have attempts left)
          'active'    — teal / gray (unanswered or currently selected)
        """
        status = self.page.evaluate(r"""
            (qNum) => {
                // ── 1. Find the bubble element for this question number ──────
                const candidates = Array.from(document.querySelectorAll(
                    'button, [role="button"], span, li, td, div, a'
                )).filter(el => {
                    const t = (el.textContent || '').trim();
                    // Bubble text is "✓ 1", "× 2", "≡ 5" etc — match digits only
                    const re = new RegExp('^[^0-9]*' + qNum + '[^0-9]*$');
                    if (!re.test(t)) return false;
                    const r = el.getBoundingClientRect();
                    // Must be in the top navigation strip
                    return (
                        r.top >= 50 && r.top < 160 &&
                        r.width > 20 && r.width < 120 &&
                        r.height > 20 && r.height < 120 &&
                        el.offsetParent !== null
                    );
                });

                if (!candidates.length) return 'unknown';

                // Pick the smallest element (the bubble itself, not a wrapper)
                const bubble = candidates.reduce((a, b) => {
                    const ra = a.getBoundingClientRect();
                    const rb = b.getBoundingClientRect();
                    return ra.width * ra.height <= rb.width * rb.height ? a : b;
                });

                // ── 2. CSS class-name check (fastest path) ───────────────────
                const fullCls = [bubble, bubble.parentElement, bubble.parentElement?.parentElement]
                    .filter(Boolean)
                    .map(n => (typeof n.className === 'string' ? n.className : ''))
                    .join(' ')
                    .toLowerCase();

                if (/\bcorrect\b|\bright\b|\bsuccess\b|\bdone\b/.test(fullCls)) return 'correct';
                if (/\bincorrect\b|\bwrong\b|\berror\b|\bfail\b/.test(fullCls))  return 'incorrect';

                // ── 3. Walk up the DOM to find the first non-transparent bg ──
                function parseBg(node) {
                    for (let n = node; n && n !== document.body; n = n.parentElement) {
                        const bg = window.getComputedStyle(n).backgroundColor;
                        if (!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') continue;
                        const m = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
                        if (!m) continue;
                        const r = +m[1], g = +m[2], b = +m[3];
                        // Skip white / near-white / light-gray backgrounds
                        if (r > 210 && g > 210 && b > 210) continue;
                        return { r, g, b };
                    }
                    return null;
                }

                const color = parseBg(bubble);
                if (color) {
                    const { r, g, b } = color;
                    // Green: g clearly dominant over r and b
                    if (g > 100 && g > r * 1.3 && g > b * 1.3) return 'correct';
                    // Red: r clearly dominant
                    if (r > 120 && r > g * 1.8 && r > b * 1.5) return 'incorrect';
                }

                return 'active';
            }
        """, question_num)

        label = status if status in ('correct', 'incorrect', 'active') else 'active'

        icons = {'correct': '✅', 'incorrect': '❌', 'active': '○'}
        colors = {'correct': '\033[1;32m', 'incorrect': '\033[1;31m', 'active': '\033[0;36m'}
        rst = '\033[0m'
        print(
            f"\n{colors[label]}  ┌─ BUBBLE Q{question_num}: {icons[label]} {label.upper()}{rst}\n"
            f"{colors[label]}  └──────────────────────────────────{rst}\n"
        )
        return label

    def is_correct_answer_shown(self) -> bool:
        """
        Check whether ALEKS is currently displaying the 'Correct Answer' reveal.

        This only appears after ALL attempts on a question have been exhausted.
        It means the question is dead — no more input is possible.

        Checks both DOM elements (by class/id) and visible page text.
        """
        try:
            found = self.page.evaluate(r"""
                () => {
                    // 1. Known CSS classes/ids ALEKS uses for the answer reveal
                    const el = document.querySelector(
                        '[class*="correct_answer"], [class*="correctAnswer"], ' +
                        '[class*="correct-answer"], [id*="correct_answer"], ' +
                        '[id*="correctAnswer"], [class*="solution_reveal"], ' +
                        '[class*="solutionReveal"]'
                    );
                    if (el && el.offsetParent !== null) return true;

                    // 2. Visible text scan — look for the reveal heading
                    // Matches "CORRECT ANSWER", "Correct Answer:", "Respuesta Correcta", etc.
                    const body = (document.body.innerText || '').substring(0, 4000);
                    return (
                        /correct\s+answer/i.test(body) ||
                        /respuesta\s+correcta/i.test(body) ||
                        /the correct answer is/i.test(body) ||
                        /la respuesta correcta es/i.test(body)
                    );
                }
            """)
            return bool(found)
        except Exception as e:
            log.warning(f"  is_correct_answer_shown failed: {e}")
            return False

    def should_skip_question(self, question_num: int) -> bool:
        """Backward-compat wrapper — returns True for correct or incorrect bubbles."""
        return self.get_bubble_status(question_num) in ('correct', 'incorrect')

    def read_question(self) -> str:
        """
        Extract the full ALEKS question as plain text.

        ALEKS renders math using custom ansedimage_* elements.
        Each one contains a <span class="visually-hidden dont_read"> with
        the human-readable math text, e.g.:
            " h = a cosine ( w t − c ) "
            " w = begin fraction 3 π over 7 end fraction radians over seconds "

        Strategy:
        1. Clone #algoPrompt (the question container)
        2. Replace every ansedimage element with its visually-hidden text
        3. Strip remaining hidden/UI elements
        4. Return clean plain text
        """
        text = self.page.evaluate(r"""
            () => {
                // Find the question container — ALEKS uses id="algoPrompt"
                const container = document.getElementById('algoPrompt') ||
                                  document.querySelector('.aleks_content_style') ||
                                  document.querySelector('[class*="problem"]') ||
                                  document.querySelector('main') ||
                                  document.body;

                const clone = container.cloneNode(true);

                // 1. Replace each ansedimage_* span with its readable hidden text
                //    The hidden span has class "visually-hidden dont_read" and
                //    contains the math as plain English: " h = a cosine ( w t − c ) "
                clone.querySelectorAll('[id^="ansedimage_"]').forEach(el => {
                    const hidden = el.querySelector('.visually-hidden.dont_read, .visually-hidden');
                    const readable = hidden ? hidden.textContent.trim() : el.textContent.trim();
                    const span = document.createElement('span');
                    span.textContent = ' ' + readable + ' ';
                    el.replaceWith(span);
                });

                // 2. Remove scripts, styles, canvas, svg, hidden UI elements,
                //    navigation buttons, copyright footer, and the "CORRECT ANSWER"
                //    reveal section that appears after a failed final attempt.
                clone.querySelectorAll(
                    'script, style, canvas, svg, ' +
                    'button, input, textarea, select, ' +
                    '.ansed_root, .ansed_tree, .ansed_canvas, ' +
                    '[aria-hidden="true"], [class*="toolbar"], [class*="navbar"], ' +
                    '[class*="footer"], [class*="copyright"], [class*="legal"], ' +
                    '[class*="correct_answer"], [class*="correctAnswer"], ' +
                    '[class*="solution"], [class*="explanation"], ' +
                    '[class*="nav"], [class*="sidebar"], [class*="header"]'
                ).forEach(el => el.remove());

                // 3. Get raw text, then strip known noise line-by-line
                const raw = (clone.innerText || clone.textContent || '').trim();
                const NOISE = [
                    /next question/i, /previous question/i, /save for later/i,
                    /submit assignment/i, /correct answer/i, /respuesta correcta/i,
                    /mcgraw.?hill/i, /terms of use/i, /privacy/i,
                    /©\s*20\d\d/i, /graph data/i, /\[graph/i,
                    /imgur\.com/i, /i\.imgur/i,
                ];
                const lines = raw.split('\n').filter(line => {
                    const t = line.trim();
                    if (!t) return false;
                    return !NOISE.some(rx => rx.test(t));
                });
                return lines.join('\n').trim();
            }
        """)

        full_question = (text or "").strip()
        if not full_question:
            self.screenshot("no_question_found")
            log.warning("Could not extract question text")

        return full_question

    # ─── Answer Input ───────────────────────────────────────────────

    def input_answer(self, answer: str, solver=None) -> bool:
        """
        Input the AI answer into the ALEKS answer field.

        Delegates to ALEKSInputLayer. Pass solver so graph questions can ask
        the chatbot for axis ranges if DOM data-attributes are absent.
        """
        from aleks_math_input import ALEKSInputLayer
        layer = ALEKSInputLayer(self.page, solver=solver)
        return layer.input_answer(answer)

    # ─── Pre/Post Verification ───────────────────────────────────────

    def press_continue(self):
        """
        Press the Continue / OK / Continuar / Siguiente button.
        Searches ALL element types (button, a, div, span, input) because
        ALEKS doesn't always use standard <button> tags.
        """
        time.sleep(0.5)

        labels = ['Continue', 'Continuar', 'OK', 'Ok', 'Siguiente', 'Next']

        # ── 1. Playwright locator: text= matches any visible element ──
        for label in labels:
            try:
                loc = self.page.locator(f'text="{label}"').first
                if loc.is_visible():
                    loc.click()
                    log.info(f"  ✅ Pressed '{label}' (locator)")
                    time.sleep(2)
                    return True
            except Exception:
                continue

        # ── 2. Query selector: button, a, div, span, input ──
        all_selectors = [
            'button', 'a', 'input[type="button"]', 'input[type="submit"]',
            '[role="button"]', 'div', 'span',
        ]
        for selector in all_selectors:
            try:
                elements = self.page.query_selector_all(selector)
                for el in elements:
                    if el.is_visible():
                        text = (el.text_content() or '').strip()
                        if text.lower() in [l.lower() for l in labels]:
                            el.click()
                            log.info(f"  ✅ Pressed '{text}' ({selector})")
                            time.sleep(2)
                            return True
            except Exception:
                continue

        # ── 3. get_by_text fallback ──
        for label in labels:
            try:
                el = self.page.get_by_text(label, exact=True).first
                if el.is_visible():
                    el.click()
                    log.info(f"  ✅ Pressed '{label}' (get_by_text)")
                    time.sleep(2)
                    return True
            except Exception:
                continue

        log.info("  ⚠️ No Continue/OK button found")
        return False

    # ─── Submit & Navigate ──────────────────────────────────────────

    def submit(self):
        """
        Click the submit/check button.

        Never hangs: each selector has a 2-second timeout.
        Falls back to JS coordinate scan, then Enter key.
        Does NOT call wait_for_load_state (that was the hang source).
        """
        # ONLY check/verify buttons — never "Entregar actividad" (Submit Assignment)
        submit_selectors = [
            'button:has-text("Check")',
            'button:has-text("Verificar")',
            'button:has-text("Comprobar")',
            'button[class*="check"]',
            'input[type="submit"]',
            '#submit-btn',
            '.submit-button',
        ]

        for selector in submit_selectors:
            try:
                btn = self.page.wait_for_selector(selector, timeout=2_000)
                if btn and btn.is_visible():
                    btn.click(timeout=3_000)
                    log.info(f"  Submitted via: {selector}")
                    time.sleep(1.5)
                    return
            except Exception:
                continue

        # JS coordinate fallback — never click "Submit Assignment" / "Entregar actividad"
        submit_hints = ["Check", "Verificar", "Comprobar"]
        coord = self.page.evaluate("""
            (hints) => {
                const FORBIDDEN = [
                    "submit assignment", "entregar actividad",
                    "submit", "entregar",
                ];
                const els = Array.from(document.querySelectorAll(
                    'button, input[type="submit"], input[type="button"], [role="button"]'
                ));
                for (const el of els) {
                    if (!el.offsetParent) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 5 || r.height < 5) continue;
                    const t = (el.textContent || el.value || '').trim().toLowerCase();
                    if (FORBIDDEN.some(f => t.includes(f))) continue;
                    for (const h of hints) {
                        if (t.includes(h.toLowerCase()))
                            return { x: r.left + r.width/2, y: r.top + r.height/2 };
                    }
                }
                return null;
            }
        """, submit_hints)

        if coord:
            self.page.mouse.click(coord["x"], coord["y"])
            log.info(f"  Submitted via JS coord ({coord['x']:.0f},{coord['y']:.0f})")
            time.sleep(1.5)
            return

        # Last resort
        log.warning("  No submit button found — pressing Enter")
        self.page.keyboard.press("Enter")
        time.sleep(1.5)

    def check_result(self, solver=None) -> str:
        """
        DOM-based result check after submitting an answer.

        Strategy:
          1. CSS class scan — looks for ALEKS feedback banner classes
          2. Visible text scan — standalone "Correct" / "Incorrect" word
          3. Chatbot vision fallback (solver required) — screenshot → classify_result()

        Returns 'correct', 'incorrect', or 'unknown'.
        """
        time.sleep(2)  # Give ALEKS time to evaluate and show the result banner

        # ── 1 & 2: DOM inspection ────────────────────────────────────────
        dom_result = self.page.evaluate(r"""
            () => {
                // ── Class-based check (fastest) ──────────────────────────
                const correctEl = document.querySelector(
                    '[class*="correct_banner"], [class*="correctBanner"], '  +
                    '[class*="correct_icon"],   [class*="correctIcon"],   '  +
                    '[class*="feedback_correct"],[class*="feedbackCorrect"]'
                );
                if (correctEl && correctEl.offsetParent !== null) return 'correct';

                const incorrectEl = document.querySelector(
                    '[class*="incorrect_banner"], [class*="incorrectBanner"], ' +
                    '[class*="incorrect_icon"],   [class*="incorrectIcon"],   ' +
                    '[class*="feedback_incorrect"],[class*="feedbackIncorrect"]'
                );
                if (incorrectEl && incorrectEl.offsetParent !== null) return 'incorrect';

                // ── Visible text scan — match standalone word only ────────
                // Walk all visible text nodes; ignore "Correct Answer" reveal
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    {
                        acceptNode: n =>
                            n.parentElement && n.parentElement.offsetParent !== null
                                ? NodeFilter.FILTER_ACCEPT
                                : NodeFilter.FILTER_REJECT
                    }
                );
                let node;
                let hasCorrect = false, hasIncorrect = false;
                while ((node = walker.nextNode())) {
                    const t = node.textContent.trim();
                    if (/^(Correct|Correcto)$/i.test(t))   hasCorrect   = true;
                    if (/^(Incorrect|Incorrecto)$/i.test(t)) hasIncorrect = true;
                }
                // "Correct Answer" reveal uses a paragraph, not a standalone word,
                // so standalone "Correct" here safely means the feedback banner.
                if (hasIncorrect) return 'incorrect';
                if (hasCorrect)   return 'correct';

                return null;
            }
        """)

        if dom_result in ('correct', 'incorrect'):
            log.info(f"  check_result (DOM): {dom_result}")
            _c = '\033[1;32m' if dom_result == 'correct' else '\033[1;31m'
            print(f"{_c}  │ Result (DOM): {dom_result.upper()}\033[0m")
            return dom_result

        # ── 3: Chatbot vision fallback ───────────────────────────────────
        if solver is not None:
            try:
                from pathlib import Path as _Path
                tmp = _Path(__file__).parent / "screenshots" / "_result_check.png"
                self.page.screenshot(path=str(tmp))
                vision_result = solver.classify_result(tmp)
                try:
                    tmp.unlink()
                except Exception:
                    pass
                if vision_result in ('correct', 'incorrect'):
                    log.info(f"  check_result (chatbot): {vision_result}")
                    _c = '\033[1;32m' if vision_result == 'correct' else '\033[1;31m'
                    print(f"{_c}  │ Result (chatbot): {vision_result.upper()}\033[0m")
                    return vision_result
            except Exception as e:
                log.warning(f"  check_result chatbot fallback failed: {e}")

        log.warning("  check_result: inconclusive — returning 'unknown'")
        return "unknown"

    def click_next(self, current_question_num: int = 0):
        """
        Advance to the next question.

        Strategy order:
          1. Text-based "Siguiente/Next/Continue" button (works after correct answers)
          2. The > arrow button in the question navigation bar
          3. Click the next question-number bubble directly (most reliable after incorrect)
          4. Keyboard ArrowRight on the nav area (last resort)

        Pass current_question_num so strategy 3 can click bubble N+1 directly.
        """
        NEXT_LABELS = [
            'siguiente', 'continuar', 'next', 'continue',
            'ok', 'aceptar', 'avanzar',
            'siguiente pregunta', 'next question',
        ]

        # ── Strategy 1: click the explicit next question-number bubble directly ───────
        # This keeps the UI perfectly synchronized with the python loop.
        # It avoids the "off-by-one" desync caused by ALEKS auto-advancing.
        if current_question_num > 0:
            next_num = current_question_num + 1
            bubble_clicked = self.page.evaluate("""
                (nextNum) => {
                    // ALEKS bubble text is "✓ 1", "× 2", "≡ 5" — match digit only.
                    const re = new RegExp('^[^0-9]*' + nextNum + '[^0-9]*$');

                    // Walk UP from the matched text element to the nearest
                    // interactive ancestor (button / role=button / <a>) so the
                    // click lands on the actual nav trigger, not an inner span.
                    function clickableAncestor(el) {
                        for (let n = el; n && n !== document.body; n = n.parentElement) {
                            const tag = n.tagName;
                            const role = (n.getAttribute('role') || '').toLowerCase();
                            if (tag === 'BUTTON' || tag === 'A' || role === 'button' || role === 'link')
                                return n;
                        }
                        return el;
                    }

                    const all = Array.from(document.querySelectorAll(
                        'button, [role="button"], span, li, td, div, a'
                    ));
                    for (const el of all) {
                        const t = (el.textContent || '').trim();
                        if (re.test(t) && el.offsetParent !== null) {
                            const r = el.getBoundingClientRect();
                            if (r.top < 200 && r.width > 5 && r.width < 120 && r.height < 120) {
                                clickableAncestor(el).click();
                                return true;
                            }
                        }
                    }
                    return false;
                }
            """, next_num)
            if bubble_clicked:
                log.info(f"  Advanced to bubble {next_num}")
                time.sleep(2)
                return

        # ── Strategy 2: text-based button (fallback if bubble isn't found) ──────────────
        clicked = self.page.evaluate("""
            (labels) => {
                const clickable = Array.from(
                    document.querySelectorAll('button, a, input[type="submit"], div[role="button"]')
                );
                for (const el of clickable) {
                    const t = (el.textContent || el.value || '').trim().toLowerCase();
                    if (labels.some(l => t === l || t.startsWith(l)) && el.offsetParent !== null) {
                        el.click();
                        return t;
                    }
                }
                return null;
            }
        """, NEXT_LABELS)
        if clicked:
            log.info(f"  Advanced via text button: '{clicked}'")
            time.sleep(2)
            return

        # ── Strategy 3: > arrow button in the question nav bar ───────────────
        arrow_clicked = self.page.evaluate("""
            () => {
                const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
                for (const el of candidates) {
                    const t = (el.textContent || '').trim();
                    const lbl = (el.getAttribute('aria-label') || '').toLowerCase();
                    const cls = (el.className || '').toLowerCase();
                    if ((t === '>' || t === '›' || t === '→' || t === '▶' ||
                         lbl.includes('next') || lbl.includes('siguiente') ||
                         cls.includes('next-arrow') || cls.includes('nextarrow') ||
                         cls.includes('nav-next') || cls.includes('arrow-right'))
                        && el.offsetParent !== null) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if arrow_clicked:
            log.info("  Advanced via > nav arrow")
            time.sleep(2)
            return

        # ── Strategy 4: Playwright role-based buttons ─────────────────────────
        for text in ["Siguiente", "Continuar", "Next", "Continue", "OK", "Aceptar", "Avanzar"]:
            try:
                btn = self.page.get_by_role("button", name=text, exact=False).first
                if btn and btn.is_visible():
                    btn.click()
                    log.info(f"  Advanced via role button: '{text}'")
                    time.sleep(2)
                    return
            except Exception:
                continue

        # ── Strategy 5: CSS selectors ──────────────────────────────────────────
        for selector in [
            'button.next_button', 'button[class*="next"]', 'button[class*="siguiente"]',
            'a.next_button', 'a[class*="next"]',
            'input[type="submit"][value*="next" i]',
            'input[type="submit"][value*="siguiente" i]',
        ]:
            try:
                el = self.page.query_selector(selector)
                if el and el.is_visible():
                    el.click()
                    log.info(f"  Advanced via selector: {selector}")
                    time.sleep(2)
                    return
            except Exception:
                continue

        log.warning(f"  Could not advance from question {current_question_num} — all strategies failed")


class AutomationError(Exception):
    """Unrecoverable automation failure."""
    pass
