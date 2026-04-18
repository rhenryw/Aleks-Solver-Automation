"""
main.py — ALEKS AutoSolver
Human-free automation: login → navigate → solve → report.

Usage:
    python main.py

You will be prompted for:
    1. Username / password (one time, never saved to disk)
    2. Which activities to solve (comma-separated numbers)

Then it runs autonomously until all activities are complete.
"""

import getpass
import logging
import sys
import time
from datetime import datetime

import config
from chatbot_solver import ChatbotSolver
from browser import AleksBrowser, AutomationError

def _build_solver(browser=None):
    """
    Instantiate the chatbot solver.
    """
    if browser is None:
        raise RuntimeError("ChatbotSolver requires a running browser instance.")
    return ChatbotSolver(browser)


# ─── Console Logger ─────────────────────────────────────────────

class ConsoleFormatter(logging.Formatter):
    COLORS = {
        "DEBUG":    "\033[90m",     # gray
        "INFO":     "\033[97m",     # white
        "WARNING":  "\033[93m",     # yellow
        "ERROR":    "\033[91m",     # red
        "CRITICAL": "\033[91;1m",   # bold red
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now().strftime("%H:%M:%S")
        return (
            f"{self.DIM}[{timestamp}]{self.RESET} "
            f"{color}{record.getMessage()}{self.RESET}"
        )


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ConsoleFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])


# ─── Semester Selection ─────────────────────────────────────────

def select_semester() -> int:
    """Display semester menu and return the chosen semester number."""
    print("\n\033[1m╔══════════════════════════════════════════════╗\033[0m")
    print("\033[1m║          SELECT SEMESTER                     ║\033[0m")
    print("\033[1m╚══════════════════════════════════════════════╝\033[0m\n")

    for num, (label, activities) in sorted(config.SEMESTERS.items()):
        count = len(activities)
        print(f"  \033[96m{num}\033[0m │ {label}  \033[90m({count} activities)\033[0m")

    print()
    raw = input("\033[1mSemester number (1/2/3/4): \033[0m").strip()

    if not raw.isdigit() or int(raw) not in config.SEMESTERS:
        print("\033[91mInvalid semester. Exiting.\033[0m")
        sys.exit(1)

    chosen = int(raw)

    # Update the global ACTIVITIES to the chosen semester
    config.SEMESTER = chosen
    config.ACTIVITIES = config.SEMESTERS[chosen][1]

    semester_label = config.SEMESTERS[chosen][0]
    print(f"\n  \033[92m✓ {semester_label}\033[0m\n")
    return chosen


# ─── Activity Selection ─────────────────────────────────────────

def select_activities() -> list[int]:
    """Display activity menu and get user selection."""
    print("\033[1m╔══════════════════════════════════════════════╗\033[0m")
    print("\033[1m║          ALEKS ACTIVITIES                    ║\033[0m")
    print("\033[1m╚══════════════════════════════════════════════╝\033[0m\n")

    for num, name in sorted(config.ACTIVITIES.items()):
        print(f"  \033[96m{num:>2}\033[0m │ {name}")

    print()
    raw = input("\033[1mSelect activities (comma-separated, e.g. 1,2,3): \033[0m").strip()

    selected = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and int(part) in config.ACTIVITIES:
            selected.append(int(part))
        elif part:
            print(f"  \033[93mSkipping unknown activity: {part}\033[0m")

    if not selected:
        print("\033[91mNo valid activities selected. Exiting.\033[0m")
        sys.exit(1)

    return selected


# ─── Main Pipeline ──────────────────────────────────────────────

