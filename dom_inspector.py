"""
dom_inspector.py — Automated ALEKS math editor DOM inspection.
Auto-logins, navigates to activity 10 Q4, dumps editor DOM + simulates input.
"""

import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE  = str(Path(__file__).parent / "browser_profile")
OUT      = Path(__file__).parent / "dom_inspection"
OUT.mkdir(exist_ok=True)
USERNAME = "GGarcia16990"
PASSWORD = "Cls12Loe"

def save(name, data):
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"  saved {name}.json")

def dump_editor(page, label):
    data = page.evaluate(r"""
        () => {
            const anseds = Array.from(document.querySelectorAll('[id*="ansed"],[class*="ansed"]')).map(el => ({
                tag: el.tagName, id: el.id,
                cls: (typeof el.className==='string'?el.className:'').substring(0,100),
                visible: !!el.offsetParent,
                text: (el.innerText||el.textContent||'').trim().substring(0,200),
                rect: (r=>({x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}))(el.getBoundingClientRect()),
                ce: el.getAttribute('contenteditable')||'',
                tabindex: el.getAttribute('tabindex')||'',
                children: Array.from(el.children).map(c=>c.tagName+'#'+c.id+'.'+((typeof c.className==='string'?c.className:'').split(' ')[0]||'')),
            }));
            const focused = document.activeElement;
            const btns = Array.from(document.querySelectorAll('button,[role="button"]'))
                .filter(b=>b.offsetParent)
                .map(b=>({
                    tag:b.tagName, id:b.id,
                    cls:(typeof b.className==='string'?b.className:'').substring(0,80),
                    title:b.title||'',
                    aria:b.getAttribute('aria-label')||'',
                    text:(b.textContent||'').trim().substring(0,30),
                    rect:(r=>({x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}))(b.getBoundingClientRect()),
                }));
            return {
                anseds,
                buttons: btns,
                focused: focused ? {tag:focused.tagName,id:focused.id,cls:(typeof focused.className==='string'?focused.className:'').substring(0,80)} : null,
            };
        }
    """)
    save(label, data)
    print(f"\n--- {label} ---")
    print(f"  ansed elements: {len(data['anseds'])}")
    for a in data['anseds']:
        print(f"    <{a['tag']}> id={a['id']!r} cls={a['cls'][:60]!r} visible={a['visible']} text={a['text'][:60]!r}")
        for c in a['children']:
            print(f"      child: {c}")
    print(f"  focused: {data['focused']}")
    print(f"  buttons ({len(data['buttons'])}):")
    for b in data['buttons']:
        if b['rect']['y'] > 130:
            print(f"    [{b['text']!r:20}] title={b['title']!r:30} aria={b['aria']!r:20} cls={b['cls'][:40]!r}")
    return data

