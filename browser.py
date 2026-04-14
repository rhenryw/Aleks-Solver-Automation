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
        - Graph JSON: plot points/asymptotes on the canvas
        - Text field: type the answer
        - Multiple choice: click the right option
        - Dropdown: select the value
        """
        answer = answer.strip()
        log.info(f"  Inputting answer: {answer}")

        # Check if this is a graph answer (JSON with graph data)
        graph_data = self._parse_graph_answer(answer)
        if graph_data:
            log.info("  Detected GRAPH answer — plotting on canvas")
            self._input_graph_answer(graph_data)
            return

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
        tool_selectors = {
            "curve": [
                'button[title*="curve" i]',
                'button[aria-label*="curve" i]',
                '[class*="curve-tool"]',
                '[class*="tool"] button:nth-child(3)',
            ],
            "line": [
                'button[title*="line" i]',
                'button[aria-label*="line" i]',
                '[class*="line-tool"]',
                '[class*="tool"] button:nth-child(2)',
            ],
            "point": [
                'button[title*="point" i]',
                'button[aria-label*="point" i]',
                '[class*="point-tool"]',
                '[class*="tool"] button:nth-child(1)',
            ],
            "asymptote": [
                'button[title*="asymptote" i]',
                'button[title*="dashed" i]',
                'button[aria-label*="asymptote" i]',
                '[class*="asymptote-tool"]',
                '[class*="tool"] button:nth-child(4)',
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
        
        Expected data format:
        {
            "type": "graph",
            "asymptotes": [-3.14, 0, 3.14],   # x-values for vertical asymptotes
            "points": [[1.57, 1], [-1.57, -1]], # [x, y] pairs to plot
            "tool": "curve"                     # optional tool type
        }
        """
        # Step 1: Find the graph canvas
        canvas = self._get_graph_canvas()
        if not canvas:
            log.error("  Could not find graph canvas on page")
            self.screenshot("graph_no_canvas")
            return

        # Step 2: Calibrate the grid (find coordinate → pixel mapping)
        cal = self._calibrate_grid(canvas)

        # Step 3: Plot asymptotes (vertical dashed lines)
        asymptotes = data.get("asymptotes", [])
        if asymptotes:
            log.info(f"  Plotting {len(asymptotes)} asymptotes: {asymptotes}")
            for x_val in asymptotes:
                # Click at top and bottom of the asymptote line
                px_top = self._coord_to_pixel(x_val, cal["y_max"] * 0.9, cal)
                px_bot = self._coord_to_pixel(x_val, cal["y_min"] * 0.9, cal)

                # Click first point
                self.page.mouse.click(px_top[0], px_top[1])
                time.sleep(0.3)
                # Click second point to draw the line
                self.page.mouse.click(px_bot[0], px_bot[1])
                time.sleep(0.3)

                log.info(f"    Asymptote x={x_val} → "
                         f"({px_top[0]:.0f},{px_top[1]:.0f}) to ({px_bot[0]:.0f},{px_bot[1]:.0f})")

        # Step 4: Plot points
        points = data.get("points", [])
        if points:
            log.info(f"  Plotting {len(points)} points: {points}")

            # If there's a specific tool to select, do it first
            tool = data.get("tool", "curve")
            self._select_graph_tool(tool)

            for pt in points:
                if len(pt) >= 2:
                    px, py = self._coord_to_pixel(pt[0], pt[1], cal)

                    # Clamp to canvas bounds
                    px = max(canvas["x"] + 5, min(px, canvas["x"] + canvas["width"] - 5))
                    py = max(canvas["y"] + 5, min(py, canvas["y"] + canvas["height"] - 5))

                    self.page.mouse.click(px, py)
                    log.info(f"    Point ({pt[0]}, {pt[1]}) → pixel ({px:.0f}, {py:.0f})")
                    time.sleep(0.4)

        # Step 5: Click the graph icon to finalize (if required)
        self._click_graph_icon()

        log.info("  Graph plotting complete")

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
