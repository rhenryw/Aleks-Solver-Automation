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
from solver import Solver
from browser import AleksBrowser, AutomationError


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


# ─── Activity Selection ─────────────────────────────────────────

def select_activities() -> list[int]:
    """Display activity menu and get user selection."""
    print("\n\033[1m╔══════════════════════════════════════════════╗\033[0m")
    print("\033[1m║          ALEKS ACTIVITIES                    ║\033[0m")
    print("\033[1m╚══════════════════════════════════════════════╝\033[0m\n")

    for num, name in sorted(config.ACTIVITIES.items()):
        print(f"  \033[96m{num:>2}\033[0m │ {name}")

    print()
    raw = input("\033[1mSelect activities (comma-separated, e.g. 9,10,11): \033[0m").strip()

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

    # Step 1: Credentials (never saved to disk)
    username = input("\033[1mALEKS Username: \033[0m").strip()
    password = getpass.getpass("\033[1mALEKS Password: \033[0m")

    if not username or not password:
        print("\033[91mUsername and password are required.\033[0m")
        sys.exit(1)

    # Step 2: Select activities
    activities = select_activities()
    log.info(f"Selected {len(activities)} activities: {activities}")

    # Step 3: Initialize modules
    solver = Solver()
    browser = AleksBrowser()

    # Track results
    all_results = []
    start_time = time.time()

    try:
        # Step 4: Launch browser and login
        browser.launch()
        log.info("=" * 40)
        log.info("PHASE 1: Authentication")
        log.info("=" * 40)
        browser.login(username, password)

        # Clear password from memory
        password = "x" * len(password)
        del password

        # Step 5: Process each activity
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

                # Read question
                log.info(f"── Question {question_num} ──")
                question_text = browser.read_question()

                if not question_text:
                    log.warning("Empty question, skipping...")
                    browser.click_next()
                    continue

                # Show truncated question in console
                preview = question_text[:100].replace("\n", " ")
                log.info(f"  Q: {preview}...")

                # Solve
                topic = activity_name.split(" - ")[1] if " - " in activity_name else ""
                answer = solver.solve(question_text, context=topic)
                log.info(f"  A: {answer}")

                # Input answer
                browser.input_answer(answer)

                # Submit
                browser.submit()

                # Check result
                result = browser.check_result()
                status_icon = {"correct": "✅", "incorrect": "❌"}.get(result, "❓")
                log.info(f"  Result: {status_icon} {result}")

                # Record
                all_results.append({
                    "activity": activity_name,
                    "question_num": question_num,
                    "question": question_text[:200],
                    "answer": answer,
                    "result": result,
                    "timestamp": datetime.now().isoformat(),
                })

                # Move to next question
                if result != "unknown":
                    browser.click_next()
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
        browser.close()

    # ─── Final Report ───────────────────────────────────────────
    elapsed = time.time() - start_time
    stats = solver.stats

    print("\n")
    print("\033[1;96m" + "=" * 50)
    print("   SESSION REPORT")
    print("=" * 50 + "\033[0m\n")

    total = len(all_results)
    correct = sum(1 for r in all_results if r["result"] == "correct")
    incorrect = sum(1 for r in all_results if r["result"] == "incorrect")
    unknown = total - correct - incorrect

    print(f"  \033[1mQuestions solved:\033[0m  {total}")
    print(f"  \033[92m✅ Correct:\033[0m         {correct}")
    print(f"  \033[91m❌ Incorrect:\033[0m       {incorrect}")
    print(f"  \033[93m❓ Unknown:\033[0m         {unknown}")
    if total > 0:
        print(f"  \033[1mSuccess rate:\033[0m      {correct / total * 100:.1f}%")
    print()
    print(f"  \033[1mAPI calls:\033[0m         {stats['api_calls']}")
    print(f"  \033[1mCache hits:\033[0m        {stats['cache_hits']}")
    print(f"  \033[1mTokens used:\033[0m       {stats['total_tokens']:,}")
    print(f"  \033[1mCached answers:\033[0m    {stats['cached_answers']}")
    print(f"  \033[1mTime elapsed:\033[0m      {elapsed:.0f}s ({elapsed / 60:.1f}min)")
    print()

    # Per-activity breakdown
    activities_seen = set(r["activity"] for r in all_results)
    if len(activities_seen) > 1:
        print("  \033[1mPer Activity:\033[0m")
        for act in activities_seen:
            act_results = [r for r in all_results if r["activity"] == act]
            act_correct = sum(1 for r in act_results if r["result"] == "correct")
            short_name = act.split(" - ")[1] if " - " in act else act
            print(f"    {short_name}: {act_correct}/{len(act_results)} correct")
        print()

    print("\033[2mResults cached in answer_cache.json for future runs\033[0m")
    print("\033[2mScreenshots saved in screenshots/ on errors\033[0m\n")


if __name__ == "__main__":
    main()
