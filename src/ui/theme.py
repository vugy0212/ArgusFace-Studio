# UI Theme, Styles, Head Scripts and Card Generators
import os
import html
import base64
import datetime
import cv2
import numpy as np
import gradio as gr
import hardware
import db

def get_profile_badge(count: int):
    if count <= 1:
        return "🔴 Osnovno (1 slika)"
    elif count == 2:
        return "🟡 Dobro (2 slike)"
    else:
        return f"🟢 Izvrsno ({count} slika)"

def format_role_badge(role_str: str) -> str:
    r = (role_str or "standard").lower()
    if r == "vip":
        return "⭐ VIP"
    elif r == "blacklist":
        return "🚨 Crna lista"
    return "Standard"


def generate_detection_cards_html(results, show_all_faces=False):
    import base64
    import datetime
    now_str = datetime.datetime.now().strftime("%H:%M:%S")

    if not results:
        return f"""
        <div class="detection-panel-inner">
            <div class="panel-header">
                <div class="panel-title">
                    <span class="status-indicator-dot"></span> Log Detekcija
                </div>
                <span class="panel-badge">Čekanje</span>
            </div>
            <div class="detection-empty-state">
                <div class="empty-icon-box">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#6E7681" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12 6 12 12 16 14"></polyline>
                    </svg>
                </div>
                <div class="empty-title">Nema novih detekcija</div>
                <div class="empty-sub">Učitajte sliku ili pokrenite live kameru za analizu.</div>
            </div>
        </div>
        """

    num_total = len(results)
    num_recognized = sum(1 for r in results if r.get("status") == "Prepoznat")

    if not show_all_faces:
        display_results = [r for r in results if r.get("status") == "Prepoznat"]
    else:
        display_results = results

    if not display_results:
        badge_text = f"0 / {num_total} lica"
        return f"""
        <div class="detection-panel-inner">
            <div class="panel-header">
                <div class="panel-title">
                    <span class="status-indicator-dot active"></span> Log Detekcija
                </div>
                <span class="panel-badge">{badge_text}</span>
            </div>
            <div class="detection-empty-state">
                <div class="empty-title" style="color: #F59E0B;">Nema prepoznatih lica</div>
                <div class="empty-sub">
                    Pronađeno je <b>{num_total}</b> lica, ali nijedno ne prelazi prag.<br>
                    Uključite <i>"Prikaži i nepoznata lica"</i> za detalje.
                </div>
            </div>
        </div>
        """

    cards = []
    for r in display_results:
        crop_bgr = r.get("crop_bgr")
        img_src = ""
        if crop_bgr is not None and isinstance(crop_bgr, np.ndarray) and crop_bgr.size > 0:
            try:
                success, buffer = cv2.imencode('.jpg', crop_bgr)
                if success:
                    img_b64 = base64.b64encode(buffer).decode('utf-8')
                    img_src = f"data:image/jpeg;base64,{img_b64}"
            except Exception:
                img_src = ""

        sim_val = r.get("similarity", 0)
        pct = 0.0
        if isinstance(sim_val, (int, float)):
            pct = float(sim_val) * 100
        else:
            try:
                pct = float(str(sim_val).replace('%', '').strip())
            except Exception:
                pct = 0.0

        status = r.get("status", "Nepoznat")
        name = r.get("best_name", "Nepoznata osoba")

        # Determine person role badge and notes
        p_role = "standard"
        p_notes = ""
        if status in ("Prepoznat", "Moguće poklapanje") and name not in ("Nepoznata osoba", "Nepoznato"):
            try:
                p_info = db.get_person_info(name)
                p_role = p_info.get("role", "standard")
                p_notes = p_info.get("notes", "")
            except Exception:
                p_role = "standard"
                p_notes = ""

        stroke_color = "#10B981"
        if p_role == "blacklist":
            badge_cls = "match-blacklist"
            role_badge = '<span class="role-pill role-blacklist">CRNA LISTA</span>'
            stroke_color = "#EF4444"
        elif p_role == "vip":
            badge_cls = "match-vip"
            role_badge = '<span class="role-pill role-vip">VIP</span>'
            stroke_color = "#0284C7"
        elif status == "Prepoznat":
            badge_cls = "match-success"
            role_badge = '<span class="role-pill role-verified">OK</span>'
            stroke_color = "#10B981"
        elif status == "Moguće poklapanje":
            badge_cls = "match-warning"
            role_badge = '<span class="role-pill role-possible">PROVJERA</span>'
            stroke_color = "#F59E0B"
        else:
            badge_cls = "match-unknown"
            role_badge = ''
            stroke_color = "#6E7681"

        safe_name = html.escape(str(name))
        safe_age = html.escape(str(r.get("age", "-")))
        safe_gender = html.escape(str(r.get("gender", "-")))
        meta_parts = [f'<span class="meta-time">{html.escape(now_str)}</span>']
        if safe_age and safe_age != "-":
            meta_parts.append(f'<span>~{safe_age}g</span>')
        if safe_gender and safe_gender != "-":
            meta_parts.append(f'<span>{safe_gender}</span>')
        meta_html = ' <span class="meta-sep">•</span> '.join(meta_parts)

        notes_html = ""
        if p_notes:
            safe_notes = html.escape(p_notes)
            notes_html = f'''
                <div class="card-notes" title="{safe_notes}">
                    <svg class="card-notes-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
                    <span class="card-notes-text">{safe_notes}</span>
                </div>
            '''

        circ_svg = f"""
        <div class="circle-gauge" title="Pouzdanost: {pct:.1f}%">
            <svg viewBox="0 0 36 36" class="circular-chart">
                <path class="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
                <path class="circle-val" stroke="{stroke_color}" stroke-dasharray="{min(100.0, max(0.0, pct)):.0f}, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
                <text x="18" y="20.5" class="percentage">{pct:.0f}%</text>
            </svg>
        </div>
        """

        cards.append(f"""
        <div class="cyber-detection-card {badge_cls}">
            <div class="card-avatar-wrap">
                <img src="{img_src}" class="card-avatar" alt="{safe_name}" />
            </div>
            <div class="card-details">
                <div class="card-name-row">
                    <span class="card-name" title="{safe_name}">{safe_name}</span>
                    {role_badge}
                </div>
                <div class="card-meta">
                    {meta_html}
                </div>
                {notes_html}
            </div>
            {circ_svg}
        </div>
        """)

    cards_html = "".join(cards)
    if not show_all_faces:
        badge_text = f"{num_recognized} prepoznato" if num_recognized == num_total else f"{num_recognized} / {num_total} lica"
    else:
        badge_text = f"{num_total} lica"

    return f"""
    <div class="detection-panel-inner">
        <div class="panel-header">
            <div class="panel-title">
                <span class="status-indicator-dot active"></span> Log Detekcija
            </div>
            <span class="panel-badge active">{badge_text}</span>
        </div>
        <div class="cyber-cards-scroll">
            {cards_html}
        </div>
    </div>
    """

