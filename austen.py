#!/usr/bin/env python3
"""Austen — AI news digest agent for RAMSAC's salesforce."""

import os
import sys
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

def install(pkg):
    os.system(f"{sys.executable} -m pip install {pkg} -q")

try:
    import anthropic
except ImportError:
    install("anthropic")
    import anthropic

try:
    import requests
except ImportError:
    install("requests")
    import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}

AI_KEYWORDS = {
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "gpt", "claude", "gemini", "mistral",
    "chatgpt", "openai", "anthropic", "deepmind", "meta ai", "grok",
    "neural", "generative", "diffusion", "transformer", "model release",
    "foundation model", "multimodal", "autonomous", "agent", "robotics",
    "inference", "finetuning", "benchmark", "agi",
}

RSS_FEEDS = [
    ("OpenAI Blog",          "https://openai.com/blog/rss.xml",                                    False),
    ("Google DeepMind",      "https://deepmind.google/blog/rss.xml",                               False),
    ("Hugging Face Blog",    "https://huggingface.co/blog/feed.xml",                               False),
    ("The Decoder",          "https://the-decoder.com/feed/",                                      False),
    ("Ars Technica AI",      "https://arstechnica.com/ai/feed/",                                   False),
    ("VentureBeat AI",       "https://venturebeat.com/category/ai/feed/",                          False),
    ("TechCrunch AI",        "https://techcrunch.com/category/artificial-intelligence/feed/",      False),
    ("MIT Technology Review","https://www.technologyreview.com/topic/artificial-intelligence/feed",False),
    ("Wired AI",             "https://www.wired.com/feed/tag/ai/latest/rss",                       False),
    ("IEEE Spectrum AI",     "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",  False),
    ("The Verge",            "https://www.theverge.com/rss/index.xml",                             True),
    ("404 Media",            "https://www.404media.co/rss/",                                       True),
]