def run():
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PROFILE, headless=False, slow_mo=60,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            viewport={"width":1366,"height":768},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(30_000)

        # ── Login ────────────────────────────────────────────────────────
        print("[1] Login...")
        page.goto("https://latam.aleks.com/login")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        if "login" in page.url.lower():
            for sel in ['#login_name_alone','input.login_name','input[name="username"]']:
                try:
                    el = page.wait_for_selector(sel, timeout=3000)
                    if el: el.fill(USERNAME); break
                except: pass
            for sel in ['#login_pass_alone','input.login_password','input[type="password"]']:
                try:
                    el = page.wait_for_selector(sel, timeout=3000)
                    if el: el.fill(PASSWORD); break
                except: pass
            for sel in ['div.login_button','button[type="submit"]','button:has-text("Log In")']:
                try:
                    btn = page.wait_for_selector(sel, timeout=3000)
                    if btn: btn.click(); break
                except: pass
            page.wait_for_load_state("networkidle")
            time.sleep(3)
        print(f"  URL: {page.url}")
        page.screenshot(path=str(OUT/"00_after_login.png"))

        # ── Select class ─────────────────────────────────────────────────
        print("[2] Select class...")
        page.evaluate(r"""
            () => {
                const all = Array.from(document.querySelectorAll('*'));
                for (const el of all) {
                    const t = (el.innerText||'').trim();
                    if (t && /Group|Grupo/i.test(t) && t.length < 150 && el.children.length < 5) {
                        el.click(); return t;
                    }
                }
            }
        """)
        time.sleep(3)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT/"01_class_selected.png"))

        # ── Navigate to Activity 10 ──────────────────────────────────────
        print("[3] Navigate to Activity 10...")
        # Open hamburger
        for sel in ['[aria-label*="menu" i]','button:has(svg)','[class*="hamburger"]']:
            try:
                el = page.locator(sel).first
                if el.is_visible(): el.click(); time.sleep(1); break
            except: pass
        # Click Actividades
        for sel in ['a:has-text("Actividades")','text=Actividades','text=Assignments']:
            try:
                el = page.locator(sel).first
                if el.is_visible(): el.click(); time.sleep(2); break
            except: pass
        # Click search/magnifier
        for sel in ['[aria-label*="search" i]','[aria-label*="buscar" i]','[class*="search"] button']:
            try:
                el = page.locator(sel).first
                if el.is_visible(): el.click(); time.sleep(1); break
            except: pass
        # Type "10" in search
        for sel in ['input[placeholder*="search" i]','input[type="search"]','input:visible']:
            try:
                el = page.locator(sel).first
                if el.is_visible(): el.fill("10"); time.sleep(1.5); break
            except: pass
        # Click Activity 10
        time.sleep(1)
        page.evaluate(r"""
            () => {
                const all = Array.from(document.querySelectorAll('*'));
                let best = null, bestArea = Infinity;
                for (const el of all) {
                    const t = (el.textContent||'').trim();
                    if (!t.startsWith('Activity 10')) continue;
                    if (!el.offsetWidth) continue;
                    const a = el.offsetWidth * el.offsetHeight;
                    if (a < bestArea) { bestArea=a; best=el; }
                }
                if (best) best.click();
            }
        """)
        time.sleep(3)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT/"02_activity10.png"))
        print(f"  URL: {page.url}")

        # ── Navigate to Q4 ───────────────────────────────────────────────
        print("[4] Navigate to Q4...")
        # Click bubble 4
        clicked = page.evaluate(r"""
            () => {
                const all = Array.from(document.querySelectorAll('button,span,li,td,div'));
                for (const el of all) {
                    const t = (el.textContent||'').trim();
                    if (t === '4' && el.offsetParent) {
                        const r = el.getBoundingClientRect();
                        if (r.top < 200 && r.width < 100 && r.width > 5) { el.click(); return true; }
                    }
                }
                return false;
            }
        """)
        time.sleep(2)
        page.screenshot(path=str(OUT/"03_q4.png"))
        print(f"  clicked Q4 bubble: {clicked}")

        # ── Dump initial DOM ─────────────────────────────────────────────
        print("\n[5] Initial DOM dump...")
        initial = dump_editor(page, "dom_initial")
        page.screenshot(path=str(OUT/"04_dom_initial.png"))

        # ── Find and click the answer field ─────────────────────────────
        print("\n[6] Click answer field...")
        click_result = page.evaluate(r"""
            () => {
                // Try clicking the biggest visible ansed element in answer area
                const candidates = [
                    ...document.querySelectorAll('[id*="ansed_root"],[class*="ansed_root"]'),
                    ...document.querySelectorAll('[id*="ansed"],[class*="ansed"]'),
                ];
                for (const el of candidates) {
                    if (!el.offsetParent) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width > 50 && r.height > 20 && r.top > 150) {
                        const cx = r.left + r.width/2, cy = r.top + r.height/2;
                        return {sel: el.tagName+'#'+el.id, x: cx, y: cy, rect: {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}};
                    }
                }
                // Fallback: large visible input
                const inputs = Array.from(document.querySelectorAll('input,textarea,[contenteditable]'))
                    .filter(el => { const r=el.getBoundingClientRect(); return el.offsetParent && r.top>150 && r.width>50; });
                if (inputs.length) {
                    const r = inputs[0].getBoundingClientRect();
                    return {sel: inputs[0].tagName+'#'+inputs[0].id, x:r.left+r.width/2, y:r.top+r.height/2};
                }
                return null;
            }
        """)
        print(f"  click target: {click_result}")
        if click_result:
            page.mouse.click(click_result['x'], click_result['y'])
            time.sleep(0.5)

        focused_after_click = page.evaluate(r"""
            () => {
                const el = document.activeElement;
                return el ? {tag:el.tagName, id:el.id, cls:(typeof el.className==='string'?el.className:'').substring(0,100), ce:el.getAttribute('contenteditable')} : null;
            }
        """)
        print(f"  focused after click: {focused_after_click}")
        save("focused_after_click", {"click_target": click_result, "focused": focused_after_click})
        page.screenshot(path=str(OUT/"05_after_click.png"))

        # ── Clear field ──────────────────────────────────────────────────
        print("\n[7] Clear field...")
        page.keyboard.press("Control+a")
        time.sleep(0.1)
        page.keyboard.press("Delete")
        time.sleep(0.1)
        for _ in range(15):
            page.keyboard.press("Backspace")
            time.sleep(0.03)
        page.screenshot(path=str(OUT/"06_after_clear.png"))

        # ── Type "-4" ────────────────────────────────────────────────────
        print("\n[8] Type '-4'...")
        page.keyboard.type("-4", delay=80)
        time.sleep(0.4)
        page.screenshot(path=str(OUT/"07_after_minus4.png"))
        dump_editor(page, "dom_after_minus4")

        # ── Type "cos" and observe ────────────────────────────────────────
        print("\n[9] Type 'cos'...")
        page.keyboard.type("cos", delay=80)
        time.sleep(0.6)
        page.screenshot(path=str(OUT/"08_after_cos.png"))
        after_cos = dump_editor(page, "dom_after_cos")

        # ── What is focused now (inside cos template box?) ───────────────
        focused_in_cos = page.evaluate(r"""
            () => {
                const el = document.activeElement;
                return el ? {
                    tag:el.tagName, id:el.id,
                    cls:(typeof el.className==='string'?el.className:'').substring(0,100),
                    ce:el.getAttribute('contenteditable'),
                    parent_id: el.parentElement ? el.parentElement.id : null,
                    parent_cls: el.parentElement ? (typeof el.parentElement.className==='string'?el.parentElement.className:'').substring(0,60) : null,
                } : null;
            }
        """)
        print(f"  focused INSIDE cos template: {focused_in_cos}")
        save("focused_in_cos", focused_in_cos)

        # ── Type argument without parens ─────────────────────────────────
        print("\n[10] Type argument 'pi t / 4'...")
        # Try clicking π button
        pi_result = page.evaluate(r"""
            () => {
                const btns = Array.from(document.querySelectorAll('button,[role="button"]'));
                for (const b of btns) {
                    if (!b.offsetParent) continue;
                    const t = (b.textContent||'').trim();
                    const ti = (b.title||'').toLowerCase();
                    if (t==='π' || t==='pi' || ti.includes('pi')) {
                        const r = b.getBoundingClientRect();
                        return {found:true, text:t, title:b.title, cls:(typeof b.className==='string'?b.className:'').substring(0,60), rect:{x:Math.round(r.x),y:Math.round(r.y)}};
                    }
                }
                return {found:false};
            }
        """)
        print(f"  π button: {pi_result}")
        if pi_result.get('found'):
            page.evaluate(r"""
                () => {
                    const btns = Array.from(document.querySelectorAll('button,[role="button"]'));
                    for (const b of btns) {
                        if (!b.offsetParent) continue;
                        const t = (b.textContent||'').trim();
                        const ti = (b.title||'').toLowerCase();
                        if (t==='π'||t==='pi'||ti.includes('pi')) { b.click(); return; }
                    }
                }
            """)
            time.sleep(0.3)
        else:
            page.keyboard.type("pi", delay=80)
            time.sleep(0.3)

        page.keyboard.type("t", delay=80)
        time.sleep(0.2)
        page.screenshot(path=str(OUT/"09_after_pit.png"))

        # Try fraction button for /4
        frac_result = page.evaluate(r"""
            () => {
                const btns = Array.from(document.querySelectorAll('button,[role="button"]'));
                for (const b of btns) {
                    if (!b.offsetParent) continue;
                    const t = (b.textContent||'').trim();
                    const ti = (b.title||'').toLowerCase();
                    const cl = (typeof b.className==='string'?b.className:'').toLowerCase();
                    if (ti.includes('fraction')||ti.includes('fracción')||ti.includes('/')||cl.includes('fraction')||t==='/') {
                        const r = b.getBoundingClientRect();
                        return {found:true, text:t, title:b.title, cls:(typeof b.className==='string'?b.className:'').substring(0,60)};
                    }
                }
                return {found:false};
            }
        """)
        print(f"  fraction button: {frac_result}")
        if frac_result.get('found'):
            page.evaluate(r"""
                () => {
                    const btns = Array.from(document.querySelectorAll('button,[role="button"]'));
                    for (const b of btns) {
                        if (!b.offsetParent) continue;
                        const t = (b.textContent||'').trim();
                        const ti = (b.title||'').toLowerCase();
                        const cl = (typeof b.className==='string'?b.className:'').toLowerCase();
                        if (ti.includes('fraction')||ti.includes('fracción')||ti.includes('/')||cl.includes('fraction')||t==='/') { b.click(); return; }
                    }
                }
            """)
        else:
            page.keyboard.type("/", delay=80)
        time.sleep(0.3)

        page.keyboard.type("4", delay=80)
        time.sleep(0.3)
        page.keyboard.press("Tab")
        time.sleep(0.4)

        page.screenshot(path=str(OUT/"10_after_arg.png"))
        dump_editor(page, "dom_after_arg")

        # ── Final screenshot ─────────────────────────────────────────────
        print(f"\n[11] Done. All files in {OUT}/")
        print("     Screenshots: 00_after_login.png ... 10_after_arg.png")
        print("     JSON: dom_initial.json, dom_after_cos.json, focused_in_cos.json, dom_after_arg.json")

        time.sleep(5)
        ctx.close()

if __name__ == "__main__":
    run()