# ---------------- PREPOZNAVANJE ----------------

def render_person_avatar_html(person_id):
    empty_html = """
    <div class="cyber-person-avatar-thumb">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
        </svg>
    </div>
    """
    if not person_id:
        return empty_html
        
    samples = db.get_person_samples(person_id)
    if samples and os.path.exists(samples[0]["crop_path"]):
        p = samples[0]["crop_path"]
        try:
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            return f"""
            <div class="cyber-person-avatar-thumb">
                <img src="data:image/jpeg;base64,{b64}" alt="Avatar" />
            </div>
            """
        except Exception:
            pass
    return empty_html


CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* ============================================================
   1. THEME DESIGN TOKENS (DARK MODE DEFAULT & LIGHT MODE)
   ============================================================ */

/* DARK THEME (DEFAULT) */
:root, :root.dark, html.dark, body.dark, [data-theme="dark"] {
    --ind-bg: #0D1117;
    --ind-card: #161B22;
    --ind-card-hover: #1C2128;
    --ind-border: #262C36;
    --ind-border-subtle: #21262D;
    --ind-pill: #21262D;
    --ind-pill-border: #30363D;
    --ind-input: #0D1117;
    --ind-blue: #2563EB;
    --ind-blue-hover: #1D4ED8;
    --ind-emerald: #10B981;
    --ind-amber: #F59E0B;
    --ind-red: #EF4444;
    --text-primary: #F0F6FC;
    --text-secondary: #C9D1D9;
    --text-muted: #8B949E;
    --color-scheme: dark;

    /* Gradio Internals */
    --background-fill-primary: #0D1117 !important;
    --background-fill-secondary: #161B22 !important;
    --block-background-fill: #161B22 !important;
    --block-border-color: #262C36 !important;
    --block-radius: 6px !important;
    --container-radius: 6px !important;
    --block-label-background-fill: #161B22 !important;
    --block-label-text-color: #8B949E !important;
    --block-title-text-color: #F0F6FC !important;
    --body-text-color: #C9D1D9 !important;
    --body-text-color-subdued: #8B949E !important;
    --input-background-fill: #0D1117 !important;
    --input-border-color: #262C36 !important;
    --input-radius: 6px !important;
    --input-placeholder-color: #6E7681 !important;
    --checkbox-background-color: #21262D !important;
    --checkbox-background-color-selected: #2563EB !important;
    --checkbox-border-color: #30363D !important;
    --checkbox-border-color-selected: #3B82F6 !important;
    --checkbox-label-background-fill: transparent !important;
    --checkbox-label-text-color: #C9D1D9 !important;
    --table-even-background-fill: #161B22 !important;
    --table-odd-background-fill: #161B22 !important;
    --table-text-color: #C9D1D9 !important;
    --table-border-color: #21262D !important;
    --border-color-primary: #262C36 !important;
    color-scheme: dark !important;
}