def load_system_prompt():
    personality_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personality.md")
    try:
        with open(personality_file, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: personality.md not found at {personality_file}, using default prompt.")
        return "You are an AI news curator for a sales team. Select the 5 most significant AI stories and present them in an enthusiastic, optimistic tone for sales professionals."

SYSTEM_PROMPT = load_system_prompt()


def parse_date(date_str):
    if not date_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def is_ai_related(title, summary):
    text = (title + " " + summary).lower()
    return any(kw in text for kw in AI_KEYWORDS)


def fetch_rss(name, url, ai_filter, cutoff):
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for item in root.findall(".//item"):
            pub = (item.findtext("pubDate") or
                   item.findtext("{http://purl.org/dc/elements/1.1/}date") or "")
            dt = parse_date(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                continue
            title = (item.findtext("title") or "").strip()
            summary = (item.findtext("description") or "").strip()[:800]
            if ai_filter and not is_ai_related(title, summary):
                continue
            articles.append({"source": name, "title": title, "summary": summary,
                              "date": dt.strftime("%Y-%m-%d"), "ts": dt})

        for entry in root.findall("atom:entry", ns):
            pub = (entry.findtext("atom:published", namespaces=ns) or
                   entry.findtext("atom:updated", namespaces=ns) or "")
            dt = parse_date(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                continue
            title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
            sel = entry.find("atom:summary", ns)
            if sel is None:
                sel = entry.find("atom:content", ns)
            summary = (sel.text or "").strip()[:800] if sel is not None else ""
            if ai_filter and not is_ai_related(title, summary):
                continue
            articles.append({"source": name, "title": title, "summary": summary,
                              "date": dt.strftime("%Y-%m-%d"), "ts": dt})
    except Exception as e:
        print(f"  Warning: could not fetch {name} ({e})")
    return articles


def load_knowledge_log():
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_log.json")
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"terms": []}


def save_knowledge_log(log, used_term_names=None):
    existing = {t["term"].lower(): i for i, t in enumerate(log["terms"])}

    # Increment teach_count for every term that was highlighted this run
    if used_term_names:
        for name in used_term_names:
            idx = existing.get(name.lower())
            if idx is not None:
                log["terms"][idx]["teach_count"] = log["terms"][idx].get("teach_count", 0) + 1

    # Ensure every term has at least teach_count=1 (it was taught today, even if not highlighted in text)
    for t in log["terms"]:
        if t.get("teach_count", 0) == 0:
            t["teach_count"] = 1

    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_log.json")
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def apply_term_highlights(data, knowledge_log):
    """Wrap eligible terms in story text with tooltip spans. Returns modified data and set of used term names."""
    eligible = [t for t in knowledge_log.get("terms", []) if t.get("teach_count", 0) < 7]
    eligible.sort(key=lambda t: len(t["term"]), reverse=True)  # longest first to avoid partial matches

    used_terms = set()

    for story in data.get("stories", []):
        for field in ("glance", "deep_p1", "deep_p2"):
            text = story.get(field, "")
            for t in eligible:
                # Strip parenthetical qualifiers Claude may append (e.g. "fine-tuning (in AI)" -> "fine-tuning")
                search_term = re.sub(r'\s*\([^)]*\)', '', t["term"]).strip()
                if not search_term:
                    continue
                definition = t["definition"].replace("'", "&#39;").replace('"', '&quot;')
                pattern = re.compile(r'\b' + re.escape(search_term) + r'\b', re.IGNORECASE)
                replacement = f'<span class="ai-term" data-def="{definition}">\\g<0></span>'
                new_text, count = pattern.subn(replacement, text)
                if count:
                    used_terms.add(t["term"])
                text = new_text
            story[field] = text

    return data, used_terms


def build_user_prompt(articles, knowledge_log):
    today = datetime.now().strftime("%B %d, %Y")
    known_terms = knowledge_log.get("terms", [])

    lines = [
        f"Today is {today}.",
        "",
        f"Below are {len(articles)} AI news articles from the past 7 days.",
        "Select the 5 most significant stories, prioritising model releases and capability breakthroughs.",
        "Even controversial stories (government bans, regulation) should be framed around the achievement.",
        "",
    ]

    if known_terms:
        lines += [
            "─── TERMS ALREADY TAUGHT ───",
            "The following terms have already been introduced to the sales team in previous editions.",
            "Do NOT list them as new terms.",
            "IMPORTANT: If a story is about a concept from this list, you MUST use the exact term phrase",
            "from the list somewhere in your story text (glance, deep_p1, or deep_p2) so it gets highlighted.",
            "For example: if 'Diffusion-based generation' is in this list and you are writing about a diffusion",
            "model, write 'Diffusion-based generation' in the story text — not 'diffusion techniques' or",
            "'diffusion approach'. The exact phrase must appear so the reader can see the tooltip.",
            "",
        ]
        for t in known_terms:
            lines.append(f"- {t['term']} (first taught: {t['first_seen']})")
        lines.append("")

    lines += [
        "─── YOUR TASK ───",
        "1. Write the 5 stories as instructed.",
        "",
        "   STORY ORDERING — BOTH RULES ARE NON-NEGOTIABLE:",
        "",
        "   RULE A — POSITION 1 MUST BE A CAPABILITY OR POWER STORY:",
        "   If any story this week shows an AI model doing something remarkable — so powerful it triggered",
        "   government action, broke a record, crossed a threshold, or shocked experts — that is position 1.",
        "   No other story type can displace it. Examples: a model banned by the White House for being too",
        "   dangerous, a new architecture that generates text 4x faster, a model beating human experts for",
        "   the first time. If two capability stories exist, pick the more dramatic one for position 1.",
        "",
        "   RULE B — POSITION 5 MUST BE THE AWARENESS STORY:",
        "   Position 5 is reserved EXCLUSIVELY for awareness stories: vulnerabilities, hacks, bans, model",
        "   shutdowns, AI causing harm, or any story where the headline describes AI failing or being dangerous.",
        "   A vulnerability story MUST be position 5 even if it is the most widely covered story of the week.",
        "   Newsworthiness does not override this rule.",
        "",
        "2. Identify NEW technical terms or concepts in this week's news that are NOT in the list above.",
        "   Only add terms that would not exist without AI — concepts AI invented or radically redefined.",
        "   Do NOT explain: fine-tuning, compute, inference, machine learning, deep learning, open-source,",
        "   benchmark, training, scaling, tokens, or any general IT/business/cybersecurity term.",
        "   These are known to the audience. Only add terms that create a genuine 'aha' moment for someone",
        "   new to AI specifically.",
        "",
        "Return ONLY a valid JSON object — no markdown fences, no extra text — matching this schema exactly:",
        "",
        '{',
        '  "subject": "This Week in AI — <5-7 word catchy headline>",',
        '  "intro": "<One energetic sentence setting the tone for the week>",',
        '  "stories": [',
        '    {',
        '      "title": "<story headline>",',
        '      "source": "<publication name>",',
        '      "glance": "<2-3 sentence punchy summary focused on achievement and why it matters>",',
        '      "deep_p1": "<paragraph: what happened, who, what it can do, what makes it remarkable>",',
        '      "deep_p2": "<paragraph: what this unlocks for businesses, what changes, what to watch>"',
        '    }',
        '  ],',
        '  "new_terms": [',
        '    {',
        '      "term": "<technical term or concept>",',
        '      "definition": "<plain-English definition a salesperson can repeat to a client>",',
        '      "story": "<title of the story where this term appeared>"',
        '    }',
        '  ]',
        '}',
        "",
        "─── ARTICLES ───",
    ]
    for i, a in enumerate(articles, 1):
        lines.append(f"\n[{i}] {a['date']} | {a['source']}")
        lines.append(f"Title: {a['title']}")
        if a["summary"]:
            lines.append(f"Excerpt: {a['summary']}")
    return "\n".join(lines)


# ─── Plain-text renderer ────────────────────────────────────────────────────

def render_text(data, today):
    lines = [
        f"Subject: {data['subject']}",
        "",
        "Hi team,",
        "",
        data["intro"],
        "",
        "━" * 38,
        "TOP 5 AI STORIES AT A GLANCE",
        "━" * 38,
        "",
    ]
    for i, s in enumerate(data["stories"], 1):
        lines += [f"{i}. {s['title']}", s["glance"], ""]

    lines += ["━" * 38, "DEEP DIVE — THE FULL STORY", "━" * 38, ""]
    for i, s in enumerate(data["stories"], 1):
        lines += [f"{i}. {s['title']}", s["deep_p1"], "", s["deep_p2"], ""]

    lines += ["━" * 38, "", "Stay curious, stay ahead. See you next week!"]
    return "\n".join(lines)


# ─── HTML renderer ──────────────────────────────────────────────────────────

TOOLTIP_CSS = """
  .ai-term {
    color: #3bb2b7;
    font-weight: 700;
    border-bottom: 2px dashed #4ddcc3;
    cursor: help;
  }
  #ai-tooltip {
    position: fixed;
    display: none;
    background: #152230;
    color: #ffffff;
    font-size: 12px;
    font-weight: 400;
    line-height: 1.5;
    border-radius: 8px;
    padding: 10px 14px;
    border: 1px solid #4ddcc3;
    box-shadow: 0 4px 20px rgba(21,34,48,0.4);
    max-width: 260px;
    width: 260px;
    z-index: 9999;
    pointer-events: none;
    white-space: normal;
  }
  .fb-btn {
    background: none;
    border: 1px solid #c7e6ff;
    border-radius: 6px;
    color: #93979f;
    cursor: pointer;
    font-size: 15px;
    padding: 3px 10px;
    margin-left: 6px;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .fb-btn:hover { border-color: #4ddcc3; color: #152230; }
  .fb-btn.active-up { background: rgba(77,220,195,0.12); border-color: #4ddcc3; color: #11383f; }
  .fb-btn.active-dn { background: rgba(253,185,19,0.12); border-color: #fdb913; color: #7a5c00; }
  #fb-section textarea {
    width: 100%;
    box-sizing: border-box;
    background: #ffffff;
    border: 1px solid #c7e6ff;
    border-radius: 8px;
    color: #373c46;
    font-size: 13px;
    font-family: "Manrope", Arial, sans-serif;
    line-height: 1.6;
    padding: 12px 14px;
    resize: vertical;
    outline: none;
    transition: border-color 0.15s;
  }
  #fb-section textarea:focus { border-color: #4ddcc3; }
  #fb-submit {
    margin-top: 10px;
    background: #fdb913;
    border: none;
    border-radius: 8px;
    color: #152230;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    font-family: "Manrope", Arial, sans-serif;
    padding: 10px 22px;
    transition: opacity 0.15s;
  }
  #fb-submit:hover { opacity: 0.85; }
  #fb-thanks {
    display: none;
    margin-top: 10px;
    font-size: 13px;
    color: #3bb2b7;
    font-family: "Manrope", Arial, sans-serif;
  }"""

ACCENT   = "#4ddcc3"   # RAMSAC mint teal — primary brand accent
PURPLE   = "#3bb2b7"   # RAMSAC fresh teal — secondary / metadata
BG_MAIN  = "#f5fbff"   # RAMSAC light blue — page surface
BG_CARD  = "#ffffff"   # White — card surface
BG_CARD2 = "#ffffff"   # White — modal surface
TEXT     = "#373c46"   # RAMSAC contrast — primary text
MUTED    = "#5a5a5a"   # Secondary text
BORDER   = "#c7e6ff"   # RAMSAC light blue — hairlines
NAVY     = "#152230"   # RAMSAC dark navy — header/footer
DARK_TEAL = "#11383f"  # RAMSAC dark teal — header gradient end


def story_number_badge(n):
    return (
        f'<td width="48" valign="top" style="padding:0 14px 0 0">'
        f'<div style="width:36px;height:36px;border-radius:50%;background:#4ddcc3;'
        f'text-align:center;line-height:36px;font-size:15px;font-weight:700;color:#152230;font-family:Montserrat,Arial,sans-serif">'
        f'{n}</div></td>'
    )


def glance_card(n, story):
    modal_id = f"modal-{n}"
    return f"""
    <tr>
      <td style="padding:0 0 12px 0">
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="background:{BG_CARD};border-radius:8px;border:1px solid {BORDER};border-left:3px solid {ACCENT}">
          <tr>
            <td style="padding:20px 22px">
              <table cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                  {story_number_badge(n)}
                  <td valign="middle">
                    <p onclick="openModal('{modal_id}')" style="margin:0;font-size:15px;font-weight:700;color:{NAVY};font-family:Montserrat,Arial,sans-serif;line-height:1.3;cursor:pointer">{story['title']} <span style="font-size:11px;color:{ACCENT};opacity:0.8">&#8599;</span></p>
                  </td>
                </tr>
                <tr><td colspan="2" style="padding-top:10px">
                  <p style="margin:0;font-size:14px;color:{MUTED};font-family:Manrope,Arial,sans-serif;line-height:1.6">{story['glance']}</p>
                </td></tr>
                <tr><td colspan="2" style="padding-top:10px;text-align:right">
                  <button class="fb-btn" id="up-{n}" onclick="vote({n},'up')" title="Useful">&#128077;</button>
                  <button class="fb-btn" id="dn-{n}" onclick="vote({n},'dn')" title="Not useful">&#128078;</button>
                </td></tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def story_modal(n, story):
    modal_id = f"modal-{n}"
    return f"""
<div id="{modal_id}" class="modal" onclick="if(event.target===this)closeModal('{modal_id}')">
  <div class="modal-content">
    <button class="modal-close" onclick="closeModal('{modal_id}')">&times;</button>
    <p style="margin:0 0 8px 0;font-size:11px;color:{ACCENT};font-family:Montserrat,Arial,sans-serif;text-transform:uppercase;letter-spacing:0.12em;font-weight:600">{story['source']}</p>
    <h2 style="margin:0 0 20px 0;font-size:20px;font-weight:700;color:{NAVY};font-family:Montserrat,Arial,sans-serif;line-height:1.3">{story['title']}</h2>
    <p style="margin:0 0 14px 0;font-size:14px;color:{TEXT};font-family:Manrope,Arial,sans-serif;line-height:1.7">{story['deep_p1']}</p>
    <p style="margin:0;font-size:14px;color:{MUTED};font-family:Manrope,Arial,sans-serif;line-height:1.7">{story['deep_p2']}</p>
  </div>
</div>"""


def section_header(title, icon):
    return f"""
    <tr>
      <td style="padding:0 0 20px 0">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td style="border-top:1px solid {BORDER};padding-top:28px">
              <p style="margin:0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:{ACCENT};font-family:Montserrat,Arial,sans-serif;font-weight:700">{title}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def new_terms_section(new_terms):
    # Section removed — terms are explained via inline hover tooltips only
    return ""


def render_html(data, today, date_slug):
    glance_rows  = "".join(glance_card(i + 1, s) for i, s in enumerate(data["stories"]))
    modals       = "".join(story_modal(i + 1, s) for i, s in enumerate(data["stories"]))
    terms_section = new_terms_section(data.get("new_terms", []))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{data['subject']}</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
{TOOLTIP_CSS}
  .modal {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(24,27,26,0.6);
    z-index: 1000;
    align-items: center;
    justify-content: center;
    padding: 16px;
  }}
  .modal.active {{ display: flex; }}
  .modal-content {{
    background: {BG_CARD2};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 32px;
    max-width: 600px;
    width: 100%;
    max-height: 80vh;
    overflow-y: auto;
    position: relative;
    box-shadow: 0 20px 48px -12px rgba(21,34,48,0.3);
  }}
  .modal-close {{
    position: absolute;
    top: 14px;
    right: 18px;
    background: none;
    border: none;
    color: #93979f;
    font-size: 26px;
    cursor: pointer;
    line-height: 1;
  }}
  .modal-close:hover {{ color: {TEXT}; }}
</style>
</head>
<body style="margin:0;padding:0;background-color:#f5fbff;font-family:Manrope,Arial,Helvetica,sans-serif">

<!-- Outer wrapper -->
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f5fbff;min-height:100vh">
<tr><td align="center" style="padding:32px 16px">

<!-- Email container -->
<table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%">

  <!-- ── HEADER ── -->
  <tr>
    <td style="background:linear-gradient(135deg,#152230 0%,#11383f 100%);border-radius:12px 12px 0 0;padding:40px 36px 36px;border-bottom:3px solid #4ddcc3">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td>
            <p style="margin:0 0 8px 0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#4ddcc3;font-family:Montserrat,Arial,sans-serif;font-weight:600">Austen &nbsp;·&nbsp; Weekly Briefing &nbsp;·&nbsp; {today}</p>
            <h1 style="margin:0;font-size:28px;font-weight:800;color:#ffffff;font-family:Montserrat,Arial,sans-serif;line-height:1.2">
              <span style="color:#4ddcc3">This Week</span> in AI
            </h1>
            <p style="margin:12px 0 0 0;font-size:14px;color:rgba(255,255,255,0.75);font-family:Manrope,Arial,sans-serif;line-height:1.6">{data['intro']}</p>
          </td>
          <td width="80" align="right" valign="top">
            <p style="margin:0;font-size:22px;font-weight:800;color:#4ddcc3;font-family:Montserrat,Arial,sans-serif;letter-spacing:-0.03em;line-height:1">ramsac</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- ── BODY ── -->
  <tr>
    <td style="background:{BG_MAIN};padding:28px 32px 8px;border-left:1px solid {BORDER};border-right:1px solid {BORDER}">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">

        {section_header("Top 5 at a Glance — click a title for the full story", "")}
        {glance_rows}
        {terms_section}

      </table>
    </td>
  </tr>

  <!-- ── FEEDBACK ── -->
  <tr>
    <td id="fb-section" style="background:{BG_MAIN};padding:24px 32px 32px;border-left:1px solid {BORDER};border-right:1px solid {BORDER};border-top:1px solid {BORDER}">
      <p style="margin:0 0 10px 0;font-size:14px;font-weight:600;color:{MUTED};font-family:Manrope,Arial,sans-serif">How can we make this more useful?</p>
      <textarea id="fb-text" rows="3" placeholder="Your thoughts..."></textarea>
      <br><button id="fb-submit" onclick="submitFeedback()">Send feedback</button>
      <p id="fb-thanks">Thanks! Your feedback has been saved.</p>
    </td>
  </tr>

  <!-- ── FOOTER ── -->
  <tr>
    <td style="background:{NAVY};border-radius:0 0 12px 12px;padding:28px 36px;border:1px solid {NAVY}">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td>
            <p style="margin:0 0 4px 0;font-size:15px;font-weight:700;color:#ffffff;font-family:Montserrat,Arial,sans-serif">Stay curious, stay ahead.</p>
            <p style="margin:0;font-size:13px;color:rgba(255,255,255,0.6);font-family:Manrope,Arial,sans-serif">See you next week.</p>
          </td>
          <td align="right">
            <p style="margin:0;font-size:11px;font-weight:800;color:#4ddcc3;font-family:Montserrat,Arial,sans-serif;letter-spacing:-0.02em">ramsac</p>
            <p style="margin:2px 0 0 0;font-size:10px;color:rgba(255,255,255,0.4);font-family:Manrope,Arial,sans-serif">Austen — Weekly AI Briefing</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

</table>
</td></tr>
</table>

{modals}

<div id="ai-tooltip"></div>
<script>
  function openModal(id) {{
    document.getElementById(id).classList.add('active');
    document.body.style.overflow = 'hidden';
  }}
  function closeModal(id) {{
    document.getElementById(id).classList.remove('active');
    document.body.style.overflow = '';
  }}
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{
      document.querySelectorAll('.modal.active').forEach(function(m) {{
        m.classList.remove('active');
      }});
      document.body.style.overflow = '';
    }}
  }});
  function vote(n, dir) {{
    var up = document.getElementById('up-' + n);
    var dn = document.getElementById('dn-' + n);
    var key = 'vote-{date_slug}-' + n;
    var current = localStorage.getItem(key);
    up.classList.remove('active-up');
    dn.classList.remove('active-dn');
    if (current === dir) {{
      localStorage.removeItem(key);
    }} else {{
      if (dir === 'up') up.classList.add('active-up');
      else dn.classList.add('active-dn');
      localStorage.setItem(key, dir);
    }}
  }}
  function submitFeedback() {{
    var text = document.getElementById('fb-text').value.trim();
    var votes = {{}};
    for (var i = 1; i <= 5; i++) {{
      var v = localStorage.getItem('vote-{date_slug}-' + i);
      if (v) votes[i] = v;
    }}
    localStorage.setItem('feedback-{date_slug}', text);
    var thanks = document.getElementById('fb-thanks');
    fetch('/api/feedback', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{digest_date: '{date_slug}', votes: votes, text: text}})
    }}).then(function() {{
      thanks.textContent = 'Thanks! Your feedback has been sent.';
    }}).catch(function() {{
      thanks.textContent = 'Saved locally (server unreachable).';
    }}).finally(function() {{
      thanks.style.display = 'block';
      setTimeout(function() {{ thanks.style.display = 'none'; }}, 3000);
    }});
  }}
  document.addEventListener('DOMContentLoaded', function() {{
    for (var i = 1; i <= 5; i++) {{
      var v = localStorage.getItem('vote-{date_slug}-' + i);
      if (v === 'up') document.getElementById('up-' + i).classList.add('active-up');
      if (v === 'dn') document.getElementById('dn-' + i).classList.add('active-dn');
    }}
    var saved = localStorage.getItem('feedback-{date_slug}');
    if (saved) document.getElementById('fb-text').value = saved;
  }});
  (function() {{
    var tip = document.getElementById('ai-tooltip');
    function positionTip(e) {{
      var tw = tip.offsetWidth, th = tip.offsetHeight;
      var vw = window.innerWidth, vh = window.innerHeight;
      var top = e.clientY - th - 14;
      var left = e.clientX - tw / 2;
      if (top < 8) top = e.clientY + 18;
      if (left < 8) left = 8;
      if (left + tw > vw - 8) left = vw - tw - 8;
      tip.style.top = top + 'px';
      tip.style.left = left + 'px';
    }}
    document.querySelectorAll('.ai-term').forEach(function(el) {{
      el.addEventListener('mouseenter', function(e) {{
        tip.textContent = el.getAttribute('data-def');
        tip.style.display = 'block';
        positionTip(e);
      }});
      el.addEventListener('mousemove', positionTip);
      el.addEventListener('mouseleave', function() {{
        tip.style.display = 'none';
      }});
    }});
  }})();