def main():
    setup_logging()
    log = logging.getLogger("main")

    print("\n\033[1;96m" + "=" * 50)
    print("   ALEKS AutoSolver — Human-Free Mode")
    print("=" * 50 + "\033[0m\n")

    # ── Step 1: Ask ALL questions before touching the browser ────────

    # 1a. Credentials
    DEFAULT_USERNAME = "GGarcia16990"
    DEFAULT_PASSWORD = "Cls12Loe"

    print("\033[90m(Press Enter on both fields to use the default account)\033[0m")
    username = input("\033[1mALEKS Username: \033[0m").strip()
    password = getpass.getpass("\033[1mALEKS Password: \033[0m")

    if not username and not password:
        username = DEFAULT_USERNAME
        password = DEFAULT_PASSWORD
        print(f"\033[90mUsing default account: {DEFAULT_USERNAME}\033[0m")
    elif not username or not password:
        print("\033[91mProvide both username and password, or leave both blank for default.\033[0m")
        sys.exit(1)

    # 1b. Semester
    select_semester()

    # 1c. Activities
    activities = select_activities()

    print(f"\n\033[92m✓ All set — launching browser now...\033[0m\n")

    # ── Step 2: Now run everything automatically ──────────────────────

    browser = AleksBrowser()
    solver  = None          # built after browser.launch() (chatbot needs it)

    # Track results
    all_results = []
    start_time = time.time()

    try:
        browser.launch()

        # Build solver here so chatbot mode can open a tab in the live context
        solver = _build_solver(browser)

        log.info("=" * 40)
        log.info("PHASE 1: Authentication")
        log.info("=" * 40)
        browser.login(username, password)

        # Clear password from memory
        password = "x" * len(password)
        del password

        log.info("")
        log.info("=" * 40)
        log.info("PHASE 1.5: Class Selection")
        log.info("=" * 40)

        active_classes = browser.get_active_classes()

        if len(active_classes) == 0:
            log.error("No active classes found on the dashboard!")
            browser.screenshot("no_classes")
            sys.exit(1)

        log.info(f"Auto-selecting: {active_classes[0]['name']}")
        browser.select_class(0, class_name=active_classes[0]['name'])

        log.info(f"Selected {len(activities)} activities: {activities}")

        # Step 6: Process each activity
        for activity_id in activities:
            activity_name = config.ACTIVITIES[activity_id]
            log.info("")
            log.info("=" * 40)
            log.info(f"PHASE 2: {activity_name}")
            log.info("=" * 40)

            try:
                browser.navigate_to_activity(activity_id)
            except AutomationError as e:
                log.error(f"Could not navigate to activity {activity_id}: {e}")
                continue

            # Solve loop for this activity
            question_num = 0
            max_questions = 50  # Safety limit per activity

            while question_num < max_questions:
                question_num += 1

                # Check if there's a question
                if not browser.has_question():
                    log.info(f"No more questions in {activity_name}")
                    break

                # ── DOUBLE CONFIRMATION ───────────────────────────────────────
                # Step 1: check bubble color
                bubble = browser.get_bubble_status(question_num)

                if bubble == 'correct':
                    # GREEN — confirmed correct, move on immediately
                    log.info(f"── Q{question_num}: correct ✓ ⏭️")
                    browser.press_continue()
                    browser.click_next(question_num)
                    time.sleep(1)
                    continue

                elif bubble == 'incorrect':
                    # RED — second confirmation: check if the correct answer is revealed
                    if browser.is_correct_answer_shown():
                        # ALEKS is showing the correct answer → question is dead.
                        # The page has a "Continue" button, not a nav bubble — use press_continue.
                        log.info(f"── Q{question_num}: exhausted (correct answer shown) ⏭️")
                        browser.press_continue()
                        time.sleep(1)
                        continue
                    else:
                        # Correct answer NOT shown → still has attempts, solve it
                        page_q_num = browser.get_current_question_number()
                        if page_q_num > 0 and page_q_num != question_num:
                            log.info(f"  Syncing Q counter: {question_num} → {page_q_num}")
                            question_num = page_q_num
                        log.info(f"── Q{question_num}: incorrect — retrying")

                else:
                    # TEAL / active — unanswered, solve on first attempt
                    log.info(f"── Q{question_num}: active — solving first attempt")

                # Read question
                log.info(f"── Question {question_num} ──")
                question_text = browser.read_question()

                if not question_text:
                    log.warning("Empty question, skipping...")
                    browser.click_next(question_num)
                    continue

                semester_label = config.SEMESTERS[config.SEMESTER][0]
                topic_name = activity_name.split(" - ")[1] if " - " in activity_name else activity_name
                topic = (
                    f"ALEKS Math Course — {semester_label}\n"
                    f"Activity: {activity_name}\n"
                    f"Subject: {topic_name}\n"
                    f"IMPORTANT: This is a PURE MATH problem. "
                    f"Solve it using algebra/trigonometry only. "
                    f"Do NOT apply physics laws or derive formulas from scratch — "
                    f"treat every equation in the question as a given math formula to evaluate."
                )
                # Use absolute paths to prevent CWD issues
                from pathlib import Path as _Path
                screenshots_dir = _Path(__file__).parent / "screenshots"
                screenshots_dir.mkdir(exist_ok=True)
                screenshot_path = screenshots_dir / f"q{question_num}.png"

                # Take a screenshot for the vision AI
                browser.page.screenshot(path=str(screenshot_path))

                # Ask the AI
                answer, _ = solver.solve_from_screenshot(
                    image_path=screenshot_path,
                    dom_text=question_text,
                    context=topic,
                )

                log.info(f"  AI Answer: {answer}")

                # ── Input the answer into ALEKS ───────────────────────
                input_ok = browser.input_answer(answer)
                if not input_ok:
                    log.warning(f"  Q{question_num}: input layer returned False — skipping submit")
                    all_results.append({
                        "activity":     activity_name,
                        "question_num": question_num,
                        "question":     question_text[:200],
                        "answer":       answer,
                        "result":       "input_failed",
                        "timestamp":    datetime.now().isoformat(),
                    })
                    browser.click_next(question_num)
                    time.sleep(1)
                    continue

                # ── Screenshot before submitting ──────────────────────
                input_q_dir = _Path(__file__).parent / "input_question"
                input_q_dir.mkdir(exist_ok=True)
                browser.page.screenshot(
                    path=str(input_q_dir / f"q{question_num}_input.png")
                )

                # ── Submit ────────────────────────────────────────────
                browser.submit()
                time.sleep(1.5)

                # ── Check result ──────────────────────────────────────
                result = browser.check_result()
                log.info(f"  Q{question_num}: {result}")

                all_results.append({
                    "activity":     activity_name,
                    "question_num": question_num,
                    "question":     question_text[:200],
                    "answer":       answer,
                    "result":       result,
                    "timestamp":    datetime.now().isoformat(),
                })

                # Advance to next question
                browser.click_next(question_num)
                time.sleep(1)

    except KeyboardInterrupt:
        log.warning("\nStopped by user (Ctrl+C)")
    except AutomationError as e:
        log.error(f"Automation error: {e}")
        browser.screenshot("fatal_error")
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        browser.screenshot("crash")
    finally:
        # Close chatbot tab first (if open), then the main browser
        if solver is not None and hasattr(solver, "close"):
            solver.close()
        browser.close()

    # ─── Final Report ───────────────────────────────────────────
    elapsed = time.time() - start_time
    stats = solver.stats if solver is not None else {
        "api_calls": 0, "total_tokens": 0
    }

    print("\n")
    print("\033[1;96m" + "=" * 50)
    print("   SESSION REPORT")
    print("=" * 50 + "\033[0m\n")

    total       = len(all_results)
    correct     = sum(1 for r in all_results if r["result"] == "correct")
    incorrect   = sum(1 for r in all_results if r["result"] == "incorrect")
    failed_inp  = sum(1 for r in all_results if r["result"] == "input_failed")
    unknown     = total - correct - incorrect - failed_inp

    print(f"  \033[1mQuestions processed:\033[0m  {total}")
    print(f"  \033[92m✅ Correct:\033[0m           {correct}")
    print(f"  \033[91m❌ Incorrect:\033[0m         {incorrect}")
    print(f"  \033[93m⚠️  Input failed:\033[0m     {failed_inp}")
    print(f"  \033[90m❔ Unknown:\033[0m           {unknown}")
    print()
    print(f"  \033[1mAI calls:\033[0m          {stats['api_calls']}")
    print(f"  \033[1mModel:\033[0m             gemini (browser chatbot)")
    print(f"  \033[1mTime elapsed:\033[0m      {elapsed:.0f}s ({elapsed / 60:.1f}min)")
    print()

    # Per-activity breakdown
    activities_seen = set(r["activity"] for r in all_results)
    if len(activities_seen) > 1:
        print("  \033[1mPer Activity:\033[0m")
        for act in activities_seen:
            act_results = [r for r in all_results if r["activity"] == act]
            short_name = act.split(" - ")[1] if " - " in act else act
            print(f"    {short_name}: {len(act_results)} questions processed")
        print()

    print("\033[2mScreenshots saved in screenshots/\033[0m\n")


if __name__ == "__main__":
    main()