/* LIGHT THEME */
:root.light, html.light, body.light, [data-theme="light"] {
    --ind-bg: #F8FAFC;
    --ind-card: #FFFFFF;
    --ind-card-hover: #F1F5F9;
    --ind-border: #CBD5E1;
    --ind-border-subtle: #E2E8F0;
    --ind-pill: #F1F5F9;
    --ind-pill-border: #CBD5E1;
    --ind-input: #FFFFFF;
    --ind-blue: #2563EB;
    --ind-blue-hover: #1D4ED8;
    --ind-emerald: #10B981;
    --ind-amber: #F59E0B;
    --ind-red: #EF4444;
    --text-primary: #0F172A;
    --text-secondary: #334155;
    --text-muted: #64748B;
    --color-scheme: light;

    /* Gradio Internals for Light Mode */
    --background-fill-primary: #F8FAFC !important;
    --background-fill-secondary: #FFFFFF !important;
    --block-background-fill: #FFFFFF !important;
    --block-border-color: #CBD5E1 !important;
    --block-radius: 6px !important;
    --container-radius: 6px !important;
    --block-label-background-fill: #FFFFFF !important;
    --block-label-text-color: #64748B !important;
    --block-title-text-color: #0F172A !important;
    --body-text-color: #334155 !important;
    --body-text-color-subdued: #64748B !important;
    --input-background-fill: #FFFFFF !important;
    --input-border-color: #CBD5E1 !important;
    --input-radius: 6px !important;
    --input-placeholder-color: #94A3B8 !important;
    --checkbox-background-color: #E2E8F0 !important;
    --checkbox-background-color-selected: #2563EB !important;
    --checkbox-border-color: #CBD5E1 !important;
    --checkbox-border-color-selected: #2563EB !important;
    --checkbox-label-background-fill: transparent !important;
    --checkbox-label-text-color: #334155 !important;
    --table-even-background-fill: #FFFFFF !important;
    --table-odd-background-fill: #F8FAFC !important;
    --table-text-color: #334155 !important;
    --table-border-color: #E2E8F0 !important;
    --border-color-primary: #CBD5E1 !important;
    color-scheme: light !important;
}

/* Base Body & Document */
body, html {
    background-color: var(--ind-bg) !important;
    background: var(--ind-bg) !important;
    color: var(--text-secondary) !important;
    font-family: 'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif !important;
    margin: 0;
    padding: 0;
    transition: background-color 0.18s ease, color 0.18s ease !important;
}

/* Custom Minimalist Scrollbar */
::-webkit-scrollbar {
    width: 6px !important;
    height: 6px !important;
}
::-webkit-scrollbar-track {
    background: var(--ind-bg) !important;
}
::-webkit-scrollbar-thumb {
    background: var(--ind-border) !important;
    border-radius: 3px !important;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--ind-pill-border) !important;
}