</script>
</body>
</html>"""


# ─── GitHub Pages publisher ─────────────────────────────────────────────────

PAGES_BASE_URL = "https://ironbridge-ai.github.io/Austen"


def write_index(directory, html_files):
    """Generate index.html listing all digest editions newest-first."""
    def date_label(filename):
        slug = filename.replace("austen_", "").replace(".html", "")
        try:
            dt = datetime.strptime(slug, "%Y-%m-%d")
            return dt.strftime("%B %d, %Y"), slug
        except ValueError:
            return slug, slug

    cards = []
    for f in html_files:
        label, slug = date_label(f)
        cards.append(
            f'    <div class="edition-card">\n'
            f'      <div>\n'
            f'        <div class="edition-date">{label}</div>\n'
            f'      </div>\n'
            f'      <a class="view-btn" href="{f}">View &rarr;</a>\n'
            f'    </div>'
        )

    cards_html = "\n".join(cards)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Austen — Weekly AI Briefing by RAMSAC</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&family=Manrope:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #f5fbff; font-family: Manrope, Arial, sans-serif; color: #373c46; min-height: 100vh; padding: 40px 16px 60px; }}
  .container {{ max-width: 640px; margin: 0 auto; }}
  .header {{ background: linear-gradient(135deg, #152230 0%, #11383f 100%); border-radius: 12px 12px 0 0; padding: 36px 36px 32px; border-bottom: 3px solid #4ddcc3; display: flex; align-items: flex-end; justify-content: space-between; }}
  .header h1 {{ font-family: Montserrat, Arial, sans-serif; font-size: 26px; font-weight: 800; color: #fff; line-height: 1.2; }}
  .header h1 span {{ color: #4ddcc3; }}
  .header-sub {{ font-family: Montserrat, Arial, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: #4ddcc3; font-weight: 600; margin-bottom: 8px; }}
  .header-brand {{ font-family: Montserrat, Arial, sans-serif; font-size: 20px; font-weight: 800; color: #4ddcc3; letter-spacing: -0.03em; }}
  .body {{ background: #f5fbff; border-left: 1px solid #c7e6ff; border-right: 1px solid #c7e6ff; padding: 28px 32px 32px; }}
  .section-label {{ font-family: Montserrat, Arial, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: #4ddcc3; font-weight: 700; border-top: 1px solid #c7e6ff; padding-top: 24px; margin-bottom: 20px; }}
  .edition-card {{ background: #fff; border: 1px solid #c7e6ff; border-left: 3px solid #4ddcc3; border-radius: 8px; padding: 18px 20px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }}
  .edition-date {{ font-family: Montserrat, Arial, sans-serif; font-size: 14px; font-weight: 700; color: #152230; }}
  .view-btn {{ display: inline-block; background: #4ddcc3; color: #152230; font-family: Montserrat, Arial, sans-serif; font-size: 12px; font-weight: 700; text-decoration: none; padding: 8px 16px; border-radius: 6px; white-space: nowrap; transition: opacity 0.15s; }}
  .view-btn:hover {{ opacity: 0.85; }}
  .footer {{ background: #152230; border-radius: 0 0 12px 12px; border: 1px solid #152230; padding: 22px 32px; display: flex; align-items: center; justify-content: space-between; }}
  .footer p {{ font-size: 12px; color: rgba(255,255,255,0.5); font-family: Manrope, Arial, sans-serif; }}
  .footer-brand {{ font-family: Montserrat, Arial, sans-serif; font-size: 18px; font-weight: 800; color: #4ddcc3; letter-spacing: -0.02em; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <p class="header-sub">Austen &nbsp;&middot;&nbsp; Weekly AI Briefing</p>
      <h1><span>This Week</span> in AI</h1>
    </div>
    <div class="header-brand">ramsac</div>
  </div>
  <div class="body">
    <p class="section-label">All Editions</p>
{cards_html}
  </div>
  <div class="footer">
    <p>Stay curious, stay ahead.</p>
    <div class="footer-brand">ramsac</div>
  </div>
</div>
</body>
</html>"""

    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def publish_to_pages(html_file, date_slug):
    """Clone gh-pages, add new digest, rebuild index, commit and push."""
    import subprocess
    import shutil
    import tempfile

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_url = subprocess.check_output(
        ["git", "-C", script_dir, "remote", "get-url", "origin"], text=True
    ).strip()

    print("\nPublishing to GitHub Pages...")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["git", "clone", "--branch", "gh-pages", "--single-branch", repo_url, tmp],
            check=True, capture_output=True
        )

        shutil.copy(os.path.join(script_dir, html_file), os.path.join(tmp, html_file))

        pages = sorted(
            [f for f in os.listdir(tmp) if f.startswith("austen_") and f.endswith(".html")],
            reverse=True
        )
        write_index(tmp, pages)

        subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
        result = subprocess.run(
            ["git", "-C", tmp, "commit", "-m", f"Austen digest {date_slug}"],
            capture_output=True, text=True
        )
        if result.returncode != 0 and "nothing to commit" in result.stdout:
            print("--- Pages: nothing new to publish.")
            return
        subprocess.run(["git", "-C", tmp, "push", "origin", "gh-pages"], check=True, capture_output=True)

    print(f"--- Published:   {PAGES_BASE_URL}/")
    print(f"--- Direct link: {PAGES_BASE_URL}/{html_file}")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    api_key  = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    print("Fetching AI news from sources...")
    all_articles = []
    for name, url, ai_filter in RSS_FEEDS:
        found = fetch_rss(name, url, ai_filter, cutoff)
        label = f"{len(found)} articles" + (" (AI-filtered)" if ai_filter else "")
        print(f"  {name}: {label}")
        all_articles.extend(found)

    all_articles.sort(key=lambda a: a["ts"], reverse=True)
    seen, unique = set(), []
    for a in all_articles:
        k = a["title"].lower().strip()
        if k not in seen:
            seen.add(k)
            unique.append(a)

    if not unique:
        print("\nNo articles found in the past 7 days.")
        sys.exit(1)

    print(f"\nTotal: {len(unique)} unique articles. Sending to Claude...\n")

    knowledge_log = load_knowledge_log()
    print(f"Knowledge log loaded: {len(knowledge_log.get('terms', []))} terms already taught.\n")

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**client_kwargs)

    response = client.messages.create(
        model="eu.anthropic.claude-opus-4-6-v1",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(unique, knowledge_log)}],
    )

    raw = response.content[0].text.strip()
    # Strip accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Claude sometimes outputs the JSON twice; extract just the first complete object
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(raw)
        except json.JSONDecodeError as e:
            print(f"Error: Claude didn't return valid JSON.\n{e}\n\nRaw output:\n{raw}")
            sys.exit(1)

    today = datetime.now().strftime("%B %d, %Y")
    date_slug = datetime.now().strftime("%Y-%m-%d")

    # Blocklist: general IT/business/cybersecurity terms that are never AI-specific
    TERM_BLOCKLIST = {
        "jailbreak", "data exfiltration", "usage-based billing", "usage based billing",
        "data governance", "market share", "acquisition", "valuation", "funding round",
        "export controls", "two-factor authentication", "2fa", "vulnerability", "exploit",
        "patch", "cloud computing", "saas", "api", "best-of-breed", "all-stock",
        "all-stock acquisition", "consumption policies", "decision loop", "pair-programmer",
        "arms race", "supply chain", "phishing", "malware", "ransomware", "firewall",
        "revenue", "ipo", "market cap",
        # General computing/infrastructure terms an IT professional already knows
        "compute", "inference", "latency", "bandwidth", "server", "hardware", "software",
        "database", "encryption", "authentication", "network", "endpoint", "protocol",
        "token", "tokens", "model", "machine learning", "deep learning",
        # Basic ML/AI concepts the RAMSAC audience already understands
        "fine-tuning", "fine-tuned", "fine-tune", "finetuning", "finetuned",
        "training", "pre-training", "pre-trained", "model training",
        "open-source", "open source", "open-weight", "open weight",
        "benchmark", "benchmarks", "evaluation", "test set",
        "accuracy", "performance",
        "scaling", "scale",
    }
    new_terms_raw = data.get("new_terms", [])
    new_terms_filtered = [
        t for t in new_terms_raw
        if t["term"].lower().strip() not in TERM_BLOCKLIST
    ]
    if len(new_terms_filtered) < len(new_terms_raw):
        blocked = [t["term"] for t in new_terms_raw if t not in new_terms_filtered]
        print(f"Blocklist removed {len(blocked)} term(s): {blocked}\n")
    data["new_terms"] = new_terms_filtered

    # Inject new terms into the in-memory log BEFORE highlighting,
    # so they get wrapped in tooltips just like existing terms.
    new_terms = data.get("new_terms", [])
    existing_keys = {t["term"].lower() for t in knowledge_log["terms"]}
    added = 0
    for t in new_terms:
        if t["term"].lower() not in existing_keys:
            knowledge_log["terms"].append({
                "term": t["term"],
                "definition": t["definition"],
                "first_seen": date_slug,
                "story": t.get("story", ""),
                "teach_count": 0
            })
            existing_keys.add(t["term"].lower())
            added += 1
    if added:
        print(f"Knowledge log: {added} new term(s) staged for highlighting.\n")

    data, used_terms = apply_term_highlights(data, knowledge_log)
    if used_terms:
        print(f"Highlighted {len(used_terms)} term(s) in stories.\n")

    # Drop any new term that wasn't found in the story text — no orphan definitions
    used_lower = {n.lower() for n in used_terms}
    data["new_terms"] = [t for t in data.get("new_terms", []) if t["term"].lower() in used_lower]

    # Also remove from the in-memory log any staged term that wasn't highlighted
    knowledge_log["terms"] = [
        t for t in knowledge_log["terms"]
        if t.get("teach_count", 0) > 0 or t["term"].lower() in used_lower
    ]

    save_knowledge_log(knowledge_log, used_term_names=used_terms)
    print(f"Knowledge log saved. Total terms: {len(knowledge_log['terms'])}.\n")

    txt_file  = f"austen_{date_slug}.txt"
    html_file = f"austen_{date_slug}.html"

    txt = render_text(data, today)
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(txt)

    html = render_html(data, today, date_slug)
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(txt)
    print(f"\n--- Text saved to {txt_file}")
    print(f"--- HTML saved to {html_file}")

    publish_to_pages(html_file, date_slug)


if __name__ == "__main__":
    main()
