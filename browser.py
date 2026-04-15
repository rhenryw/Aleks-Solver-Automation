"""
browser.py — Playwright-based browser automation for ALEKS.

Handles:
  1. Launch browser and login
  2. Navigate to specific activity
  3. Extract question text from the page
  4. Input answers (text fields, multiple choice, dropdowns)
  5. Submit and advance to next question
"""

import json
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
            'button[aria-label*="menu" i]',
            'button[aria-label*="navigation" i]',
            '[class*="hamburger"]',
            '[class*="menu-toggle"]',
            '[class*="nav-toggle"]',
            'button:has(svg)',           # icon-only button
            'button.MuiIconButton-root', # Material UI icon button
        ]
        for sel in hamburger_selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    time.sleep(1)
                    log.info("  Opened hamburger menu")
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
            'button[aria-label*="search" i]',
            'button[aria-label*="buscar" i]',
            '[class*="search"] button',
            '[class*="search-icon"]',
            'button:has([class*="search"])',
            'button:has(svg[class*="search" i])',
            # generic: any small button that contains an svg (icon button) near the list
            '[class*="assignment"] button:has(svg)',
            '[class*="list"] button:has(svg)',
        ]
        for sel in magnifier_selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    time.sleep(1)
                    log.info("  Clicked magnifier / search button")
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

    # ─── Question Screenshot ────────────────────────────────────────

    def capture_question_screenshot(self, name: str = "question") -> Path | None:
        """
        Screenshot ONLY the question body — not the nav, header, or answer inputs.
        Tries progressively broader selectors until something reasonable is found.
        Saves to tmp_screenshots/<name>.png.
        """
        tmp_dir = Path("tmp_screenshots")
        tmp_dir.mkdir(exist_ok=True)
        path = tmp_dir / f"{name}.png"

        # Ordered from most specific to broadest — stop at first visible element
        # that is large enough to contain a real question (>100px tall)
        selectors = [
            '.problem-text',
            '.question-content',
            '[class*="problem-body"]',
            '[class*="question-body"]',
            '[class*="exercise"]',
            '[class*="problem"]',
            '[class*="question"]',
            'main',
            '[role="main"]',
        ]
        try:
            for sel in selectors:
                el = self.page.query_selector(sel)
                if not el or not el.is_visible():
                    continue
                box = el.bounding_box()
                if box and box["height"] > 80:
                    el.screenshot(path=str(path))
                    log.info(f"  Screenshot ({sel}) → {path}")
                    return path

            # Last resort: clip to the center content area, avoiding top nav bar
            vp = self.page.viewport_size or {"width": 1366, "height": 768}
            clip = {"x": 250, "y": 80, "width": vp["width"] - 280, "height": vp["height"] - 100}
            self.page.screenshot(path=str(path), clip=clip)
            log.info(f"  Screenshot (center clip) → {path}")
            return path
        except Exception as e:
            log.warning(f"  Screenshot failed: {e}")
            return None

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

    def is_already_correct(self) -> bool:
        """
        Check if the current question is already marked correct.

        ALEKS shows this in two ways:
          1. A green "Correct" banner on screen
          2. The current question number bubble is green (has a checkmark ✓)
        """
        try:
            # Fast text check — green "Correct" banner
            if self.page.query_selector('text="Correct"') or \
               self.page.query_selector('text="Correcto"'):
                return True

            # Check if the active question number bubble is green (already answered)
            result = self.page.evaluate("""
                () => {
                    // ALEKS question number bubbles — find the active/selected one
                    // A correct question number has a green background or a checkmark inside
                    const bubbles = Array.from(document.querySelectorAll(
                        '[class*="question"] span, [class*="progress"] span, ' +
                        '[class*="questionNumber"], [class*="question_number"], ' +
                        'span[class*="green"], span[class*="correct"], ' +
                        '[class*="questionNav"] button, [class*="question-nav"] button'
                    ));

                    for (const el of bubbles) {
                        const style = window.getComputedStyle(el);
                        const bg = style.backgroundColor || '';
                        const text = (el.textContent || '').trim();

                        // Green background = already correct
                        const isGreen = bg.includes('0, 128') || bg.includes('34, 139') ||
                                        bg.includes('0, 153') || bg.includes('76, 175') ||
                                        bg.includes('56, 142') || bg.includes('46, 125');

                        // Must be the current question (has focus / aria-current / active class)
                        const cls = (el.className || '').toLowerCase();
                        const isCurrent = cls.includes('active') || cls.includes('current') ||
                                          cls.includes('selected') ||
                                          el.getAttribute('aria-current') === 'true' ||
                                          el.getAttribute('aria-current') === 'page';

                        if (isGreen && isCurrent) return true;

                        // Checkmark symbol inside current bubble
                        if ((text === '✓' || text.startsWith('✓')) && isCurrent) return true;
                    }
                    return false;
                }
            """)
            return bool(result)
        except Exception:
            return False

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

                // 2. Remove scripts, styles, canvas, svg, hidden UI elements
                clone.querySelectorAll(
                    'script, style, canvas, svg, ' +
                    'button, input, textarea, select, ' +
                    '.ansed_root, .ansed_tree, .ansed_canvas, ' +
                    '[aria-hidden="true"], [class*="toolbar"], [class*="navbar"]'
                ).forEach(el => el.remove());

                // 3. Return clean text
                return (clone.innerText || clone.textContent || '').trim();
            }
        """)

        full_question = (text or "").strip()
        if not full_question:
            self.screenshot("no_question_found")
            log.warning("Could not extract question text")

        return full_question

    # ─── Answer Input ───────────────────────────────────────────────

    def _clear_aleks_input(self):
        """Select all and delete content in the currently focused ALEKS input."""
        self.page.keyboard.press("Control+a")
        time.sleep(0.1)
        self.page.keyboard.press("Delete")
        time.sleep(0.1)
        # Second pass — ALEKS sometimes needs Backspace after Delete
        self.page.keyboard.press("Control+a")
        self.page.keyboard.press("Backspace")
        time.sleep(0.1)

    def _type_aleks_answer(self, answer: str):
        """
        Type an answer into the currently-focused ALEKS input field.

        ALEKS keyboard shortcuts for math notation:
          /        → fraction (numerator already typed, / moves to denominator)
          ^        → exponent (superscript)
          sqrt(x)  → type as sqrt then ( x )  — ALEKS recognises it
          *        → multiplication
          pi       → π
          inf      → ∞
          abs(x)   → |x|

        For a plain fraction like 3/4:
          - type "3", press "/", type "4", press Tab/Right to exit denominator
        """
        import re

        # Handle fractions: "3/4" → type numerator, /, denominator, then exit
        frac_match = re.fullmatch(r'(-?\d+)\s*/\s*(-?\d+)', answer.strip())
        if frac_match:
            num, den = frac_match.group(1), frac_match.group(2)
            self.page.keyboard.type(num, delay=40)
            self.page.keyboard.press("/")
            time.sleep(0.15)
            self.page.keyboard.type(den, delay=40)
            # Exit the denominator field
            self.page.keyboard.press("Tab")
            log.info(f"  Typed fraction {num}/{den}")
            return

        # For everything else type character by character
        self.page.keyboard.type(answer, delay=40)

    def input_answer(self, answer: str):
        """
        Input the answer into ALEKS.

        Priority order:
        1. Graph JSON  → plot on canvas
        2. Multiple choice (single letter) → click radio/button
        3. ALEKS custom answer input (.answerBoxInput, [id^='answerBox']) → type
        4. Standard text inputs → type
        5. MathQuill / contenteditable → type
        """
        answer = answer.strip()
        log.info(f"  Inputting answer: {answer}")

        # 1. Graph answer (JSON)
        graph_data = self._parse_graph_answer(answer)
        if graph_data:
            log.info("  Detected GRAPH answer — plotting on canvas")
            self._input_graph_answer(graph_data)
            return

        # 2. Multiple choice — single letter A-H
        if len(answer) == 1 and answer.upper() in "ABCDEFGH":
            if self._click_choice(answer.upper()):
                return

        # 3. ALEKS-specific answer box selectors (highest priority for text)
        aleks_selectors = [
            '[id^="answerBox"]',
            '[class*="answerBox"]',
            '[id^="answer_box"]',
            '[class*="answer_box"]',
            'input.answer',
            'input[name*="answer"]',
            'input[id*="answer"]',
        ]

        for selector in aleks_selectors:
            try:
                el = self.page.query_selector(selector)
                if el and el.is_visible():
                    el.click()
                    time.sleep(0.1)
                    self._clear_aleks_input()
                    self._type_aleks_answer(answer)
                    log.info(f"  Typed into ALEKS box: {selector}")
                    return
            except Exception:
                continue

        # 4. Generic text inputs
        generic_selectors = [
            'input[type="text"]:visible',
            'textarea:visible',
        ]

        for selector in generic_selectors:
            try:
                el = self.page.wait_for_selector(selector, timeout=3000)
                if el:
                    el.click()
                    time.sleep(0.1)
                    el.fill("")
                    self._clear_aleks_input()
                    self._type_aleks_answer(answer)
                    log.info(f"  Typed into: {selector}")
                    return
            except Exception:
                continue

        # 5. MathQuill / contenteditable
        try:
            math_input = self.page.query_selector(
                '.mq-editable-field, .mathquill-editable, [contenteditable="true"]'
            )
            if math_input and math_input.is_visible():
                math_input.click()
                time.sleep(0.1)
                self._clear_aleks_input()
                self._type_aleks_answer(answer)
                log.info("  Typed into math/contenteditable field")
                return
        except Exception:
            pass

        log.warning(f"  Could not find input field for answer: {answer}")
        self.screenshot("input_failed")

    # ─── Graph Answer Handling ──────────────────────────────────────

    def _parse_graph_answer(self, answer: str) -> dict | None:
        """
        Try to parse the answer as graph JSON data.
        
        Expected format from Claude:
        {
            "type": "graph",
            "asymptotes": [-3.14, 0, 3.14],
            "points": [[1.57, 1], [-1.57, -1]],
            "tool": "curve"  (optional: "line", "curve", "ray", "segment")
        }
        """
        try:
            data = json.loads(answer)
            if isinstance(data, dict) and data.get("type") == "graph":
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def _get_graph_canvas(self) -> dict | None:
        """
        Find the ALEKS graphing canvas and return its bounding box.
        
        ALEKS uses an SVG or canvas-based graph widget.
        Returns: {x, y, width, height} of the graph area, or None.
        """
        canvas_selectors = [
            'svg[class*="graph"]',
            'svg[class*="plot"]',
            'canvas[class*="graph"]',
            '.graph-container svg',
            '.plot-area',
            '.graph-area',
            '[class*="coordinate-plane"]',
            '[class*="coord-plane"]',
            'svg',  # Fallback: first SVG that looks like a graph
        ]

        for selector in canvas_selectors:
            try:
                elements = self.page.query_selector_all(selector)
                for el in elements:
                    bbox = el.bounding_box()
                    if bbox and bbox["width"] > 150 and bbox["height"] > 150:
                        log.info(f"  Graph canvas found via: {selector}")
                        log.info(f"    Position: ({bbox['x']:.0f}, {bbox['y']:.0f})  "
                                 f"Size: {bbox['width']:.0f}×{bbox['height']:.0f}")
                        return bbox
            except Exception:
                continue

        return None

    def _calibrate_grid(self, canvas_bbox: dict) -> dict:
        """
        Determine the coordinate-to-pixel mapping for the graph.
        
        Tries to read axis labels from the DOM to find the actual range.
        Falls back to a standard ±10 range which is common in ALEKS.
        
        Returns calibration dict with origin pixel and scale factors.
        """
        # Default range: standard ALEKS grid is typically -10 to 10
        x_min, x_max = -10, 10
        y_min, y_max = -10, 10

        # Try to read axis tick labels from the DOM
        try:
            tick_values = self.page.evaluate("""
                () => {
                    // Look for axis labels in SVG text elements or spans near the graph
                    const texts = document.querySelectorAll(
                        'svg text, .tick-label, [class*="axis"] text, [class*="tick"] text'
                    );
                    const values = [];
                    texts.forEach(t => {
                        const val = parseFloat(t.textContent);
                        if (!isNaN(val)) values.push(val);
                    });
                    return values;
                }
            """)
            if tick_values and len(tick_values) >= 4:
                x_min = min(tick_values)
                x_max = max(tick_values)
                y_min = x_min  # Assume symmetric axes
                y_max = x_max
                log.info(f"  Grid range detected from ticks: [{x_min}, {x_max}]")
        except Exception:
            pass

        # Try reading from ALEKS-specific data attributes
        try:
            grid_range = self.page.evaluate("""
                () => {
                    const g = document.querySelector('[data-x-min], [data-xmin]');
                    if (g) {
                        return {
                            xMin: parseFloat(g.getAttribute('data-x-min') || g.getAttribute('data-xmin')),
                            xMax: parseFloat(g.getAttribute('data-x-max') || g.getAttribute('data-xmax')),
                            yMin: parseFloat(g.getAttribute('data-y-min') || g.getAttribute('data-ymin')),
                            yMax: parseFloat(g.getAttribute('data-y-max') || g.getAttribute('data-ymax')),
                        };
                    }
                    return null;
                }
            """)
            if grid_range:
                x_min = grid_range.get("xMin", x_min)
                x_max = grid_range.get("xMax", x_max)
                y_min = grid_range.get("yMin", y_min)
                y_max = grid_range.get("yMax", y_max)
                log.info(f"  Grid range from data attrs: x[{x_min},{x_max}] y[{y_min},{y_max}]")
        except Exception:
            pass

        # Calculate pixel mapping
        # Origin (0,0) in pixel coordinates
        cx = canvas_bbox["x"]
        cy = canvas_bbox["y"]
        cw = canvas_bbox["width"]
        ch = canvas_bbox["height"]

        # Add small padding (ALEKS graphs have margin inside the canvas)
        padding_x = cw * 0.05
        padding_y = ch * 0.05
        plot_w = cw - 2 * padding_x
        plot_h = ch - 2 * padding_y

        # Pixels per math unit
        px_per_unit_x = plot_w / (x_max - x_min)
        px_per_unit_y = plot_h / (y_max - y_min)

        # Origin in screen pixels
        origin_px = cx + padding_x + (-x_min) * px_per_unit_x
        origin_py = cy + padding_y + (y_max) * px_per_unit_y

        calibration = {
            "x_min": x_min, "x_max": x_max,
            "y_min": y_min, "y_max": y_max,
            "origin_px": origin_px,
            "origin_py": origin_py,
            "px_per_unit_x": px_per_unit_x,
            "px_per_unit_y": px_per_unit_y,
            "canvas": canvas_bbox,
        }

        log.info(f"  Grid calibrated: origin=({origin_px:.0f},{origin_py:.0f}) "
                 f"scale=({px_per_unit_x:.1f},{px_per_unit_y:.1f}) px/unit")

        return calibration

    def _coord_to_pixel(self, x: float, y: float, cal: dict) -> tuple[float, float]:
        """
        Convert math coordinates (x, y) to screen pixel position.
        
        In screen coordinates, Y is inverted (increases downward).
        """
        px = cal["origin_px"] + x * cal["px_per_unit_x"]
        py = cal["origin_py"] - y * cal["px_per_unit_y"]  # Inverted Y
        return (px, py)

    def _select_graph_tool(self, tool_type: str = "curve"):
        """
        Select a drawing tool from the ALEKS graph tool palette.
        
        Common tools: 'curve', 'line', 'ray', 'segment', 'point'
        In the ALEKS palette (see screenshot), tools are icon buttons.
        """
        # Map tool names to possible selectors / icon positions
        # Spanish names from tutorial: "para volar"=curve, "semi recta"=ray,
        # "lápiz"=pencil/point, "tijera"=scissors/crop, "goma"=eraser
        tool_selectors = {
            "curve": [
                'button[title*="curve" i]',
                'button[aria-label*="curve" i]',
                'button[title*="parabola" i]',
                'button[title*="para volar" i]',
                '[class*="curve-tool"]',
                '[class*="tool"] button:nth-child(3)',
            ],
            "line": [
                'button[title*="line" i]',
                'button[aria-label*="line" i]',
                '[class*="line-tool"]',
                '[class*="tool"] button:nth-child(2)',
            ],
            "ray": [
                'button[title*="ray" i]',
                'button[aria-label*="ray" i]',
                'button[title*="semi recta" i]',
                'button[aria-label*="semi recta" i]',
                'button[title*="half" i]',
                '[class*="ray-tool"]',
                '[class*="tool"] button:nth-child(4)',
            ],
            "point": [
                'button[title*="point" i]',
                'button[aria-label*="point" i]',
                'button[title*="lápiz" i]',
                'button[title*="lapiz" i]',
                '[class*="point-tool"]',
                '[class*="tool"] button:nth-child(1)',
            ],
            "closed_point": [
                'button[title*="closed" i]',
                'button[aria-label*="closed" i]',
                'button[title*="cerrado" i]',
                'button[title*="filled" i]',
                '[class*="closed-point"]',
                'button[title*="point" i]',
            ],
            "open_point": [
                'button[title*="open" i]',
                'button[aria-label*="open" i]',
                'button[title*="abierto" i]',
                'button[title*="hollow" i]',
                '[class*="open-point"]',
            ],
            "asymptote": [
                'button[title*="asymptote" i]',
                'button[title*="dashed" i]',
                'button[aria-label*="asymptote" i]',
                '[class*="asymptote-tool"]',
                '[class*="tool"] button:nth-child(5)',
            ],
        }

        selectors = tool_selectors.get(tool_type, tool_selectors["curve"])

        for selector in selectors:
            try:
                btn = self.page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    log.info(f"  Selected {tool_type} tool via: {selector}")
                    time.sleep(0.5)
                    return True
            except Exception:
                continue

        # Fallback: try clicking the graph tool palette icons by image/position
        # ALEKS tool palette is usually a grid of small icon buttons
        try:
            tool_buttons = self.page.query_selector_all(
                '.tool-palette button, .graph-tools button, '
                '[class*="toolbar"] button, [class*="tool-bar"] button'
            )
            if tool_buttons:
                # Map tool type to approximate button index in the palette
                tool_indices = {
                    "point": 0, "line": 1, "curve": 2,
                    "ray": 3, "asymptote": 3, "segment": 4,
                }
                idx = tool_indices.get(tool_type, 2)
                if idx < len(tool_buttons):
                    tool_buttons[idx].click()
                    log.info(f"  Selected {tool_type} tool (button index {idx})")
                    time.sleep(0.5)
                    return True
        except Exception:
            pass

        log.warning(f"  Could not find {tool_type} tool in palette")
        return False

    def _click_graph_icon(self):
        """
        Click the 'graph' icon/button to finalize the graph after plotting.
        ALEKS instructions often say 'Then click on the graph icon.'
        """
        graph_icon_selectors = [
            'button[title*="graph" i]',
            'button[aria-label*="graph" i]',
            '[class*="graph-icon"]',
            '[class*="graph-btn"]',
            'button:has-text("Graph")',
        ]
        for selector in graph_icon_selectors:
            try:
                btn = self.page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    log.info(f"  Clicked graph icon via: {selector}")
                    time.sleep(1)
                    return
            except Exception:
                continue
        log.info("  No separate graph icon found (may not be needed)")

    def _input_graph_answer(self, data: dict):
        """
        Plot a graph answer on the ALEKS canvas.

        Supports two formats:

        Simple (single curve/line):
        {
            "type": "graph",
            "asymptotes": [-3.14, 0, 3.14],
            "points": [[1.57, 1], [-1.57, -1]],
            "tool": "curve"
        }

        Piecewise (multiple pieces — from video tutorial):
        {
            "type": "graph",
            "piecewise": [
                {
                    "tool": "curve",          # parabola piece
                    "points": [[0,10],[4,-6]],
                    "crop": [-4, 4],          # x-domain to keep [x_min, x_max]
                    "endpoints": [            # closed/open dots at boundaries
                        {"x": -4, "y": 6, "closed": true},
                        {"x": 4,  "y": -6, "closed": false}
                    ]
                },
                {
                    "tool": "ray",            # half-line piece
                    "points": [[4,-6],[5,-9]],
                    "endpoints": [
                        {"x": 4, "y": -6, "closed": true}
                    ]
                }
            ]
        }
        """
        canvas = self._get_graph_canvas()
        if not canvas:
            log.error("  Could not find graph canvas on page")
            self.screenshot("graph_no_canvas")
            return

        cal = self._calibrate_grid(canvas)

        # ── Piecewise path ───────────────────────────────────────────
        if "piecewise" in data:
            log.info(f"  Piecewise graph: {len(data['piecewise'])} pieces")
            for i, piece in enumerate(data["piecewise"]):
                tool = piece.get("tool", "curve")
                points = piece.get("points", [])
                crop = piece.get("crop")       # [x_min, x_max] or None
                endpoints = piece.get("endpoints", [])

                log.info(f"  Piece {i+1}: tool={tool}, {len(points)} points")

                # Select the drawing tool
                self._select_graph_tool(tool)
                time.sleep(0.3)

                # Plot the key points for this piece
                for pt in points:
                    px, py = self._coord_to_pixel(pt[0], pt[1], cal)
                    px = max(canvas["x"] + 5, min(px, canvas["x"] + canvas["width"] - 5))
                    py = max(canvas["y"] + 5, min(py, canvas["y"] + canvas["height"] - 5))
                    self.page.mouse.click(px, py)
                    log.info(f"    Plotted ({pt[0]}, {pt[1]}) → ({px:.0f}, {py:.0f})")
                    time.sleep(0.4)

                # Crop the curve to the domain if specified
                if crop and len(crop) == 2:
                    self._crop_piece(crop[0], crop[1], cal, canvas)

                # Mark open/closed endpoints
                for ep in endpoints:
                    self._mark_endpoint(ep["x"], ep["y"], ep.get("closed", True), cal, canvas)

            self._click_graph_icon()
            log.info("  Piecewise graph complete")
            return

        # ── Simple path (asymptotes + points) ───────────────────────
        asymptotes = data.get("asymptotes", [])
        if asymptotes:
            log.info(f"  Plotting {len(asymptotes)} asymptotes")
            for x_val in asymptotes:
                px_top = self._coord_to_pixel(x_val, cal["y_max"] * 0.9, cal)
                px_bot = self._coord_to_pixel(x_val, cal["y_min"] * 0.9, cal)
                self.page.mouse.click(px_top[0], px_top[1])
                time.sleep(0.3)
                self.page.mouse.click(px_bot[0], px_bot[1])
                time.sleep(0.3)
                log.info(f"    Asymptote x={x_val}")

        points = data.get("points", [])
        if points:
            tool = data.get("tool", "curve")
            self._select_graph_tool(tool)
            for pt in points:
                if len(pt) >= 2:
                    px, py = self._coord_to_pixel(pt[0], pt[1], cal)
                    px = max(canvas["x"] + 5, min(px, canvas["x"] + canvas["width"] - 5))
                    py = max(canvas["y"] + 5, min(py, canvas["y"] + canvas["height"] - 5))
                    self.page.mouse.click(px, py)
                    log.info(f"    Point ({pt[0]}, {pt[1]}) → ({px:.0f}, {py:.0f})")
                    time.sleep(0.4)

        self._click_graph_icon()
        log.info("  Graph plotting complete")

    def _crop_piece(self, x_min: float, x_max: float, cal: dict, canvas: dict):
        """
        Use the ALEKS crop tool to cut a curve between x_min and x_max,
        then erase the parts outside the domain.

        Flow (from video tutorial):
        1. Select crop tool
        2. Click cut point at x_min (on the curve)
        3. Click cut point at x_max (on the curve)
        4. Select eraser tool and remove the unwanted segments
        """
        log.info(f"  Cropping piece to domain [{x_min}, {x_max}]")

        # Select crop tool (called "tijera" / scissors in Spanish ALEKS)
        crop_selectors = [
            'button[title*="tijera" i]',
            'button[aria-label*="tijera" i]',
            'button[title*="crop" i]',
            'button[aria-label*="crop" i]',
            'button[title*="recortar" i]',
            'button[title*="scissors" i]',
            '[class*="crop-tool"]',
            '[class*="scissors"]',
            '[class*="tool"] button:nth-child(5)',
        ]
        for sel in crop_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    log.info("    Crop tool selected")
                    break
            except Exception:
                continue

        # Click the two cut points (y=0 is a safe mid-curve guess;
        # ALEKS snaps to the nearest curve automatically)
        for x_cut in [x_min, x_max]:
            px, py = self._coord_to_pixel(x_cut, 0, cal)
            px = max(canvas["x"] + 5, min(px, canvas["x"] + canvas["width"] - 5))
            py = max(canvas["y"] + 5, min(py, canvas["y"] + canvas["height"] - 5))
            self.page.mouse.click(px, py)
            log.info(f"    Cut at x={x_cut} → ({px:.0f}, {py:.0f})")
            time.sleep(0.5)

        # Select eraser and remove segments outside [x_min, x_max]
        eraser_selectors = [
            'button[title*="eras" i]',
            'button[aria-label*="eras" i]',
            'button[title*="goma" i]',
            '[class*="eraser"]',
            '[class*="erase-tool"]',
        ]
        for sel in eraser_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    log.info("    Eraser tool selected")
                    break
            except Exception:
                continue

        # Click slightly outside both ends to erase those segments
        for x_erase in [x_min - abs(x_max - x_min) * 0.3,
                         x_max + abs(x_max - x_min) * 0.3]:
            px, py = self._coord_to_pixel(x_erase, 0, cal)
            px = max(canvas["x"] + 5, min(px, canvas["x"] + canvas["width"] - 5))
            py = max(canvas["y"] + 5, min(py, canvas["y"] + canvas["height"] - 5))
            self.page.mouse.click(px, py)
            log.info(f"    Erased segment at x={x_erase:.2f}")
            time.sleep(0.4)

    def _mark_endpoint(self, x: float, y: float, closed: bool, cal: dict, canvas: dict):
        """
        Place a closed (filled) or open (hollow) endpoint dot on the graph.
        Closed = endpoint IS included (≤ or ≥).
        Open   = endpoint is NOT included (< or >).
        """
        point_type = "closed" if closed else "open"
        log.info(f"  Marking {point_type} endpoint at ({x}, {y})")

        # Select closed_point or open_point tool (bolita cerrada / bolita abierta)
        self._select_graph_tool("closed_point" if closed else "open_point")

        px, py = self._coord_to_pixel(x, y, cal)
        px = max(canvas["x"] + 5, min(px, canvas["x"] + canvas["width"] - 5))
        py = max(canvas["y"] + 5, min(py, canvas["y"] + canvas["height"] - 5))
        self.page.mouse.click(px, py)
        log.info(f"    {point_type.capitalize()} dot at ({x}, {y}) → ({px:.0f}, {py:.0f})")
        time.sleep(0.4)

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
            'button:has-text("Entregar actividad")',
            'button:has-text("Entregar")',
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

        log.warning("  No submit button found")

    def check_result(self) -> str:
        """
        Check if the submitted answer was correct or incorrect.

        ALEKS signals correct by turning the question number green.
        We detect this via:
          1. A green-colored question number element
          2. CSS classes that contain 'correct' / 'wrong' / 'incorrect'
          3. A checkmark icon appearing next to the question number
        """
        time.sleep(1.5)  # Give ALEKS time to evaluate and update the UI

        # Fast path: ALEKS shows explicit "Correct" / "Incorrect" text in a banner
        try:
            if self.page.query_selector('text="Correct"') or \
               self.page.query_selector('text="Correcto"'):
                return "correct"
            if self.page.query_selector('text="Incorrect"') or \
               self.page.query_selector('text="Incorrecto"'):
                return "incorrect"
        except Exception:
            pass

        try:
            result = self.page.evaluate("""
                () => {
                    // 1. Green question-number indicator
                    //    ALEKS wraps the current question number in a styled element.
                    //    When correct it gets a green background or green text color.
                    const allEls = Array.from(document.querySelectorAll('*'));

                    for (const el of allEls) {
                        const style = window.getComputedStyle(el);
                        const bg = style.backgroundColor || '';
                        const color = style.color || '';
                        const cls = (el.className || '').toLowerCase();
                        const id  = (el.id || '').toLowerCase();

                        // Green background or text = correct
                        if (bg.includes('0, 128') || bg.includes('34, 139') ||
                            bg.includes('0, 153') || bg.includes('76, 175') ||
                            color.includes('0, 128') || color.includes('0, 153')) {
                            return 'correct';
                        }

                        // Red background or text = incorrect
                        if (bg.includes('255, 0') || bg.includes('220, 53') ||
                            bg.includes('255, 59') || bg.includes('198, 40') ||
                            color.includes('255, 0') || color.includes('220, 53')) {
                            return 'incorrect';
                        }

                        // CSS class names
                        if (cls.includes('correct') || cls.includes('success') ||
                            id.includes('correct') || id.includes('success')) {
                            return 'correct';
                        }
                        if (cls.includes('incorrect') || cls.includes('wrong') ||
                            cls.includes('error') || id.includes('wrong')) {
                            return 'incorrect';
                        }
                    }
                    return 'unknown';
                }
            """)
            if result in ("correct", "incorrect"):
                return result
        except Exception:
            pass

        return "unknown"

    def click_next(self):
        """
        Click the Next / Siguiente button to advance to the next question.

        After a correct answer ALEKS shows a "Siguiente" (or "Next") button
        to move to the next problem. We wait for it to appear then click it.
        """
        # Use JS to find any button/link whose visible text matches continue/next labels
        clicked = self.page.evaluate("""
            () => {
                const labels = [
                    'continue', 'continuar', 'siguiente', 'next', 'next question'
                ];
                const els = Array.from(document.querySelectorAll('button, a'));
                for (const el of els) {
                    const t = (el.textContent || '').trim().toLowerCase();
                    if (labels.includes(t) && el.offsetParent !== null) {
                        el.click();
                        return t;
                    }
                }
                return null;
            }
        """)

        if clicked:
            log.info(f"  Clicked next button: '{clicked}'")
            time.sleep(2)
            return

        # Playwright fallback for each label
        for text in ["Continue", "Continuar", "Siguiente", "Next"]:
            try:
                btn = self.page.get_by_role("button", name=text, exact=False)
                if btn.is_visible():
                    btn.click()
                    log.info(f"  Clicked next via role: {text}")
                    time.sleep(2)
                    return
            except Exception:
                continue

        log.warning("  No 'Next' button found")


class AutomationError(Exception):
    """Unrecoverable automation failure."""
    pass