.gradio-container {
    background-color: var(--ind-bg) !important;
    background: var(--ind-bg) !important;
    color: var(--text-secondary) !important;
    max-width: 100% !important;
    padding: 12px !important;
    font-family: 'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* ============================================================
   2. HEADER BAR & THEME TOGGLE
   ============================================================ */
.industrial-header-bar,
.cyber-header-bar {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    background: var(--ind-card) !important;
    background-color: var(--ind-card) !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    padding: 8px 16px !important;
    margin-bottom: 12px !important;
    flex-wrap: wrap !important;
    gap: 10px !important;
    box-shadow: none !important;
    transition: background 0.18s ease, border-color 0.18s ease !important;
}

.header-left {
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
}

.header-brand {
    font-size: 1.15rem !important;
    font-weight: 700 !important;
    color: var(--text-primary) !important;
    letter-spacing: -0.01em !important;
}

.header-tagline {
    font-size: 0.78rem !important;
    color: var(--text-muted) !important;
    padding-left: 8px !important;
    border-left: 1px solid var(--ind-border) !important;
}

.header-middle {
    display: flex !important;
    align-items: center !important;
    gap: 8px !important;
    flex-wrap: wrap !important;
}

.header-right {
    display: flex !important;
    align-items: center !important;
    gap: 8px !important;
    margin-left: auto !important;
}

.status-pill {
    display: inline-flex !important;
    align-items: center !important;
    gap: 6px !important;
    background: var(--ind-pill) !important;
    border: 1px solid var(--ind-pill-border) !important;
    border-radius: 6px !important;
    padding: 3px 10px !important;
    font-size: 0.78rem !important;
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
}

.status-dot {
    width: 6px !important;
    height: 6px !important;
    border-radius: 50% !important;
    flex-shrink: 0 !important;
}

.status-dot.green { background-color: #10B981 !important; }
.status-dot.blue { background-color: #2563EB !important; }
.status-dot.slate { background-color: var(--text-muted) !important; }

/* Theme Toggle Button */
.theme-toggle-btn {
    display: inline-flex !important;
    align-items: center !important;
    gap: 6px !important;
    background: var(--ind-pill) !important;
    border: 1px solid var(--ind-pill-border) !important;
    border-radius: 6px !important;
    padding: 4px 11px !important;
    font-size: 0.78rem !important;
    color: var(--text-secondary) !important;
    font-weight: 600 !important;
    cursor: pointer !important;
    transition: all 0.15s ease !important;
    outline: none !important;
    user-select: none !important;
}

.theme-toggle-btn:hover {
    background: var(--ind-card-hover) !important;
    border-color: var(--ind-blue) !important;
    color: var(--text-primary) !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08) !important;
}

/* Visibility of Theme Toggle Text / Icons */
html.light .theme-icon-dark-indicator,
body.light .theme-icon-dark-indicator {
    display: inline-flex !important;
    align-items: center !important;
}
html.light .theme-icon-light-indicator,
body.light .theme-icon-light-indicator {
    display: none !important;
}

html.dark .theme-icon-dark-indicator,
body.dark .theme-icon-dark-indicator,
:root:not(.light) .theme-icon-dark-indicator {
    display: none !important;
}
html.dark .theme-icon-light-indicator,
body.dark .theme-icon-light-indicator,
:root:not(.light) .theme-icon-light-indicator {
    display: inline-flex !important;
    align-items: center !important;
}

/* ============================================================
   3. NAVIGATION TABS
   ============================================================ */
.tabs > .tab-nav,
div[role="tablist"] {
    background: var(--ind-card) !important;
    border-radius: 6px !important;
    padding: 4px !important;
    border: 1px solid var(--ind-border) !important;
    gap: 4px !important;
    margin-bottom: 12px !important;
    display: flex !important;
    box-shadow: none !important;
}

.tabs > .tab-nav > button,
div[role="tablist"] button,
button[role="tab"] {
    color: var(--text-muted) !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    border-radius: 6px !important;
    padding: 6px 14px !important;
    border: 1px solid transparent !important;
    background: transparent !important;
    transition: all 0.15s ease !important;
    box-shadow: none !important;
}

.tabs > .tab-nav > button:hover,
div[role="tablist"] button:hover,
button[role="tab"]:hover {
    color: var(--text-primary) !important;
    background: var(--ind-pill) !important;
    border-color: var(--ind-pill-border) !important;
    transform: none !important;
}

.tabs > .tab-nav > button.selected,
div[role="tablist"] button.selected,
div[role="tablist"] button[aria-selected="true"],
button[role="tab"][aria-selected="true"] {
    color: var(--text-primary) !important;
    background: var(--ind-pill) !important;
    border: 1px solid var(--ind-pill-border) !important;
    font-weight: 600 !important;
    box-shadow: none !important;
}

.tabs > .tab-nav > button.selected::after,
div[role="tablist"] button[aria-selected="true"]::after {
    display: none !important;
}

/* ============================================================
   4. CONTAINERS, BLOCKS, PANELS & ACCORDIONS
   ============================================================ */
.cyber-card,
.block,
fieldset.block,
div.block,
.gr-box,
.panel {
    background: var(--ind-card) !important;
    background-color: var(--ind-card) !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    padding: 12px !important;
    box-shadow: none !important;
    transition: background 0.18s ease, border-color 0.18s ease !important;
}

.cyber-card:hover,
.block:hover {
    border-color: var(--ind-border) !important;
    box-shadow: none !important;
    transform: none !important;
}

/* Accordion */
.cyber-accordion,
details {
    background: var(--ind-card) !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    box-shadow: none !important;
}

summary {
    color: var(--text-secondary) !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
}

/* ============================================================
   5. VIDEO VIEWPORT (ZONE B) — PERMANENT MATTE BLACK
   ============================================================ */
.cyber-preview-frame,
div[data-testid="image"],
div[data-testid="image"] > div,
.image-container,
.upload-container,
.empty,
.drop-zone {
    background-color: #000000 !important;
    background: #000000 !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    box-shadow: none !important;
    color: #C9D1D9 !important;
}

div[data-testid="image"] button,
.upload-container button {
    background: var(--ind-pill) !important;
    border: 1px solid var(--ind-pill-border) !important;
    color: var(--text-secondary) !important;
    border-radius: 6px !important;
}

/* ============================================================
   6. SWITCH-STYLE CHECKBOXES (ZONE A)
   ============================================================ */
.gradio-checkbox,
label:has(input[type="checkbox"]) {
    display: flex !important;
    align-items: center !important;
    background: transparent !important;
    background-color: transparent !important;
    border: none !important;
    padding: 4px 0 !important;
    cursor: pointer !important;
    color: var(--text-secondary) !important;
    box-shadow: none !important;
}

input[type="checkbox"] {
    -webkit-appearance: none !important;
    -moz-appearance: none !important;
    appearance: none !important;
    width: 32px !important;
    height: 18px !important;
    min-width: 32px !important;
    min-height: 18px !important;
    max-width: 32px !important;
    max-height: 18px !important;
    background: var(--ind-pill) !important;
    background-color: var(--ind-pill) !important;
    border: 1px solid var(--ind-pill-border) !important;
    border-radius: 10px !important;
    position: relative !important;
    cursor: pointer !important;
    outline: none !important;
    transition: all 0.18s ease !important;
    margin: 0 10px 0 0 !important;
    flex-shrink: 0 !important;
    box-shadow: none !important;
}

input[type="checkbox"]::before {
    content: "" !important;
    position: absolute !important;
    top: 2px !important;
    left: 2px !important;
    width: 12px !important;
    height: 12px !important;
    background: var(--text-muted) !important;
    border-radius: 50% !important;
    transition: all 0.18s ease !important;
}

input[type="checkbox"]:checked {
    background: #2563EB !important;
    background-color: #2563EB !important;
    border-color: #3B82F6 !important;
    background-image: none !important;
}

input[type="checkbox"]:checked::before {
    transform: translateX(14px) !important;
    background: #FFFFFF !important;
}

/* ============================================================
   7. INPUTS, DROPDOWNS & CONTROLS
   ============================================================ */
input[type="text"],
input[type="number"],
textarea,
select,
.dropdown,
.select,
div[data-testid="dropdown"] {
    background: var(--ind-input) !important;
    background-color: var(--ind-input) !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    color: var(--text-primary) !important;
    font-size: 0.85rem !important;
    box-shadow: none !important;
}

input::placeholder,
textarea::placeholder {
    color: var(--text-muted) !important;
}

input:focus, textarea:focus, select:focus {
    border-color: #2563EB !important;
    outline: none !important;
}

ul.options, .options-wrap {
    background: var(--ind-card) !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    color: var(--text-primary) !important;
}

ul.options li:hover, ul.options li.selected {
    background: var(--ind-pill) !important;
    color: var(--text-primary) !important;
}

/* ============================================================
   8. BUTTONS: PRIMARY, SECONDARY, DANGER
   ============================================================ */
.btn-industrial-primary,
.btn-cyber-primary,
button.primary {
    background: #2563EB !important;
    background-color: #2563EB !important;
    color: #FFFFFF !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    border: 1px solid #3B82F6 !important;
    border-radius: 6px !important;
    padding: 8px 16px !important;
    box-shadow: none !important;
    transition: background-color 0.15s ease !important;
    cursor: pointer !important;
}

.btn-industrial-primary:hover,
.btn-cyber-primary:hover,
button.primary:hover {
    background: #1D4ED8 !important;
    background-color: #1D4ED8 !important;
    border-color: #2563EB !important;
    transform: none !important;
    box-shadow: none !important;
}

.btn-industrial-secondary,
.btn-cyber-secondary,
.btn-cyber-live,
button.secondary {
    background: var(--ind-pill) !important;
    background-color: var(--ind-pill) !important;
    color: var(--text-secondary) !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    padding: 8px 16px !important;
    box-shadow: none !important;
    transition: background-color 0.15s ease !important;
    cursor: pointer !important;
}

.btn-industrial-secondary:hover,
.btn-cyber-secondary:hover,
.btn-cyber-live:hover,
button.secondary:hover {
    background: var(--ind-card-hover) !important;
    background-color: var(--ind-card-hover) !important;
    color: var(--text-primary) !important;
    border-color: var(--ind-pill-border) !important;
    transform: none !important;
}

.btn-cyber-danger,
button.stop {
    background: var(--ind-pill) !important;
    background-color: var(--ind-pill) !important;
    color: #EF4444 !important;
    border: 1px solid rgba(239, 68, 68, 0.35) !important;
    border-radius: 6px !important;
    box-shadow: none !important;
}

.btn-cyber-danger:hover,
button.stop:hover {
    background: #DC2626 !important;
    background-color: #DC2626 !important;
    color: #FFFFFF !important;
    border-color: #DC2626 !important;
}

/* ============================================================
   9. TABLES & DATAFRAMES
   ============================================================ */
table,
.dataframe,
.table-wrap,
div[data-testid="table"],
div[data-testid="dataframe"] {
    background: var(--ind-card) !important;
    background-color: var(--ind-card) !important;
    color: var(--text-secondary) !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    border-collapse: collapse !important;
    overflow: hidden !important;
}

thead, th, .dataframe thead tr th {
    background: var(--ind-card) !important;
    background-color: var(--ind-card) !important;
    color: var(--text-muted) !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
    padding: 10px 14px !important;
    border: none !important;
    border-bottom: 1px solid var(--ind-border-subtle) !important;
    border-left: none !important;
    border-right: none !important;
}

tbody tr, .dataframe tbody tr {
    background: var(--ind-card) !important;
    background-color: var(--ind-card) !important;
    color: var(--text-secondary) !important;
    border: none !important;
    border-bottom: 1px solid var(--ind-border-subtle) !important;
    border-left: none !important;
    border-right: none !important;
    transition: background-color 0.15s ease !important;
}

tbody tr:nth-child(even), .dataframe tbody tr:nth-child(even) {
    background: var(--ind-card) !important;
    background-color: var(--ind-card) !important;
}

tbody tr:hover, .dataframe tbody tr:hover {
    background: var(--ind-card-hover) !important;
    background-color: var(--ind-card-hover) !important;
}

td, .dataframe tbody tr td {
    color: var(--text-secondary) !important;
    padding: 10px 14px !important;
    border: none !important;
    border-bottom: 1px solid var(--ind-border-subtle) !important;
    border-left: none !important;
    border-right: none !important;
    font-size: 0.85rem !important;
}

/* ============================================================
   10. ZONE C: DETECTION LOG CARDS & CONFIDENCE GAUGE
   ============================================================ */
.detection-panel-inner {
    display: flex !important;
    flex-direction: column !important;
    gap: 8px !important;
}

.panel-header {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    padding-bottom: 8px !important;
    border-bottom: 1px solid var(--ind-border) !important;
}

.panel-title {
    display: flex !important;
    align-items: center !important;
    gap: 8px !important;
    font-size: 0.88rem !important;
    font-weight: 600 !important;
    color: var(--text-primary) !important;
}

.status-indicator-dot {
    width: 7px !important;
    height: 7px !important;
    border-radius: 50% !important;
    background: var(--text-muted) !important;
}

.status-indicator-dot.active {
    background: #10B981 !important;
}

.panel-badge {
    font-size: 0.72rem !important;
    background: var(--ind-pill) !important;
    border: 1px solid var(--ind-pill-border) !important;
    border-radius: 6px !important;
    padding: 2px 8px !important;
    color: var(--text-muted) !important;
}

.panel-badge.active {
    color: var(--text-secondary) !important;
}

.cyber-cards-scroll {
    display: flex !important;
    flex-direction: column !important;
    gap: 6px !important;
    max-height: 480px !important;
    overflow-y: auto !important;
}

.cyber-detection-card {
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    background: var(--ind-card) !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    padding: 8px 10px !important;
    transition: background-color 0.15s ease !important;
    box-shadow: none !important;
}

.cyber-detection-card:hover {
    background: var(--ind-card-hover) !important;
    transform: none !important;
}

.cyber-detection-card.match-success {
    border-left: 3px solid #10B981 !important;
}

.cyber-detection-card.match-warning {
    border-left: 3px solid #F59E0B !important;
}

.cyber-detection-card.match-unknown {
    border-left: 3px solid var(--text-muted) !important;
}

.cyber-detection-card.match-blacklist {
    border-left: 3px solid #EF4444 !important;
}

.cyber-detection-card.match-vip {
    border-left: 3px solid #0284C7 !important;
}

.card-avatar-wrap {
    width: 38px !important;
    height: 38px !important;
    flex-shrink: 0 !important;
}

.card-avatar {
    width: 38px !important;
    height: 38px !important;
    border-radius: 6px !important;
    object-fit: cover !important;
    background: var(--ind-pill) !important;
    border: 1px solid var(--ind-border) !important;
}

.card-details {
    flex: 1 !important;
    min-width: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 2px !important;
}

.card-name-row {
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
}

.card-name {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    color: var(--text-primary) !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}

.card-meta {
    display: flex !important;
    align-items: center !important;
    gap: 4px !important;
    font-size: 0.72rem !important;
    color: var(--text-muted) !important;
}

.card-notes {
    display: flex !important;
    align-items: center !important;
    gap: 5px !important;
    font-size: 0.72rem !important;
    color: var(--text-secondary) !important;
    margin-top: 1px !important;
    min-width: 0 !important;
    max-width: 100% !important;
}

.card-notes-icon {
    flex-shrink: 0 !important;
    color: #0284C7 !important;
    opacity: 0.85 !important;
}

.card-notes-text {
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    min-width: 0 !important;
}

.meta-time {
    color: var(--text-muted) !important;
    font-family: 'JetBrains Mono', monospace !important;
}

.meta-sep {
    color: var(--ind-border) !important;
}

/* Role Pills for Dark Mode */
.role-pill {
    font-size: 0.62rem !important;
    font-weight: 700 !important;
    padding: 1px 5px !important;
    border-radius: 4px !important;
    letter-spacing: 0.02em !important;
}

.role-verified { background: #0E4429 !important; color: #3FB950 !important; }
.role-possible { background: #4D2D00 !important; color: #E3B341 !important; }
.role-vip { background: #1F3B66 !important; color: #58A6FF !important; }
.role-blacklist { background: #490202 !important; color: #F85149 !important; }

/* Role Pills for Light Mode */
html.light .role-verified, body.light .role-verified { background: #DCFCE7 !important; color: #15803D !important; border: 1px solid #86EFAC !important; }
html.light .role-possible, body.light .role-possible { background: #FEF3C7 !important; color: #B45309 !important; border: 1px solid #FCD34D !important; }
html.light .role-vip, body.light .role-vip { background: #E0F2FE !important; color: #0369A1 !important; border: 1px solid #7DD3FC !important; }
html.light .role-blacklist, body.light .role-blacklist { background: #FEE2E2 !important; color: #B91C1C !important; border: 1px solid #FCA5A5 !important; }

/* Circular Percentage Gauge */
.circle-gauge {
    width: 34px !important;
    height: 34px !important;
    flex-shrink: 0 !important;
}

.circular-chart {
    display: block !important;
    margin: 0 auto !important;
    max-width: 100% !important;
    max-height: 100% !important;
}

.circle-bg {
    fill: none !important;
    stroke: var(--ind-pill-border) !important;
    stroke-width: 3.5 !important;
}

.circle-val {
    fill: none !important;
    stroke-width: 3.5 !important;
    stroke-linecap: round !important;
    transition: stroke-dasharray 0.3s ease !important;
}

.percentage {
    fill: var(--text-secondary) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.65rem !important;
    font-weight: 600 !important;
    text-anchor: middle !important;
}

.detection-empty-state {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 28px 12px !important;
    text-align: center !important;
}

.empty-icon-box {
    margin-bottom: 10px !important;
}

.empty-title {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    color: var(--text-secondary) !important;
    margin-bottom: 4px !important;
}

.empty-sub {
    font-size: 0.75rem !important;
    color: var(--text-muted) !important;
    line-height: 1.4 !important;
}

/* Shortcuts Card */
.industrial-shortcuts-card {
    background: var(--ind-card) !important;
    border: 1px solid var(--ind-border) !important;
    border-radius: 6px !important;
    padding: 10px 12px !important;
    margin-top: 8px !important;
    box-shadow: none !important;
}

.shortcuts-header {
    display: flex !important;
    align-items: center !important;
    gap: 8px !important;
    margin-bottom: 8px !important;
}

.shortcuts-badge {
    font-size: 0.65rem !important;
    font-weight: 700 !important;
    background: var(--ind-pill) !important;
    border: 1px solid var(--ind-pill-border) !important;
    color: var(--text-muted) !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
}

.shortcuts-title {
    font-size: 0.78rem !important;
    color: var(--text-muted) !important;
}

.shortcuts-grid {
    display: grid !important;
    grid-template-columns: repeat(2, 1fr) !important;
    gap: 6px 12px !important;
    font-size: 0.75rem !important;
    color: var(--text-secondary) !important;
}

.sc-item {
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
}

.sc-item kbd {
    background: var(--ind-pill) !important;
    border: 1px solid var(--ind-pill-border) !important;
    border-radius: 4px !important;
    padding: 1px 5px !important;
    font-size: 0.7rem !important;
    font-family: 'JetBrains Mono', monospace !important;
    color: var(--text-primary) !important;
}

/* Compact File Component for Backup & Restore */
.compact-file {
    min-height: 80px !important;
}
.compact-file > .empty,
.compact-file .file-upload,
.compact-file [data-testid="file-upload"] {
    min-height: 75px !important;
    padding: 8px 12px !important;
}
.compact-file svg {
    width: 22px !important;
    height: 22px !important;
}

/* Gladak prijelaz tabova */
.tabitem {
    animation: tabFadeIn 0.12s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

@keyframes tabFadeIn {
    0% {
        opacity: 0.90;
    }
    100% {
        opacity: 1;
    }
}

/* ============================================================
   11. CENTERED CONFIRMATION MODALS (OVERLAY & BOX)
   ============================================================ */
.cyber-modal-overlay.hide,
.cyber-modal-overlay[style*="display: none"],
.cyber-modal-overlay[hidden] {
    display: none !important;
}

.cyber-modal-overlay:not(.hide) {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    background: rgba(9, 13, 20, 0.76) !important;
    backdrop-filter: blur(5px) !important;
    -webkit-backdrop-filter: blur(5px) !important;
    z-index: 99999 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 20px !important;
    margin: 0 !important;
    border: none !important;
    border-radius: 0 !important;
}

html.light .cyber-modal-overlay:not(.hide),
body.light .cyber-modal-overlay:not(.hide) {
    background: rgba(15, 23, 42, 0.55) !important;
}

.cyber-modal-overlay:not(.hide) > div:not(.cyber-modal-box) {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    height: 100% !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

.cyber-modal-box {
    background: var(--ind-card) !important;
    background-color: var(--ind-card) !important;
    border: 1px solid var(--ind-border) !important;
    border-top: 3px solid #EF4444 !important;
    border-radius: 10px !important;
    padding: 22px 24px !important;
    width: 100% !important;
    max-width: 560px !important;
    max-height: 88vh !important;
    margin: auto !important;
    overflow-y: auto !important;
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5) !important;
    animation: modalPopIn 0.16s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

@keyframes modalPopIn {
    0% {
        opacity: 0;
        transform: scale(0.95) translateY(8px);
    }
    100% {
        opacity: 1;
        transform: scale(1) translateY(0);
    }
}

.danger-zone-accordion {
    border: 1px solid rgba(239, 68, 68, 0.35) !important;
}

.batch-delete-tray {
    background: var(--ind-card) !important;
    border: 1px solid rgba(239, 68, 68, 0.4) !important;
    border-radius: 6px !important;
    padding: 10px 12px !important;
    margin-bottom: 10px !important;
}
"""

HEAD_THEME_JS = """
<script>
    (function() {
        function getStoredTheme() {
            try {
                return localStorage.getItem('argus_theme') || 'dark';
            } catch(e) {
                return 'dark';
            }
        }

        function setStoredTheme(t) {
            try {
                localStorage.setItem('argus_theme', t);
                localStorage.setItem('color-theme', t);
                localStorage.setItem('theme', t);
            } catch(e) {}
        }

        function applyTheme(theme) {
            const isLight = (theme === 'light');
            window.__theme = isLight ? 'light' : 'dark';
            
            const toAdd = isLight ? 'light' : 'dark';
            const toRemove = isLight ? 'dark' : 'light';
            
            document.documentElement.classList.remove(toRemove);
            document.documentElement.classList.add(toAdd);
            document.documentElement.setAttribute('data-theme', toAdd);
            document.documentElement.style.colorScheme = toAdd;
            
            if (document.body) {
                document.body.classList.remove(toRemove);
                document.body.classList.add(toAdd);
                document.body.setAttribute('data-theme', toAdd);
                document.body.style.colorScheme = toAdd;
            }
            setStoredTheme(window.__theme);
        }

        window.toggleAppTheme = function() {
            const current = window.__theme || getStoredTheme();
            const next = (current === 'light') ? 'dark' : 'light';
            applyTheme(next);
        };

        // Apply theme immediately
        applyTheme(getStoredTheme());

        // Keep observer to enforce theme if Gradio rerenders or alters root classes
        const obs = new MutationObserver(function() {
            const desired = window.__theme || getStoredTheme();
            const isLight = (desired === 'light');
            const root = document.documentElement;
            if (isLight) {
                if (!root.classList.contains('light') || root.classList.contains('dark')) {
                    root.classList.remove('dark');
                    root.classList.add('light');
                    root.setAttribute('data-theme', 'light');
                }
            } else {
                if (!root.classList.contains('dark') || root.classList.contains('light')) {
                    root.classList.remove('light');
                    root.classList.add('dark');
                    root.setAttribute('data-theme', 'dark');
                }
            }
        });
        obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] });

        // Global Drag & Drop safety
        window.addEventListener('dragover', function(e) { e.preventDefault(); }, false);
        window.addEventListener('drop', function(e) {
            var target = e.target;
            if (!target.closest('input[type="file"]') && !target.closest('.upload-container') && !target.closest('.dropzone') && !target.closest('[data-testid="image"]')) {
                e.preventDefault();
            }
        }, false);
    })();
</script>
"""

# Backwards compatibility alias for app.py
HEAD_DARK_JS = HEAD_THEME_JS

custom_theme = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="slate",
    neutral_hue="slate"
).set(
    body_background_fill="var(--ind-bg)",
    body_background_fill_dark="var(--ind-bg)",
    background_fill_primary="var(--ind-bg)",
    background_fill_primary_dark="var(--ind-bg)",
    background_fill_secondary="var(--ind-card)",
    background_fill_secondary_dark="var(--ind-card)",
    block_background_fill="var(--ind-card)",
    block_background_fill_dark="var(--ind-card)",
    block_border_color="var(--ind-border)",
    block_border_color_dark="var(--ind-border)",
    block_radius="6px",
    container_radius="6px",
    block_label_background_fill="var(--ind-card)",
    block_label_background_fill_dark="var(--ind-card)",
    block_label_text_color="var(--text-muted)",
    block_label_text_color_dark="var(--text-muted)",
    block_title_text_color="var(--text-primary)",
    block_title_text_color_dark="var(--text-primary)",
    body_text_color="var(--text-secondary)",
    body_text_color_dark="var(--text-secondary)",
    body_text_color_subdued="var(--text-muted)",
    body_text_color_subdued_dark="var(--text-muted)",
    input_background_fill="var(--ind-input)",
    input_background_fill_dark="var(--ind-input)",
    input_border_color="var(--ind-border)",
    input_border_color_dark="var(--ind-border)",
    input_placeholder_color="var(--text-muted)",
    input_placeholder_color_dark="var(--text-muted)",
    checkbox_background_color="var(--ind-pill)",
    checkbox_background_color_selected="#2563EB",
    checkbox_background_color_dark="var(--ind-pill)",
    checkbox_background_color_selected_dark="#2563EB",
    checkbox_border_color="var(--ind-pill-border)",
    checkbox_border_color_selected="#3B82F6",
    checkbox_border_color_dark="var(--ind-pill-border)",
    checkbox_border_color_selected_dark="#3B82F6",
    checkbox_label_background_fill="transparent",
    checkbox_label_background_fill_dark="transparent",
    checkbox_label_text_color="var(--text-secondary)",
    checkbox_label_text_color_dark="var(--text-secondary)",
    accordion_text_color="var(--text-primary)",
    accordion_text_color_dark="var(--text-primary)",
    table_even_background_fill="var(--ind-card)",
    table_even_background_fill_dark="var(--ind-card)",
    table_odd_background_fill="var(--ind-card)",
    table_odd_background_fill_dark="var(--ind-card)",
    table_text_color="var(--text-secondary)",
    table_text_color_dark="var(--text-secondary)",
    button_primary_background_fill="#2563EB",
    button_primary_background_fill_dark="#2563EB",
    button_primary_text_color="#FFFFFF",
    button_primary_text_color_dark="#FFFFFF",
    button_secondary_background_fill="var(--ind-pill)",
    button_secondary_background_fill_dark="var(--ind-pill)",
    button_secondary_text_color="var(--text-secondary)",
    button_secondary_text_color_dark="var(--text-secondary)"
)


def get_header_bar_html():
    hw_name, _ = hardware.get_onnx_acceleration_status()
    db_stats = db.get_stats()
    p_count = db_stats.get("total_persons", 0)
    safe_hw = html.escape(str(hw_name))
    return f"""
    <div class="industrial-header-bar">
        <div class="header-left">
            <span class="header-brand">ArgusFace</span>
            <span class="header-tagline">Industrial VMS</span>
        </div>
        <div class="header-middle">
            <div class="status-pill">
                <span class="status-dot green"></span>
                <span>100% Lokalno</span>
            </div>
            <div class="status-pill">
                <span class="status-dot blue"></span>
                <span>{safe_hw} Aktivno</span>
            </div>
            <div class="status-pill">
                <span class="status-dot slate"></span>
                <span>Baza: {p_count} osoba</span>
            </div>
        </div>
        <div class="header-right">
            <button id="theme-toggle-btn" class="theme-toggle-btn" onclick="toggleAppTheme()" title="Promijeni temu sučelja (Svijetla / Tamna)">
                <span class="theme-icon-light-indicator">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: -2px; margin-right: 4px;">
                        <circle cx="12" cy="12" r="5"></circle>
                        <line x1="12" y1="1" x2="12" y2="3"></line>
                        <line x1="12" y1="21" x2="12" y2="23"></line>
                        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                        <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                        <line x1="1" y1="12" x2="3" y2="12"></line>
                        <line x1="21" y1="12" x2="23" y2="12"></line>
                        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                        <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
                    </svg>
                    Svijetla tema
                </span>
                <span class="theme-icon-dark-indicator">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: -2px; margin-right: 4px;">
                        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
                    </svg>
                    Tamna tema
                </span>
            </button>
        </div>
    </div>
    """
