"""
main.py — ALEKS AutoSolver.

Flow (matches real ALEKS behavior as captured by record_session.py):

  1. Login       : paste a Canvas/LMS SSO URL (or use saved session)
  2. Start       : click the 'Start Learning' button on the dashboard
  3. Loop        : read question → ask the AI → type answer → Check
                   → Continue / New Item depending on correctness
  4. Stop when   : no more questions, safety cap hit, or Ctrl+C

Usage:
    python3 main.py                     # interactive: asks for SSO URL
    python3 main.py --sso "https://..." # non-interactive
    python3 main.py --max 50            # cap at 50 questions
    python3 main.py --dry-run           # read-only: don't submit answers
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import config
from browser import AleksBrowser, AutomationError
from solver import Solver


# ─── Pretty console logger ──────────────────────────────────────

class ConsoleFormatter(logging.Formatter):
    COLORS = {
        "DEBUG":    "\033[90m",
        "INFO":     "\033[97m",
        "WARNING":  "\033[93m",
        "ERROR":    "\033[91m",
        "CRITICAL": "\033[91;1m",
    }
    RESET, DIM = "\033[0m", "\033[2m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        ts    = datetime.now().strftime("%H:%M:%S")
        return f"{self.DIM}[{ts}]{self.RESET} {color}{record.getMessage()}{self.RESET}"


def setup_logging():
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(ConsoleFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[h])


# ─── CLI ────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Automate ALEKS problem solving via an OpenAI-compatible LLM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--sso",     metavar="URL",
                   help="Canvas/LMS SSO link into ALEKS. If omitted, you'll be prompted.")
    p.add_argument("--max",     type=int, default=config.MAX_QUESTIONS_PER_SESSION,
                   metavar="N", help="Max questions to solve in this session.")
    p.add_argument("--dry-run", action="store_true",
                   help="Read questions and get answers but don't submit.")
    p.add_argument("--skip-wrong", action="store_true",
                   help="Immediately request a new item when an answer is wrong.")
    p.add_argument("--class", dest="class_name", metavar="TEXT",
                   help="Substring to match when multiple classes are listed on 'My Classes' "
                        "(e.g. 'MAT 170'). Defaults to the first class.")
    return p.parse_args()


# ─── Main loop ──────────────────────────────────────────────────

def main() -> int:
    setup_logging()
    log = logging.getLogger("main")
    args = parse_args()

    print("\n\033[1;96m" + "=" * 54)
    print("   ALEKS AutoSolver")
    print("=" * 54 + "\033[0m\n")

    # 1. SSO URL
    sso_url = args.sso or input("\033[1mPaste ALEKS SSO URL (from Canvas): \033[0m").strip()
    if not sso_url.startswith("http"):
        print("\033[91mThat doesn't look like a valid URL.\033[0m")
        return 1

    # 2. Init
    solver  = Solver()
    browser = AleksBrowser()
    results = []
    t0      = time.time()

    try:
        browser.launch()

        log.info("=" * 42)
        log.info("Phase 1: SSO Login")
        log.info("=" * 42)
        browser.login_sso(sso_url)

        log.info("=" * 42)
        log.info("Phase 2: Open class & Start Learning")
        log.info("=" * 42)
        browser.start_learning(class_name_substring=args.class_name)

        log.info("=" * 42)
        log.info("Phase 3: Solving")
        log.info("=" * 42)
        consecutive_empty = 0
        last_question = ""
        stuck_count   = 0
        empty_count   = 0

        for n in range(1, args.max + 1):
            if not browser.has_question():
                # ALEKS shows a "mastery checkpoint" between problem clusters:
                # Continue My Path → Start → next problem. Try to advance
                # through it before giving up. Also retry Start Learning —
                # sometimes the first click hits a loading overlay.
                if (browser.advance_past_checkpoint()
                        or browser._click_first_visible(
                            config.SELECTORS["start_learning"], "Start Learning")):
                    log.info("  Advanced past checkpoint screen.")
                    time.sleep(config.WAIT_AFTER_NEXT_SECONDS)
                    continue
                consecutive_empty += 1
                try:
                    url_now = browser.page.url
                except Exception:
                    url_now = "?"
                log.info(f"  No question visible (attempt {consecutive_empty}/5) — url={url_now[:90]}")
                if consecutive_empty >= 5:
                    browser.screenshot(f"no_question_final")
                    log.info("  No more questions — stopping.")
                    break
                time.sleep(3)
                continue
            consecutive_empty = 0

            log.info("")
            log.info(f"── Question {n} ──")
            q = browser.read_question()
            if not q:
                empty_count += 1
                log.warning(f"  Empty question text ({empty_count}/5) — probing advance.")
                if empty_count == 1:
                    browser.screenshot("empty_question")
                # Try every button that could move us forward.
                moved = (browser.recover_from_explanation()
                         or browser.click_try_again()
                         or browser.advance_past_checkpoint()
                         or browser.skip_to_new_item())
                if empty_count >= 5:
                    log.warning("  Too many empty questions — stopping.")
                    browser.screenshot("empty_question_giveup")
                    break
                time.sleep(config.WAIT_AFTER_NEXT_SECONDS if moved else 2.0)
                continue
            empty_count = 0

            preview = q[:140].replace("\n", " ")
            log.info(f"  Q: {preview}")

            # Detect stuck-on-same-question loop (e.g. Check button gone,
            # or input widget swapped out mid-submit). After 3 repeats force
            # an advance via every known button.
            if q == last_question:
                stuck_count += 1
                if stuck_count >= 3:
                    log.warning(f"  Stuck on same question {stuck_count}× — forcing advance.")
                    solver.invalidate(q)
                    if not (browser.recover_from_explanation()
                            or browser.click_try_again()
                            or browser.skip_to_new_item()
                            or browser.advance_past_checkpoint()):
                        log.warning("  No advance button worked — waiting.")
                        browser.screenshot("stuck_hard")
                        time.sleep(config.WAIT_AFTER_NEXT_SECONDS)
                    stuck_count = 0
                    last_question = ""
                    continue
            else:
                stuck_count   = 0
                last_question = q

            if args.dry_run:
                answer = solver.solve(q)
                log.info(f"  A (dry-run): {answer[:80]}")
                results.append({"n": n, "q": q[:200], "a": answer, "result": "dry-run"})
                continue

            # ── attempt loop (retry wrong answers up to MAX_WRONG_ATTEMPTS) ──
            final_result = "unknown"
            final_answer = ""
            wrong_hints: list[str] = []
            notice_hints: list[str] = []

            for attempt in range(1, config.MAX_WRONG_ATTEMPTS + 1):
                # Capture any leftover popup notice before asking the model
                # again (e.g. "Write your answer as a single fraction.").
                pending_notice = browser.dismiss_notice()
                if pending_notice:
                    notice_hints.append(pending_notice)

                hint_parts: list[str] = []
                if wrong_hints:
                    hint_parts.append(
                        "Your previous answer(s) were WRONG: "
                        + "; ".join(wrong_hints)
                        + ". Try a different approach."
                    )
                if notice_hints:
                    hint_parts.append(
                        "ALEKS instruction(s) from popup notice(s): "
                        + " | ".join(notice_hints)
                        + ". You MUST obey these constraints exactly."
                    )
                hint = "\n".join(hint_parts)

                answer = solver.solve(q, context=hint)
                final_answer = answer
                log.info(f"  A (try {attempt}): {answer[:80]}")

                if not browser.input_answer(answer):
                    log.warning("  No answer widget reachable — skipping Check.")
                    final_result = "unknown"
                    time.sleep(config.WAIT_AFTER_CHECK_SECONDS)
                    break
                if not browser.check_answer():
                    log.warning("  Could not click Check — advancing.")
                    break

                # ALEKS sometimes pops an informational dialog ("Be Careful:
                # Fill in all the empty boxes.") — check_answer dismisses it
                # and stashes the message. Treat it as a hint for the retry.
                if browser.last_notice:
                    notice_hints.append(browser.last_notice)
                    solver.invalidate(q)
                    log.info("  Re-submitting after notice.")
                    continue

                final_result = browser.check_result()
                icon  = {"correct": "✓", "incorrect": "✗", "try_again": "↻"}.get(final_result, "?")
                color = {"correct": "\033[92m", "incorrect": "\033[91m",
                         "try_again": "\033[91m"}.get(final_result, "\033[93m")
                log.info(f"  Result: {color}{icon} {final_result}\033[0m")

                if final_result == "correct":
                    break
                if final_result == "try_again":
                    # This is still the same problem; feed the wrong answer
                    # back as context and retry once more instead of moving on.
                    wrong_hints.append(answer)
                    solver.invalidate(q)
                    if args.skip_wrong:
                        log.info("  --skip-wrong set — not retrying this problem.")
                        break
                    if attempt >= config.MAX_WRONG_ATTEMPTS:
                        log.info(f"  {config.MAX_WRONG_ATTEMPTS} wrong attempts — giving up.")
                        break
                    log.info("  ALEKS says 'Try Again' — retrying same question.")
                    browser.click_try_again()
                    time.sleep(config.WAIT_AFTER_NEXT_SECONDS)
                    continue
                if final_result == "incorrect":
                    wrong_hints.append(answer)
                    solver.invalidate(q)
                    if args.skip_wrong:
                        log.info("  --skip-wrong set — not retrying this problem.")
                        break
                    if attempt >= config.MAX_WRONG_ATTEMPTS:
                        log.info(f"  {config.MAX_WRONG_ATTEMPTS} wrong attempts — giving up.")
                    continue
                # unknown — small wait, then re-probe next loop iteration
                time.sleep(config.WAIT_AFTER_CHECK_SECONDS)
                break

            results.append({
                "n": n, "q": q[:200], "a": final_answer,
                "result": final_result,
                "ts": datetime.now().isoformat(),
            })

            # Cache answers ONLY when ALEKS explicitly marks them correct.
            if final_result == "correct":
                solver.mark_correct(q, final_answer)

            # ── advance to the next problem ──
            if final_result == "correct":
                browser.continue_after_correct()
            elif final_result == "try_again":
                browser.click_try_again()
            elif final_result == "incorrect":
                # ALEKS is showing the "Let's Take a Break / CORRECT ANSWER /
                # EXPLANATION" screen. The advancement button is below the
                # fold — scroll and try every known button.
                if not browser.recover_from_explanation():
                    log.warning("  Could not advance past explanation screen — waiting.")
                    browser.screenshot("stuck_on_explanation")
                    time.sleep(config.WAIT_AFTER_NEXT_SECONDS)
            else:
                # 'unknown' — ALEKS didn't show a clear correct/incorrect
                # indicator. Could be a transient DOM state, a dismissed
                # popup, or the widget was replaced. Try every advance
                # button so we don't loop on the same problem forever.
                log.info("  Unknown result — probing advance buttons.")
                (browser.recover_from_explanation()
                 or browser.click_try_again()
                 or browser.advance_past_checkpoint()
                 or browser.skip_to_new_item())
                time.sleep(config.WAIT_AFTER_CHECK_SECONDS)

    except KeyboardInterrupt:
        log.warning("\nStopped by user (Ctrl+C)")
    except AutomationError as e:
        log.error(f"Automation error: {e}")
        browser.screenshot("automation_error")
    except Exception as e:
        log.exception(f"Unexpected error: {e}")
        browser.screenshot("crash")
    finally:
        browser.close()

    _print_report(results, solver, time.time() - t0)
    _save_results(results)
    return 0


# ─── Reporting ──────────────────────────────────────────────────

def _print_report(results: list[dict], solver: Solver, elapsed: float):
    print("\n\033[1;96m" + "=" * 54)
    print("   SESSION REPORT")
    print("=" * 54 + "\033[0m\n")

    n         = len(results)
    correct   = sum(1 for r in results if r["result"] == "correct")
    incorrect = sum(1 for r in results if r["result"] == "incorrect")
    try_again = sum(1 for r in results if r["result"] == "try_again")
    dry_run   = sum(1 for r in results if r["result"] == "dry-run")
    unknown   = n - correct - incorrect - try_again - dry_run
    stats     = solver.stats

    print(f"  \033[1mQuestions:\033[0m       {n}")
    print(f"  \033[92m✓ Correct:\033[0m       {correct}")
    print(f"  \033[91m✗ Incorrect:\033[0m     {incorrect}")
    print(f"  \033[91m↻ Try again:\033[0m     {try_again}")
    print(f"  \033[93m? Unknown:\033[0m       {unknown}")
    if n:
        print(f"  \033[1mSuccess rate:\033[0m    {correct / n * 100:.1f}%")
    print()
    print(f"  \033[1mAPI calls:\033[0m       {stats['api_calls']}")
    print(f"  \033[1mCache hits:\033[0m      {stats['cache_hits']}")
    print(f"  \033[1mTokens used:\033[0m     {stats['total_tokens']:,}")
    print(f"  \033[1mCached answers:\033[0m  {stats['cached_answers']}")
    print(f"  \033[1mElapsed:\033[0m         {elapsed:.0f}s ({elapsed / 60:.1f}min)")
    print()


def _save_results(results: list[dict]):
    if not results:
        return
    out = Path("session_results.json")
    existing = []
    if out.exists():
        try:
            existing = json.loads(out.read_text())
        except Exception:
            pass
    existing.append({
        "finished_at": datetime.now().isoformat(),
        "results": results,
    })
    out.write_text(json.dumps(existing, indent=2))
    print(f"\033[2mResults appended to {out}\033[0m\n")


if __name__ == "__main__":
    raise SystemExit(main())
