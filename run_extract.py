import os

file_path = "/Users/henry/Desktop/Aleks-Solver-Automation/recordings/20260421-163949-precalc-asu-record/snapshots/0011-navigation-page-01.html"

if not os.path.exists(file_path):
    print(f"File not found: {file_path}")
    exit(1)

file_size = os.path.getsize(file_path)
print(f"File size: {file_size} bytes")

with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

keywords = ["Solve for", "Simplify", "Find the", "fraction", "equation"]
found_idx = -1
for kw in keywords:
    idx = content.find(kw)
    if idx != -1:
        if found_idx == -1 or idx < found_idx:
            found_idx = idx

if found_idx != -1:
    start = max(0, found_idx - 2000)
    end = min(len(content), found_idx + 3000)
    print(f"--- CONTENT AROUND KEYWORD (Index: {found_idx}) ---")
    print(content[start:end])
    print("--- END CONTENT ---")
else:
    print("Keywords not found.")

counts = {
    "<math": content.count("<math"),
    "MathJax": content.count("MathJax"),
    "aria-label": content.count("aria-label"),
    "mjx-container": content.count("mjx-container"),
    'role="math"': content.count('role="math"'),
    "ansed_root": content.count("ansed_root"),
    "question": content.count("question"),
    "problem-panel": content.count("problem-panel"),
    "data-mml": content.count("data-mml")
}

print("
Counts:")
for k, v in counts.items():
    print(f"{k}: {v}")
