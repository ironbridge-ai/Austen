#!/usr/bin/env python3
"""Austen — AI news digest agent for ramsac's salesforce."""

import os
import sys
import json
import re
import urllib.parse
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
            summary = (item.findtext("description") or "").strip()[:400]
            link = (item.findtext("link") or "").strip()
            if ai_filter and not is_ai_related(title, summary):
                continue
            articles.append({"source": name, "title": title, "summary": summary,
                              "date": dt.strftime("%Y-%m-%d"), "ts": dt, "url": link})

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
            summary = (sel.text or "").strip()[:400] if sel is not None else ""
            link_el = entry.find("atom:link", ns)
            link = (link_el.get("href") or "").strip() if link_el is not None else ""
            if ai_filter and not is_ai_related(title, summary):
                continue
            articles.append({"source": name, "title": title, "summary": summary,
                              "date": dt.strftime("%Y-%m-%d"), "ts": dt, "url": link})
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


def load_stories_log():
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stories_log.json")
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"stories": []}


def save_stories_log(log):
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stories_log.json")
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def append_published_stories(stories, date_slug):
    log = load_stories_log()
    for s in stories:
        log["stories"].append({
            "date":   date_slug,
            "title":  s.get("title", ""),
            "source": s.get("source", ""),
            "topic":  s.get("glance", "")[:200],
        })
    save_stories_log(log)


def recent_published_stories(weeks=2):
    """Return stories published in the last `weeks` weeks."""
    log = load_stories_log()
    cutoff = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    return [s for s in log["stories"] if s.get("date", "") >= cutoff]


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

    def highlight(text):
        for t in eligible:
            # Strip parenthetical qualifiers Claude may append (e.g. "fine-tuning (in AI)" -> "fine-tuning")
            search_term = re.sub(r'\s*\([^)]*\)', '', t["term"]).strip()
            if not search_term:
                continue
            definition = t["definition"].replace("'", "&#39;").replace('"', '&quot;')
            pattern = re.compile(r'\b' + re.escape(search_term) + r's?\b', re.IGNORECASE)
            replacement = f'<span class="ai-term" data-def="{definition}" data-term="{search_term}">\\g<0></span>'
            new_text, count = pattern.subn(replacement, text)
            if count:
                used_terms.add(t["term"])
            text = new_text
        return text

    for story in data.get("stories", []):
        story["glance"] = highlight(story.get("glance", ""))
        story["bullets"] = [highlight(b) for b in story.get("bullets", [])]

    return data, used_terms


def build_user_prompt(articles, knowledge_log):
    today = datetime.now().strftime("%B %d, %Y")
    known_terms = knowledge_log.get("terms", [])
    prev_stories = recent_published_stories(weeks=2)

    lines = [
        f"Today is {today}.",
        "",
        f"Below are {len(articles)} AI news articles from the past 7 days.",
        "Select the 5 most significant stories, prioritising model releases and capability breakthroughs.",
        "Even controversial stories (government bans, regulation) should be framed around the achievement.",
        "",
    ]

    if prev_stories:
        lines += [
            "─── STORIES ALREADY PUBLISHED (last 2 weeks) ───",
            "The following stories have already been covered in recent editions of this digest.",
            "Do NOT select a story that covers the same topic, company announcement, or event as any entry below.",
            "EXCEPTION: If a story is a meaningful UPDATE or DEVELOPMENT on a previously covered topic",
            "(e.g. a model that was banned last week has now been re-released, or a vulnerability that was",
            "disclosed last week has now been patched and caused wider impact), you MAY include it — but you",
            "MUST explicitly note in the glance that it is a follow-up to last week's coverage.",
            "",
        ]
        for s in prev_stories:
            lines.append(f"- [{s['date']}] {s['title']} ({s['source']})")
            if s.get("topic"):
                lines.append(f"  Topic summary: {s['topic']}")
        lines.append("")

    if known_terms:
        lines += [
            "─── TERMS ALREADY TAUGHT ───",
            "The following terms have already been introduced to the sales team in previous editions.",
            "Do NOT list them as new terms.",
            "IMPORTANT: If a story is about a concept from this list, you MUST use the exact term phrase",
            "from the list somewhere in your story text (glance or bullets) so it gets highlighted.",
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
        '  "intro": "<One energetic sentence capturing the week AS A WHOLE. Find the common thread across at least 2-3 of the 5 stories below, not just story 1. Do not simply restate the lead story.>",',
        '  "stories": [',
        '    {',
        '      "title": "<story headline>",',
        '      "source": "<publication name>",',
        '      "glance": "<1-2 sentence concise summary of what happened, no sales framing>",',
        '      "bullets": ["<concise fact: who/what>", "<concise fact: what it can do>", "<concise fact: what makes it remarkable>", "<optional concise fact: what to watch next>"],',
        '      "ramsac_angle": "<2-3 sentences that ARE the talking point itself, not instructions about it. Do NOT prefix with labels like \'Ask your client:\', \'Open with:\', \'The line for clients:\'. Just write the question or observation directly, as a sentence someone outside ramsac could read and still get the point, while it stays usable verbatim by a rep in a client conversation.>",',
        '      "source_index": <the [N] number of the article below this story is based on, so the link back to the original can be resolved automatically>',
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
        lines += [f"{i}. {s['title']}"]
        lines += [f"  - {b}" for b in s.get("bullets", [])]
        if s.get("ramsac_angle"):
            lines += ["", f"  ramsac angle: {s['ramsac_angle']}"]
        lines.append("")

    lines += ["━" * 38, "", "Stay curious, stay ahead. See you next week!"]
    return "\n".join(lines)


# ─── HTML renderer ──────────────────────────────────────────────────────────

TOOLTIP_CSS = """
  .ai-term {
    color: #41488A;
    font-weight: 700;
    border-bottom: 2px dashed #CF512B;
    cursor: pointer;
  }
  #ai-tooltip {
    position: fixed;
    display: none;
    background: #0A111A;
    color: #ffffff;
    font-size: 12px;
    font-weight: 400;
    line-height: 1.5;
    border-radius: 8px;
    padding: 10px 14px;
    border: 1px solid #CF512B;
    box-shadow: 0 4px 20px rgba(10,17,26,0.4);
    max-width: 260px;
    width: 260px;
    z-index: 9999;
    pointer-events: none;
    white-space: normal;
  }
  .fb-btn {
    display: inline-flex;
    align-items: center;
    background: none;
    border: 1px solid #C2CCD5;
    border-radius: 6px;
    color: #888F95;
    cursor: pointer;
    font-size: 12px;
    font-family: Geist, Arial, sans-serif;
    font-weight: 600;
    padding: 5px 10px;
    margin-left: 6px;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }
  .fb-btn:hover { border-color: #CF512B; color: #0A111A; }
  .fb-btn.active-up { background: rgba(207,81,43,0.12); border-color: #CF512B; color: #0A111A; }
  .fb-btn.active-dn { background: rgba(207,81,43,0.12); border-color: #CF512B; color: #41488A; }
  #fb-section textarea {
    width: 100%;
    box-sizing: border-box;
    background: #ffffff;
    border: 1px solid #C2CCD5;
    border-radius: 8px;
    color: #0A111A;
    font-size: 13px;
    font-family: "Geist", Arial, sans-serif;
    line-height: 1.6;
    padding: 12px 14px;
    resize: vertical;
    outline: none;
    transition: border-color 0.15s;
  }
  #fb-section textarea:focus { border-color: #CF512B; }
  #fb-submit {
    margin-top: 10px;
    background: #CF512B;
    border: none;
    border-radius: 8px;
    color: #ffffff;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    font-family: 'Charger', Georgia, 'Times New Roman', serif;
    padding: 10px 22px;
    transition: opacity 0.15s;
  }
  #fb-submit:hover { opacity: 0.85; }
  #fb-thanks {
    display: none;
    margin-top: 10px;
    font-size: 13px;
    color: #41488A;
    font-family: "Geist", Arial, sans-serif;
  }"""

FEEDBACK_SERVER_URL = os.environ.get("FEEDBACK_SERVER_URL", "https://dev-rvelasquez.tailc35de4.ts.net")

# ramsac × Alpha Real brand palette (cream / ink / blue / orange / red / grey).
ACCENT   = "#CF512B"   # red — primary accent
PURPLE   = "#41488A"   # blue — secondary / metadata
BG_MAIN  = "#FAF7E6"   # cream — page surface
BG_CARD  = "#ffffff"   # White — card surface
TEXT     = "#0A111A"   # ink — primary text
MUTED    = "#41488A"   # blue — secondary text
BORDER   = "#C2CCD5"   # grey — hairlines
NAVY     = "#0A111A"   # ink — header/footer
DARK_TEAL = "#0A111A"  # ink — header gradient end
ON_DARK  = "#ffffff"   # Text/accents on dark surfaces

# ramsac × Alpha Real signature gradient: cream → orange → red → grey → blue → ink.
# Used as a thin signature bar.
GRADIENT_BAR = ("linear-gradient(90deg,#FAF7E6 0%,#F0B976 20%,#CF512B 45%,"
                "#C2CCD5 68%,#41488A 85%,#0A111A 100%)")
# Hero treatment: red cooling into blue into ink (white text stays readable).
HERO_GRADIENT = "linear-gradient(150deg,#CF512B 0%,#41488A 52%,#0A111A 100%)"

# Ironbridge "bridge" bracket frames — a solid cream [ / ] with a large
# semicircular arch bitten out of the inner edge (the bridge underside).
# Drawn as a FILLED inline SVG, used as ::before/::after background images.
_BR_TEMPLATE = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 200' "
                "fill='#FAF7E6'><path d='{d}'/></svg>")
# Left bracket: cutout on the right (inner) side; rounded outer corners + arm tips.
_BR_PATH_L = ("M0 10 A10 10 0 0 1 10 0 L90 0 A10 10 0 0 1 100 10 L100 30 "
              "A70 70 0 0 0 100 170 L100 190 A10 10 0 0 1 90 200 L10 200 "
              "A10 10 0 0 1 0 190 Z")
# Right bracket: mirror — cutout on the left (inner) side.
_BR_PATH_R = ("M100 10 A10 10 0 0 0 90 0 L10 0 A10 10 0 0 0 0 10 L0 30 "
              "A70 70 0 0 1 0 170 L0 190 A10 10 0 0 0 10 200 L90 200 "
              "A10 10 0 0 0 100 190 Z")
def _bracket_uri(path):
    svg = _BR_TEMPLATE.format(d=path)
    return 'url("data:image/svg+xml,' + urllib.parse.quote(svg) + '")'
BRACKET_L = _bracket_uri(_BR_PATH_L)
BRACKET_R = _bracket_uri(_BR_PATH_R)

# TP monogram — embedded from tp-logo.png (exact brand asset, white-filtered for dark backgrounds)
TP_MARK = (
    '<img src="data:image/png;base64,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" width="24" height="26" style="display:inline-block;vertical-align:middle;flex-shrink:0;filter:brightness(0) invert(1)" alt="Thought Provoked">'
)

# Plain thumb icons (not emoji) for the relevance-feedback buttons.
THUMB_UP_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" '
    'style="vertical-align:-2px;margin-right:5px"><path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32'
    'c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-'
    '7.05c.09-.23.14-.47.14-.73v-2z"/></svg>'
)
THUMB_DOWN_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" '
    'style="vertical-align:-2px;margin-right:5px"><path d="M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47'
    '-.14.73v2c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5'
    'c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z"/></svg>'
)

# ─── Glossary data ──────────────────────────────────────────────────────────

# Sampled from the ramsac × Alpha Real brand palette — one hue per theme,
# deepened where needed so labels stay readable on the cream background.
CATEGORY_COLORS = {
    "foundation": "#0A111A",   # ink
    "generation": "#CF512B",   # red
    "deployment": "#41488A",   # blue
    "safety":     "#B9793A",   # orange — deepened for legibility
    "business":   "#748094",   # grey — deepened for legibility
}

TERM_CATEGORIES = {
    "ai agent": "deployment",
    "prompt injection": "safety", "multi-agent interaction": "deployment",
    "emergent behaviour": "safety", "frontier model": "foundation",
    "multi-model architectures": "business", "diffusion-based generation": "generation",
    "search-grounding": "deployment", "open-weight model": "foundation",
    "ai agent governance": "business",
    "llm": "foundation", "transformer": "foundation",
    "neural network": "foundation", "context window": "deployment",
    "rag": "deployment", "hallucination": "safety",
    "rlhf": "safety", "multimodal": "generation",
    "agentic workflow": "deployment", "alignment": "safety",
    "autoregressive model": "generation", "copilot": "business",
    # Foundational terms every beginner should learn
    "generative ai": "generation", "prompt": "foundation",
    "prompt engineering": "deployment", "token": "foundation",
    "fine-tuning": "foundation", "inference": "deployment",
    "parameters": "foundation", "embedding": "foundation",
    "vector database": "deployment", "temperature": "generation",
    "system prompt": "deployment", "chain-of-thought": "generation",
    "reasoning model": "foundation", "guardrails": "safety",
    "few-shot learning": "foundation", "knowledge cutoff": "safety",
    "agi": "foundation", "mixture of experts": "foundation",
    "distillation": "foundation", "quantization": "deployment",
    "bias": "safety",
}

GLOSSARY_SEED_TERMS = [
    {"term": "LLM", "definition": "Large Language Model. An AI trained on vast amounts of text that can understand and generate human language. Think of it as an extremely well-read assistant that has absorbed billions of documents and can write, summarise, answer questions, and hold a conversation."},
    {"term": "Transformer", "definition": "The architecture that powers most modern AI models. Invented by Google in 2017, it lets AI process entire paragraphs at once and understand how words relate to each other, rather than reading one word at a time. It is the engine inside GPT, Claude, Gemini, and nearly every other AI you use today."},
    {"term": "Neural Network", "definition": "The basic building block of modern AI. Loosely inspired by the human brain, it is a layered system that learns patterns by adjusting millions of tiny connections based on examples. Train it on enough data and it learns to recognise faces, translate languages, or generate code."},
    {"term": "Context Window", "definition": "The maximum amount of text an AI can see and work with at one time. Think of it like the AI's short-term memory. A small context window limits the AI to a few pages; a large one can handle an entire book. Bigger context windows mean the AI can work on longer, more complex tasks."},
    {"term": "RAG", "definition": "Retrieval-Augmented Generation. A technique where an AI first searches a database of documents to find relevant information, then writes its answer based on what it found. This stops the AI from making things up and keeps answers grounded in your actual company data."},
    {"term": "Hallucination", "definition": "When an AI confidently states something that is factually wrong. Like a student who does not know the answer but writes something plausible-sounding anyway. Hallucination is one of the main risks of using AI output without human review."},
    {"term": "RLHF", "definition": "Reinforcement Learning from Human Feedback. A training method where humans rate the AI's responses as good or bad, and the AI learns to produce more of what got positive ratings. This is how ChatGPT and Claude became helpful and conversational."},
    {"term": "Multimodal", "definition": "An AI that can work with more than one type of input or output, such as text, images, audio, and video. A multimodal model can describe a photograph, read a chart, listen to a voice recording, or analyse a document without switching tools."},
    {"term": "Agentic workflow", "definition": "A process where an AI takes a series of actions over time to complete a goal, rather than just answering a single question. An AI told to book a meeting might check calendars, draft an email, send it, and update a spreadsheet, all without needing a human to prompt every step."},
    {"term": "Alignment", "definition": "The challenge of making AI systems do what humans actually want, safely and reliably. An aligned AI follows instructions without harmful side effects, respects rules, and does not pursue goals that conflict with human values. It is the difference between a helpful assistant and an unpredictable one."},
    {"term": "Autoregressive model", "definition": "An AI that generates text one word at a time, where each word is predicted based on everything that came before it. This is how GPT models work. It is like autocomplete on your phone, but applied thousands of times in sequence at extraordinary speed."},
    {"term": "Generative AI", "definition": "AI that creates brand-new content, whether that's text, images, audio, or code, rather than just sorting or analysing existing data. It is the category that ChatGPT, image generators, and coding assistants all belong to. The 'generative' part means it produces something that did not exist before."},
    {"term": "Prompt", "definition": "The instruction or question you give an AI to tell it what you want. It is simply what you type into the box. The clearer and more specific your prompt, the better the answer you get back."},
    {"term": "Prompt engineering", "definition": "The skill of writing instructions that get the best results from an AI. Small changes in wording can dramatically change the output, so this has become a real craft. It is less about coding and more about clear, structured communication."},
    {"term": "Token", "definition": "The small chunk of text an AI reads and writes, roughly three-quarters of a word. AI does not see whole sentences; it breaks everything into tokens. The number of tokens decides how much you pay and how much the AI can handle at once."},
    {"term": "Fine-tuning", "definition": "Taking a general AI model and training it a little more on your own examples so it gets better at a specific job. Like hiring a capable graduate and then teaching them how your company does things. The result is a model that speaks your language and follows your patterns."},
    {"term": "Inference", "definition": "The moment an AI actually answers, taking your question and turning it into a response. Training is when the model learns, and inference is when it works. Every answer you receive is an act of inference, and it is what costs money to run."},
    {"term": "Parameters", "definition": "The millions or billions of internal dials an AI adjusts as it learns. More parameters generally means the model can capture more complex patterns. When you hear a model is '70 billion parameters', that is a rough measure of its size and capability."},
    {"term": "Embedding", "definition": "A way of turning words, images, or documents into lists of numbers that capture their meaning, so a computer can compare them. Things with similar meaning end up with similar numbers. This is how AI knows that 'car' and 'vehicle' are related."},
    {"term": "Vector database", "definition": "A special kind of storage that holds those number-lists (embeddings) and finds the closest matches fast. It lets an AI search your documents by meaning rather than exact keywords. It is the engine behind most 'chat with your documents' tools."},
    {"term": "Temperature", "definition": "A setting that controls how creative or predictable an AI's output is. Low temperature makes it focused and repeatable; high temperature makes it more varied and surprising. Think of it as a dial between a careful accountant and a free-wheeling brainstormer."},
    {"term": "System prompt", "definition": "Hidden instructions given to an AI before you ever type anything, setting its role, tone, and rules. It is the briefing the AI gets backstage. It is why one chatbot acts like a formal assistant and another like a playful friend."},
    {"term": "Chain-of-thought", "definition": "When an AI works through a problem step by step instead of jumping straight to an answer. Like showing your working in a maths exam, it makes the AI more accurate on hard problems. Many modern models reason this way before they reply."},
    {"term": "Reasoning model", "definition": "A newer kind of AI built to think before it answers, spending extra time working through a problem step by step. It trades speed for accuracy, making it better at maths, coding, and logic. It is the difference between blurting an answer and pausing to reason."},
    {"term": "Guardrails", "definition": "The safety rules and filters built around an AI to stop it producing harmful, false, or off-limits content. Like the barriers on a mountain road, they keep the system from going where it should not. Good guardrails are what make AI safe to put in front of customers."},
    {"term": "Few-shot learning", "definition": "Giving an AI a handful of examples inside your request so it understands the pattern you want. Show it three examples of the format you like, and it copies the style. It is teaching by demonstration, with no retraining needed."},
    {"term": "Knowledge cutoff", "definition": "The date after which an AI knows nothing, because its training data stopped there. Ask about events after the cutoff and it will not know unless it can search the web. It is why an AI sometimes seems frozen in the past."},
    {"term": "AGI", "definition": "Artificial General Intelligence, a hypothetical AI that can do any intellectual task a human can, across every domain. Today's AI is narrow, brilliant at specific things, while AGI would be broadly capable. It is the long-term goal that drives much of the industry."},
    {"term": "Mixture of Experts", "definition": "A model design that splits the work among many specialist sub-models and only wakes the ones it needs for each task. Like a hospital routing you to the right specialist instead of one doctor for everything. It makes very large models faster and cheaper to run."},
    {"term": "Distillation", "definition": "Training a small, fast AI to copy the behaviour of a large, expensive one. The big model is the teacher; the small model is the student that learns to give similar answers at a fraction of the cost. It is how powerful AI gets squeezed onto phones and laptops."},
    {"term": "Quantization", "definition": "Shrinking an AI model by storing its numbers with less precision, so it runs on smaller, cheaper hardware. Like compressing a photo: slightly less detail, far smaller size. It is what lets big models run on a laptop or phone."},
    {"term": "Bias", "definition": "When an AI systematically favours or disadvantages certain groups because of patterns in the data it learned from. If the training data was skewed, the AI inherits that skew. Spotting and reducing bias is central to using AI fairly."},
]

GLOSSARY_EDGES = [
    ["LLM", "Transformer"], ["LLM", "frontier model"], ["LLM", "Context Window"],
    ["LLM", "Hallucination"], ["LLM", "multi-model architectures"],
    ["LLM", "Autoregressive model"],
    ["Transformer", "diffusion-based generation"], ["Transformer", "Autoregressive model"],
    ["AI agent", "Agentic workflow"], ["AI agent", "multi-agent interaction"],
    ["AI agent", "AI agent governance"],
    ["prompt injection", "Hallucination"],
    ["search-grounding", "RAG"],
    ["RAG", "Context Window"],
    ["multi-agent interaction", "emergent behaviour"],
    ["multi-agent interaction", "AI agent governance"],
    ["frontier model", "open-weight model"],
    ["RLHF", "Alignment"], ["RLHF", "frontier model"],
    ["Multimodal", "diffusion-based generation"],
    ["Agentic workflow", "AI agent governance"],
    ["Neural Network", "Transformer"], ["Neural Network", "LLM"],
    # Foundational-term connections
    ["Generative AI", "LLM"], ["Generative AI", "diffusion-based generation"],
    ["Generative AI", "Multimodal"],
    ["Prompt", "Prompt engineering"], ["Prompt", "System prompt"],
    ["Prompt", "Few-shot learning"], ["Prompt", "LLM"],
    ["Prompt engineering", "Few-shot learning"],
    ["Token", "Context Window"], ["Token", "Inference"], ["Token", "LLM"],
    ["Fine-tuning", "Parameters"], ["Fine-tuning", "Distillation"], ["Fine-tuning", "LLM"],
    ["Inference", "Quantization"], ["Inference", "Reasoning model"],
    ["Parameters", "Neural Network"], ["Parameters", "Mixture of Experts"],
    ["Embedding", "Vector database"], ["Embedding", "RAG"], ["Embedding", "Neural Network"],
    ["Vector database", "RAG"],
    ["Temperature", "Hallucination"], ["Temperature", "Generative AI"],
    ["System prompt", "Guardrails"], ["System prompt", "Alignment"],
    ["Chain-of-thought", "Reasoning model"], ["Chain-of-thought", "Agentic workflow"],
    ["Reasoning model", "frontier model"],
    ["Guardrails", "Alignment"], ["Guardrails", "prompt injection"],
    ["Knowledge cutoff", "RAG"], ["Knowledge cutoff", "Hallucination"],
    ["AGI", "frontier model"], ["AGI", "Alignment"],
    ["Mixture of Experts", "multi-model architectures"],
    ["Distillation", "open-weight model"], ["Quantization", "open-weight model"],
    ["Bias", "Alignment"], ["Bias", "RLHF"],
    # Dynamic knowledge-log terms — safe to add; only applied when both nodes exist
    ["computer use", "AI agent"], ["computer use", "Agentic workflow"],
    ["computer use", "Multimodal"],
    ["model cloning", "Distillation"], ["model cloning", "open-weight model"],
    ["model cloning", "frontier model"],
    ["copilot", "multi-model architectures"], ["copilot", "context window"],
    ["latent space", "Embedding"], ["latent space", "diffusion-based generation"],
    ["reinforcement learning", "RLHF"], ["reinforcement learning", "Alignment"],
    ["synthetic data", "Fine-tuning"], ["synthetic data", "Distillation"],
    ["function calling", "AI agent"], ["function calling", "Agentic workflow"],
    ["tool use", "AI agent"], ["tool use", "function calling"],
    ["grounding", "RAG"], ["grounding", "Hallucination"],
    ["model collapse", "Fine-tuning"], ["model collapse", "synthetic data"],
]

# ─── Battle card data ────────────────────────────────────────────────────────

BATTLE_CARDS = [
    {
        "id": "anthropic",
        "name": "Anthropic",
        "product": "Claude",
        "tagline": "Safety-first frontier AI",
        "color": "#CF512B",
        "what_it_is": "Anthropic is an AI safety company founded by former OpenAI researchers. Their flagship product is Claude, a family of AI models (Opus, Sonnet, Haiku) known for being exceptionally safe, accurate, and capable of handling long, complex documents. Claude powers many enterprise AI applications behind the scenes.",
        "key_products": ["Claude Opus (most capable)", "Claude Sonnet (balanced)", "Claude Haiku (fastest, cheapest)"],
        "strengths": ["Highest-rated for accuracy and instruction-following", "Best-in-class for long document analysis", "Strong safety record with enterprise clients", "Excellent at coding and technical reasoning"],
        "watch_out": "Available primarily via API, with no standalone consumer app that's seen wide adoption yet. Anthropic focuses on the model layer, not the application layer.",
        "ramsac_angle": "Claude is one of the models we can deploy and wrap for clients. Because we are model-agnostic, we can use Anthropic's strengths in accuracy, safety, and long context for the right use cases without locking clients into a single vendor.",
        "related_terms": ["frontier model", "AI agent", "Context Window", "Alignment", "RLHF"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "product": "ChatGPT / GPT-4o",
        "tagline": "The brand that made AI mainstream",
        "color": "#41488A",
        "what_it_is": "OpenAI created ChatGPT, the product that brought AI to 200 million users. Their GPT-4o model powers ChatGPT and is embedded in thousands of third-party products. OpenAI also makes Codex (code generation), DALL-E (images), and Operator (web browsing agent).",
        "key_products": ["ChatGPT (consumer + enterprise)", "GPT-4o API", "Codex (coding)", "Operator (agentic web browsing)"],
        "strengths": ["Largest user base and brand recognition", "Strong ecosystem of integrations", "Broad multimodal capability (text, images, audio, video)", "Fastest at shipping new features"],
        "watch_out": "Quality can be inconsistent across versions. Microsoft has exclusive cloud rights, meaning Azure OpenAI Service is the enterprise path, which ties clients to Microsoft pricing and infrastructure.",
        "ramsac_angle": "Most clients will already have heard of ChatGPT. We can build on that familiarity while offering something they cannot get alone: proper deployment, governance, and the ability to switch to a better model when OpenAI is not the right fit.",
        "related_terms": ["LLM", "Multimodal", "Agentic workflow", "Autoregressive model", "frontier model"],
    },
    {
        "id": "microsoft",
        "name": "Microsoft",
        "product": "Copilot / Azure AI",
        "tagline": "AI baked into tools your clients already pay for",
        "color": "#748094",
        "what_it_is": "Microsoft has embedded AI across its entire product stack. Copilot appears in Word, Excel, Outlook, Teams, and SharePoint. Azure OpenAI Service gives enterprises access to GPT-4 through Microsoft's cloud. Copilot Studio lets businesses build custom AI agents without writing code.",
        "key_products": ["Microsoft 365 Copilot (Office AI)", "Azure OpenAI Service", "Copilot Studio (custom agents)", "Security Copilot"],
        "strengths": ["Already inside tools clients pay for, so there's no new vendor to bring in", "Deep integration with M365 data (emails, Teams, SharePoint)", "Enterprise-grade compliance and data residency", "Security Copilot for threat intelligence"],
        "watch_out": "Copilot licensing adds cost on top of existing M365 subscriptions. Some features require specific licence tiers. Privacy and data handling policies have been a concern for regulated industries.",
        "ramsac_angle": "This is our core territory. As an M365 specialist, we are the natural partner for Copilot deployment, governance, and training. We understand which clients are ready, what data needs preparing, and how to get ROI, something Microsoft's own sales team cannot deliver at the SME level.",
        "related_terms": ["Agentic workflow", "search-grounding", "prompt injection", "multi-model architectures"],
    },
    {
        "id": "google",
        "name": "Google / DeepMind",
        "product": "Gemini",
        "tagline": "The multimodal powerhouse",
        "color": "#B9793A",
        "what_it_is": "Google DeepMind develops Gemini, Google's flagship AI model family. Gemini powers Google Search AI, Google Workspace AI (Docs, Gmail, Meet), and Google Cloud AI. DeepMind, Google's research arm, also produces breakthrough research models including AlphaFold.",
        "key_products": ["Gemini Ultra / Pro / Flash", "Google Workspace AI", "NotebookLM (document intelligence)", "Google Cloud Vertex AI"],
        "strengths": ["Best multimodal capabilities (text, image, audio, video, code)", "Deep integration with Google Workspace", "Real-time web search grounding built in", "Strong research pedigree from DeepMind"],
        "watch_out": "Gemini's consumer reputation has suffered from high-profile errors at launch. Enterprise adoption is growing but still behind Microsoft. Google Cloud customers are the natural target, not M365 shops.",
        "ramsac_angle": "Most of our clients are in the Microsoft ecosystem, not Google. But Gemini's multimodal strengths and research pace mean it is a model worth including in any multi-model deployment strategy, especially for image, video, or search-heavy workflows.",
        "related_terms": ["Multimodal", "diffusion-based generation", "frontier model", "search-grounding", "RAG"],
    },
    {
        "id": "xai",
        "name": "xAI",
        "product": "Grok",
        "tagline": "Elon Musk's unfiltered AI",
        "color": "#0A111A",
        "what_it_is": "xAI is Elon Musk's AI company, launched in 2023. Grok is its flagship model, integrated into X (formerly Twitter) and available as a standalone API. Grok 3 is positioned as a frontier model competing directly with GPT-4 and Claude. Aurora is xAI's image generation model.",
        "key_products": ["Grok 3 (frontier model)", "Grok API", "Aurora (image generation)", "X/Twitter integration"],
        "strengths": ["Real-time access to X/Twitter data", "Fewer content restrictions than competitors", "Growing model quality, with Grok 3 benchmarks now competitive", "Strong coding capabilities"],
        "watch_out": "Brand association with Elon Musk and X creates reputational risk for enterprise clients. Data privacy policies are less mature than established providers. Not a natural fit for regulated industries.",
        "ramsac_angle": "Grok is unlikely to be the right choice for our clients in regulated or professional services sectors. Worth knowing about because clients will ask. In a model-agnostic architecture, it could serve specific use cases where real-time social data or fewer content restrictions matter.",
        "related_terms": ["LLM", "frontier model", "open-weight model", "Multimodal"],
    },
    {
        "id": "meta",
        "name": "Meta AI",
        "product": "Llama",
        "tagline": "Open-weight AI anyone can run",
        "color": "#F0B976",
        "what_it_is": "Meta releases its Llama model family as open-weight, meaning anyone can download and run the models on their own hardware. Llama 3 and 3.1 are among the most capable open models available. Meta AI is also the assistant embedded in WhatsApp, Instagram, and Facebook.",
        "key_products": ["Llama 3.x (open-weight models)", "Meta AI (consumer assistant)", "Llama API (hosted inference)"],
        "strengths": ["Open-weight means clients can run models on-premise with no data leaving their environment", "No per-token cost when self-hosted", "Strong community of fine-tuned variants for specific industries", "Competitive quality, especially for code and instruction-following"],
        "watch_out": "Running Llama requires technical infrastructure, and it is not plug-and-play for most SMEs. Meta's consumer products (WhatsApp AI) are separate from enterprise Llama deployments. Meta does not provide enterprise support.",
        "ramsac_angle": "Llama is the clearest illustration of why model-agnostic matters. Some clients in legal, finance, or healthcare need AI that never touches an external server. We can deploy Llama on the client's own infrastructure, something no single-vendor AI provider will ever offer.",
        "related_terms": ["open-weight model", "LLM", "frontier model"],
    },
]


def story_number_badge(n):
    return (
        f'<td width="48" valign="top" style="padding:0 14px 0 0">'
        f'<div style="width:36px;height:36px;border-radius:50%;background:#CF512B;'
        f'text-align:center;line-height:36px;font-size:15px;font-weight:700;color:#ffffff;font-family:\'Charger\',Georgia,\'Times New Roman\',serif">'
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
                    <p onclick="openModal('{modal_id}')" style="margin:0;font-size:15px;font-weight:700;color:{NAVY};font-family:'Charger',Georgia,'Times New Roman',serif;line-height:1.3;cursor:pointer">{story['title']} <span style="font-size:11px;color:{ACCENT};opacity:0.8">&#8599;</span></p>
                  </td>
                </tr>
                <tr><td colspan="2" style="padding-top:10px">
                  <p style="margin:0;font-size:14px;color:{MUTED};font-family:Geist,Arial,sans-serif;line-height:1.6">{story['glance']}</p>
                </td></tr>
                <tr><td colspan="2" style="padding-top:10px;text-align:right">
                  <button class="fb-btn" id="up-{n}" onclick="vote({n},'up')" title="Relevant" aria-label="Relevant">{THUMB_UP_SVG}Relevant</button>
                  <button class="fb-btn" id="dn-{n}" onclick="vote({n},'dn')" title="Not relevant" aria-label="Not relevant">{THUMB_DOWN_SVG}Not relevant</button>
                </td></tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def story_modal(n, story):
    modal_id = f"modal-{n}"
    bullets_html = "".join(
        f'<li style="margin-bottom:10px;font-size:14px;color:{TEXT};font-family:Geist,Arial,sans-serif;line-height:1.6">{b}</li>'
        for b in story.get("bullets", [])
    )
    read_original = ""
    if story.get("url"):
        read_original = (
            f'<a class="modal-link-btn" href="{story["url"]}" target="_blank" rel="noopener">'
            f'Read original &#8599;</a>'
        )
    source_html = story['source']
    if story.get("url"):
        source_html = (
            f'<a href="{story["url"]}" target="_blank" rel="noopener" '
            f'style="color:inherit;text-decoration:none">{story["source"]}</a>'
        )
    return f"""
<div id="{modal_id}" class="modal" onclick="if(event.target===this)closeModal('{modal_id}')">
  <div class="modal-content">
    <button class="modal-close" onclick="closeModal('{modal_id}')">&times;</button>
    <div class="mflip" id="mflip-{n}">
      <div class="mflip-inner">
        <div class="mflip-face mflip-front">
          <p style="margin:0 0 8px 0;font-size:11px;color:{ACCENT};font-family:'Charger',Georgia,'Times New Roman',serif;text-transform:uppercase;letter-spacing:0.12em;font-weight:600">{source_html}</p>
          <h2 style="margin:0 0 20px 0;font-size:20px;font-weight:700;color:{NAVY};font-family:'Charger',Georgia,'Times New Roman',serif;line-height:1.3">{story['title']}</h2>
          <ul style="margin:0;padding-left:20px">{bullets_html}</ul>
          <div class="modal-actions">
            <button class="modal-action-btn" onclick="flipModal('mflip-{n}')">ramsac angle &rarr;</button>
            {read_original}
          </div>
        </div>
        <div class="mflip-face mflip-back">
          <span class="scard-tag">ramsac angle</span>
          <p>{story.get('ramsac_angle', '')}</p>
          <div class="modal-actions">
            <button class="modal-action-btn" onclick="flipModal('mflip-{n}')">&larr; Back to story</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>"""


def section_header(title, icon):
    return f"""
    <tr>
      <td style="padding:0 0 20px 0">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td style="border-top:1px solid {BORDER};padding-top:28px">
              <p style="margin:0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:{ACCENT};font-family:'Charger',Georgia,'Times New Roman',serif;font-weight:700">{title}</p>
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
<html lang="en" style="color-scheme:light only;background-color:#FAF7E6">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light only">
<title>{data['subject']}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
@font-face{{font-family:'Charger';src:url('fonts/ChargerV2Condensed.ttf') format('truetype');font-weight:400;font-display:swap}}
  :root {{ color-scheme: light only; }}
  html {{ background-color: #FAF7E6 !important; }}
  body {{ background-color: #FAF7E6 !important; color: #0A111A !important; }}
  .dh-bracket {{ position: relative; }}
  .dh-bracket::before, .dh-bracket::after {{ content: ''; position: absolute; top: 50%; transform: translateY(-50%); height: 60px; width: 34px; pointer-events: none; background-repeat: no-repeat; background-position: center; background-size: 100% 100%; }}
  .dh-bracket::before {{ left: 14px; background-image: {BRACKET_L}; }}
  .dh-bracket::after {{ right: 14px; background-image: {BRACKET_R}; }}
{TOOLTIP_CSS}
  .modal {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(10,17,26,0.6);
    z-index: 1000;
    align-items: center;
    justify-content: center;
    padding: 16px;
  }}
  .modal.active {{ display: flex; }}
  .modal-content {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 32px;
    max-width: 600px;
    width: 100%;
    max-height: 80vh;
    overflow-y: auto;
    position: relative;
    box-shadow: 0 20px 48px -12px rgba(10,17,26,0.3);
  }}
  .modal-close {{
    position: absolute;
    top: 14px;
    right: 18px;
    background: none;
    border: none;
    color: #888F95;
    font-size: 26px;
    cursor: pointer;
    line-height: 1;
  }}
  .modal-close:hover {{ color: {TEXT}; }}
  .mflip {{ perspective: 1600px; }}
  .mflip-inner {{
    position: relative;
    transition: transform 0.55s cubic-bezier(.22,.61,.36,1);
    transform-style: preserve-3d;
  }}
  .mflip.flipped .mflip-inner {{ transform: rotateY(180deg); }}
  .mflip-face {{ backface-visibility: hidden; -webkit-backface-visibility: hidden; }}
  .mflip-front {{ position: relative; }}
  .mflip-back {{
    position: absolute;
    inset: 0;
    transform: rotateY(180deg);
    background: #F6E6D3;
    border: 1.5px solid {ACCENT};
    border-radius: 10px;
    padding: 24px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    overflow-y: auto;
  }}
  .scard-tag {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-family: 'Charger', Georgia, 'Times New Roman', serif;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: {ACCENT};
    margin-bottom: 10px;
  }}
  .scard-tag::before {{ content: ''; width: 16px; height: 2px; background: {ACCENT}; display: inline-block; }}
  .mflip-back p {{ margin: 0; font-size: 14px; color: {TEXT}; font-family: Geist, Arial, sans-serif; line-height: 1.6; }}
  .modal-actions {{ display: flex; gap: 10px; margin-top: 18px; flex-wrap: wrap; }}
  .modal-action-btn, .modal-link-btn {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: none;
    cursor: pointer;
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {ACCENT};
    font-family: 'Charger', Georgia, 'Times New Roman', serif;
    font-size: 12px;
    font-weight: 700;
    padding: 8px 14px;
    text-decoration: none;
    transition: border-color 0.15s, background 0.15s;
  }}
  .modal-action-btn:hover, .modal-link-btn:hover {{ border-color: {ACCENT}; background: rgba(207,81,43,0.08); }}
</style>
</head>
<body style="margin:0;padding:0;background-color:#FAF7E6 !important;font-family:Geist,Arial,Helvetica,sans-serif;color:#0A111A !important">

<!-- Outer wrapper -->
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#FAF7E6;min-height:100vh">
<tr><td align="center" style="padding:32px 16px">

<!-- Back to hub -->
<table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%">
  <tr><td style="padding:0 0 16px 0">
    <a href="index.html" style="display:inline-block;background:{BG_CARD};border:1px solid {BORDER};color:{ACCENT};font-family:'Charger',Georgia,'Times New Roman',serif;font-size:12px;font-weight:700;text-decoration:none;padding:9px 16px;border-radius:8px">&larr; Back to Hub</a>
  </td></tr>
</table>

<!-- Email container -->
<table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%">

  <!-- ── HEADER: fixed masthead (date, title, brand) ── -->
  <tr>
    <td class="dh-bracket" style="background:{HERO_GRADIENT};border-radius:12px 12px 0 0;padding:36px 72px 28px">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td>
            <p style="margin:0 0 8px 0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#ffffff;font-family:'Charger',Georgia,'Times New Roman',serif;font-weight:600">{today}</p>
            <h1 style="margin:0;font-size:28px;font-weight:800;color:#ffffff;font-family:'Charger',Georgia,'Times New Roman',serif;line-height:1.2">
              <span style="color:#ffffff;border-bottom:3px solid #CF512B;padding-bottom:2px">This Week</span> in AI
            </h1>
          </td>
          <td width="180" align="right" valign="middle" style="text-align:right">
            <div style="display:inline-flex;align-items:center;gap:8px">
              {TP_MARK}
              <span style="font-size:16px;font-weight:800;color:#ffffff;font-family:'Charger',Georgia,'Times New Roman',serif;letter-spacing:-0.02em;white-space:nowrap">Thought Provoked</span>
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- ── THIS EDITION'S HEADLINE: changes every week ── -->
  <tr>
    <td style="background:{BG_CARD};padding:20px 32px;border-left:1px solid {BORDER};border-right:1px solid {BORDER};border-top:3px solid {ACCENT}">
      <p style="margin:0 0 6px 0;font-size:10px;letter-spacing:0.14em;text-transform:uppercase;color:{ACCENT};font-family:'Charger',Georgia,'Times New Roman',serif;font-weight:700">This week</p>
      <p style="margin:0;font-size:17px;font-weight:600;color:{TEXT};font-family:Geist,Arial,sans-serif;line-height:1.5">{data['intro']}</p>
    </td>
  </tr>

  <!-- ── metal-heat gradient bar ── -->
  <tr><td style="height:4px;line-height:4px;font-size:0;background:{GRADIENT_BAR}">&nbsp;</td></tr>

  <!-- ── BODY ── -->
  <tr>
    <td style="background:{BG_MAIN};padding:28px 32px 8px;border-left:1px solid {BORDER};border-right:1px solid {BORDER}">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">

        {section_header("Top 5 at a Glance (click a title for the full story)", "")}
        {glance_rows}
        {terms_section}

      </table>
    </td>
  </tr>

  <!-- ── FEEDBACK ── -->
  <tr>
    <td id="fb-section" style="background:{BG_MAIN};padding:24px 32px 32px;border-left:1px solid {BORDER};border-right:1px solid {BORDER};border-top:1px solid {BORDER}">
      <p style="margin:0 0 10px 0;font-size:14px;font-weight:600;color:{MUTED};font-family:'Charger',Georgia,'Times New Roman',serif">How can we make this more useful?</p>
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
            <p style="margin:0 0 4px 0;font-size:15px;font-weight:700;color:#ffffff;font-family:'Charger',Georgia,'Times New Roman',serif">Stay curious, stay ahead.</p>
            <p style="margin:0;font-size:13px;color:rgba(255,255,255,0.6);font-family:Geist,Arial,sans-serif">See you next week.</p>
          </td>
          <td align="right">
            <div style="display:inline-flex;align-items:center;gap:8px">
              {TP_MARK}
              <div style="text-align:left">
                <p style="margin:0;font-size:16px;font-weight:800;color:#ffffff;font-family:'Charger',Georgia,'Times New Roman',serif;letter-spacing:-0.02em;white-space:nowrap">Thought Provoked</p>
                <p style="margin:2px 0 0 0;font-size:10px;color:rgba(255,255,255,0.4);font-family:Geist,Arial,sans-serif">Weekly AI Briefing</p>
              </div>
            </div>
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
    var m = document.getElementById(id);
    m.classList.remove('active');
    document.body.style.overflow = '';
    var mflip = m.querySelector('.mflip');
    if (mflip) mflip.classList.remove('flipped');
  }}
  function flipModal(id) {{
    document.getElementById(id).classList.toggle('flipped');
  }}
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{
      document.querySelectorAll('.modal.active').forEach(function(m) {{
        closeModal(m.id);
      }});
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
      el.addEventListener('click', function() {{
        tip.style.display = 'none';
        var term = el.getAttribute('data-term') || el.textContent;
        window.open('glossary.html?focus=' + encodeURIComponent(term), '_blank');
      }});
    }});
  }})();
</script>
</body>
</html>"""


# ─── Shared nav helpers ─────────────────────────────────────────────────────

def _nav_css():
    return f"""
  .site-nav {{ background: {NAVY}; padding: 0 24px; display: flex; align-items: center; gap: 0; position: relative; z-index: 10; }}
  .nav-brand {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 16px; font-weight: 800; color: {ON_DARK}; letter-spacing: -0.02em; padding: 14px 20px 14px 0; border-right: 1px solid rgba(255,255,255,0.1); margin-right: 4px; white-space: nowrap; }}
  .nav-link {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.6); padding: 14px 16px; text-transform: uppercase; letter-spacing: 0.08em; transition: color 0.15s; border-bottom: 3px solid transparent; margin-bottom: -3px; }}
  .nav-link:hover {{ color: #fff; }}
  .nav-link.active {{ color: {ON_DARK}; border-bottom-color: {ACCENT}; }}
  .nav-build {{ margin-left: auto; font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: rgba(255,255,255,0.4); white-space: nowrap; }}
  .austen-name {{ position: relative; color: rgba(255,255,255,0.75); font-weight: 800; letter-spacing: 0.06em; cursor: help; }}
  .austen-name::after {{ content: "Named after Jane Austen, English novelist of Pride and Prejudice and Emma. She had a rare gift for making complicated worlds feel clear, urgent, and readable. That is exactly what this digest tries to do for AI."; position: absolute; top: calc(100% + 8px); right: 0; background: {NAVY}; color: {BG_MAIN}; padding: 12px 16px; border-radius: 10px; font-size: 12px; font-weight: 400; line-height: 1.6; width: 260px; white-space: normal; opacity: 0; pointer-events: none; transition: opacity 0.2s; border: 1px solid {ACCENT}; box-shadow: 0 6px 24px rgba(10,17,26,0.5); z-index: 9999; text-transform: none; letter-spacing: 0; }}
  .austen-name:hover::after {{ opacity: 1; }}
  /* Ironbridge "iron is never one colour" gradient bar */
  .brand-bar {{ height: 4px; width: 100%; background: {GRADIENT_BAR}; }}
  /* hairline divider */
  .hairline {{ height: 1px; background: {BORDER}; border: none; margin: 0; }}
  /* outlined pill tag */
  .pill {{ display: inline-block; font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: {ACCENT}; border: 1px solid {ACCENT}; border-radius: 999px; padding: 4px 13px; }}
  .pill-light {{ border-color: rgba(250,247,230,0.5); color: {ON_DARK}; }}
  /* eyebrow row: pill on the left, counter on the right */
  .eyebrow-row {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
  .eyebrow-count {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: {MUTED}; }}
  /* bridge-arch bracket frame: cream [ ] with a semicircular arch, on hero sides */
  .bracket {{ position: relative; }}
  .bracket::before, .bracket::after {{ content: ''; position: absolute; top: 50%; transform: translateY(-50%); height: 72px; width: 40px; pointer-events: none; background-repeat: no-repeat; background-position: center; background-size: 100% 100%; }}
  .bracket::before {{ left: 18px; background-image: {BRACKET_L}; }}
  .bracket::after {{ right: 18px; background-image: {BRACKET_R}; }}"""


def _nav_html(active):
    links = [
        ("index.html", "Digest"),
        ("glossary.html", "Glossary"),
    ]
    items = ""
    for href, label in links:
        cls = "nav-link active" if label.lower().replace(" ", "") == active.lower().replace(" ", "") else "nav-link"
        items += f'<a href="{href}" class="{cls}">{label}</a>'
    brand = (f'<a href="https://thoughtprovoked.co.uk" target="_blank" rel="noopener" '
             f'class="nav-brand" style="display:flex;align-items:center;gap:7px">'
             f'{TP_MARK}<span>Thought Provoked</span></a>')
    return f'<nav class="site-nav">{brand}{items}<span class="nav-build"><span class="austen-name">Austen</span></span></nav><div class="brand-bar"></div>'


# ─── Glossary constellation renderer ────────────────────────────────────────

def render_glossary_html(knowledge_log):
    # Merge seed terms with knowledge_log — knowledge_log takes priority for definitions
    kl_terms = {t["term"].lower(): t for t in knowledge_log.get("terms", [])}
    all_nodes = {}

    def _cap(s):
        """Capitalise first letter only, preserving the rest (LLM stays LLM, RAG stays RAG)."""
        return (s[0].upper() + s[1:]) if s else s

    for seed in GLOSSARY_SEED_TERMS:
        key = seed["term"].lower()
        if key in kl_terms:
            t = kl_terms[key]
            all_nodes[key] = {"label": _cap(t["term"]), "definition": t["definition"],
                               "category": TERM_CATEGORIES.get(key, "foundation"), "from_log": True}
        else:
            all_nodes[key] = {"label": _cap(seed["term"]), "definition": seed["definition"],
                               "category": TERM_CATEGORIES.get(key, "foundation"), "from_log": False}

    for t in knowledge_log.get("terms", []):
        key = t["term"].lower()
        if key not in all_nodes:
            all_nodes[key] = {"label": _cap(t["term"]), "definition": t["definition"],
                               "category": TERM_CATEGORIES.get(key, "business"), "from_log": True}

    nodes_list = list(all_nodes.values())
    label_to_idx = {n["label"].lower(): i for i, n in enumerate(nodes_list)}

    valid_edges = []
    for a, b in GLOSSARY_EDGES:
        ia = label_to_idx.get(a.lower())
        ib = label_to_idx.get(b.lower())
        if ia is not None and ib is not None:
            valid_edges.append([ia, ib])

    # Build battle card linkage
    bc_map = {}
    for card in BATTLE_CARDS:
        for t in card["related_terms"]:
            key = t.lower()
            if key not in bc_map:
                bc_map[key] = []
            bc_map[key].append({"name": card["name"], "id": card["id"]})

    for n in nodes_list:
        n["battlecards"] = bc_map.get(n["label"].lower(), [])

    nodes_json = json.dumps(nodes_list)
    edges_json = json.dumps(valid_edges)
    cat_colors_json = json.dumps(CATEGORY_COLORS)
    nav = _nav_html("glossary")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Austen</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
@font-face{{font-family:'Charger';src:url('fonts/ChargerV2Condensed.ttf') format('truetype');font-weight:400;font-display:swap}}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {BG_MAIN}; font-family: Geist, Arial, sans-serif; color: {TEXT}; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
  a {{ color: inherit; text-decoration: none; }}
  {_nav_css()}
  .workspace {{ display: flex; flex: 1; overflow: hidden; }}
  .graph-col {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }}
  .toolbar {{ display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: {BG_CARD}; border-bottom: 1px solid {BORDER}; flex-shrink: 0; }}
  .search-wrap {{ position: relative; flex: 1; max-width: 300px; }}
  .search-wrap input {{ width: 100%; padding: 8px 12px 8px 32px; border: 1px solid {BORDER}; border-radius: 20px; font-size: 13px; font-family: Geist, Arial, sans-serif; outline: none; color: {TEXT}; background: {BG_MAIN}; transition: border-color 0.15s; }}
  .search-wrap input:focus {{ border-color: {ACCENT}; }}
  .search-icon {{ position: absolute; left: 10px; top: 50%; transform: translateY(-50%); font-size: 13px; opacity: 0.5; pointer-events: none; }}
  .legend-intro {{ font-size: 11px; color: {MUTED}; font-family: Geist, Arial, sans-serif; margin-right: 4px; align-self: center; }}
  .legend {{ display: flex; gap: 14px; flex-wrap: wrap; }}
  .legend-item {{ display: flex; align-items: flex-start; gap: 6px; cursor: pointer; transition: opacity 0.15s; }}
  .legend-dot {{ width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; margin-top: 2px; }}
  .legend-text {{ display: flex; flex-direction: column; line-height: 1.25; }}
  .legend-name {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: {NAVY}; font-family: 'Charger', Georgia, 'Times New Roman', serif; }}
  .legend-desc {{ font-size: 10px; color: {MUTED}; font-family: Geist, Arial, sans-serif; white-space: nowrap; }}
  .trending-bar {{ font-size: 11px; color: {MUTED}; display: flex; align-items: center; gap: 6px; flex-shrink: 0; }}
  .trending-bar span {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: {ACCENT}; }}
  .trending-chip {{ display: inline-block; background: rgba(207,81,43,0.1); color: {NAVY}; border-radius: 12px; padding: 2px 9px; font-size: 11px; cursor: pointer; border: 1px solid rgba(207,81,43,0.3); }}
  .trending-chip:hover {{ background: {ACCENT}; color: {ON_DARK}; }}
  #graph-svg {{ flex: 1; width: 100%; display: block; cursor: grab; }}
  #graph-svg:active {{ cursor: grabbing; }}
  .detail-col {{ width: 320px; flex-shrink: 0; border-left: 1px solid {BORDER}; background: {BG_CARD}; display: flex; flex-direction: column; overflow: hidden; }}
  .detail-empty {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 32px; text-align: center; opacity: 0.5; }}
  .detail-empty .hint-icon {{ font-size: 36px; margin-bottom: 12px; }}
  .detail-empty p {{ font-size: 13px; color: {MUTED}; line-height: 1.6; }}
  .detail-content {{ flex: 1; overflow-y: auto; padding: 28px 24px; display: none; }}
  .detail-category {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 700; margin-bottom: 8px; }}
  .detail-term {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 22px; font-weight: 800; color: {NAVY}; margin-bottom: 16px; line-height: 1.2; }}
  .detail-def {{ font-size: 14px; line-height: 1.75; color: {TEXT}; margin-bottom: 24px; }}
  .detail-section-label {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: {ACCENT}; font-weight: 700; margin-bottom: 8px; border-top: 1px solid {BORDER}; padding-top: 16px; }}
  .related-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .related-chip {{ display: inline-block; background: {BG_MAIN}; border: 1px solid {BORDER}; border-radius: 16px; padding: 4px 12px; font-size: 12px; font-family: 'Charger', Georgia, 'Times New Roman', serif; font-weight: 600; cursor: pointer; transition: all 0.15s; }}
  .related-chip:hover {{ border-color: {ACCENT}; background: rgba(207,81,43,0.1); }}
  .bc-link {{ display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: {BG_MAIN}; border: 1px solid {BORDER}; border-radius: 8px; margin-bottom: 8px; font-size: 13px; font-weight: 600; color: {NAVY}; font-family: 'Charger', Georgia, 'Times New Roman', serif; transition: border-color 0.15s; }}
  .bc-link:hover {{ border-color: {ACCENT}; }}
  .bc-link-arrow {{ margin-left: auto; color: {ACCENT}; }}
  .back-hub-btn {{ display: inline-flex; align-items: center; gap: 6px; background: transparent; border: 1px solid {BORDER}; border-radius: 20px; padding: 6px 14px; font-size: 12px; font-weight: 700; font-family: 'Charger', Georgia, 'Times New Roman', serif; color: {NAVY}; letter-spacing: 0.04em; transition: border-color 0.15s, background 0.15s; white-space: nowrap; flex-shrink: 0; }}
  .back-hub-btn:hover {{ border-color: {ACCENT}; background: rgba(207,81,43,0.08); color: {ACCENT}; }}
  .shuffle-btn {{ position: absolute; bottom: 20px; right: 20px; display: inline-flex; align-items: center; gap: 8px; background: {ACCENT}; color: {ON_DARK}; border: none; border-radius: 24px; padding: 10px 20px; font-size: 13px; font-weight: 700; font-family: 'Charger', Georgia, 'Times New Roman', serif; letter-spacing: 0.04em; cursor: pointer; box-shadow: 0 4px 16px rgba(207,81,43,0.35); transition: opacity 0.15s, transform 0.15s; z-index: 10; }}
  .shuffle-btn:hover {{ opacity: 0.88; transform: scale(1.04); }}
  .shuffle-btn:active {{ transform: scale(0.97); }}
  .proximity-note {{ position: absolute; bottom: 20px; left: 20px; max-width: 280px; display: flex; align-items: flex-start; gap: 7px; font-size: 11px; line-height: 1.45; color: {MUTED}; font-family: Geist, Arial, sans-serif; background: rgba(250,247,230,0.82); backdrop-filter: blur(2px); border: 1px solid {BORDER}; border-left: 3px solid {ACCENT}; border-radius: 8px; padding: 8px 11px; z-index: 10; pointer-events: none; }}
  .proximity-note b {{ color: {NAVY}; font-weight: 700; }}
</style>
</head>
<body>
{nav}
<div class="workspace">
  <div class="graph-col">
    <div class="toolbar">
      <a href="index.html" class="back-hub-btn">&#8592; Back to Hub</a>
      <div class="search-wrap">
        <span class="search-icon">&#128269;</span>
        <input type="text" id="search-input" placeholder="Search concepts..." autocomplete="off">
      </div>
    </div>
    <div class="toolbar" style="padding-top:10px;padding-bottom:10px;border-top:none;align-items:flex-start;flex-wrap:wrap;gap:14px">
      <span class="legend-intro">Colour marks one of 5 themes &mdash; click a theme to filter:</span>
      <div class="legend" id="legend"></div>
    </div>
    <div class="toolbar" style="padding-top:8px;padding-bottom:8px;border-top:none">
      <div class="trending-bar" id="trending-bar"><span class="pill">Trending</span><span id="trending-chips" style="display:flex;gap:6px"></span></div>
    </div>
    <svg id="graph-svg"></svg>
    <div class="proximity-note">&#9737;&nbsp;<span><b>This map reflects conceptual proximity.</b> This is a visual representation of how an LLM understands meaning: it represents every idea as a vector, a list of numbers, and concepts it treats as related end up with vectors that sit closer together. Distance here mirrors that same closeness.</span></div>
    <button class="shuffle-btn" id="shuffle-btn" title="Pick a random concept">&#9654; Shuffle</button>
  </div>
  <div class="detail-col">
    <div class="detail-empty" id="detail-empty">
      <div class="hint-icon">&#10024;</div>
      <p>Click any concept to explore its definition and connections.</p>
    </div>
    <div class="detail-content" id="detail-content">
      <div class="detail-category" id="d-cat"></div>
      <div class="detail-term" id="d-term"></div>
      <div class="detail-def" id="d-def"></div>
      <div id="d-related-wrap" style="display:none">
        <div class="detail-section-label">Related concepts</div>
        <div class="related-chips" id="d-related"></div>
      </div>
    </div>
  </div>
</div>
<script>
(function() {{
  var NODES = {nodes_json};
  var EDGES = {edges_json};
  var CAT_COLORS = {cat_colors_json};
  var SEARCH_URL = "{FEEDBACK_SERVER_URL}";
  var POPULARITY = {{
    'llm': 5, 'generative ai': 5, 'hallucination': 5, 'agi': 5,
    'prompt': 4, 'ai agent': 4, 'frontier model': 4, 'reasoning model': 4,
    'rag': 4, 'multimodal': 4, 'agentic workflow': 4, 'alignment': 4,
    'context window': 3, 'neural network': 3, 'transformer': 3,
    'fine-tuning': 3, 'embedding': 3, 'open-weight model': 3,
    'diffusion-based generation': 3, 'multi-model architectures': 3,
    'prompt injection': 3, 'bias': 3, 'rlhf': 3,
    'computer use': 2, 'model cloning': 2, 'distillation': 2, 'quantization': 2
  }};
  // Semantic-proximity clustering: rather than snapping categories to fixed
  // screen zones, each node is pulled toward the LIVE centroid of its category
  // (a coarse semantic prior) while edges pull specifically-related concepts
  // together (fine semantic structure). Clusters therefore emerge from actual
  // relationships, like a projected vector space, instead of arbitrary bins.
  var CLUSTER_FORCE = 0.014;

  var svg = document.getElementById('graph-svg');
  var W, H;
  var simNodes = [], simEdges = [];
  var dragging = null, dragOffX = 0, dragOffY = 0;
  var activeIdx = -1;
  var filterCat = null;
  var searchQuery = '';

  function resize() {{
    W = svg.clientWidth; H = svg.clientHeight;
  }}

  function initNodes() {{
    var n = NODES.length;
    simNodes = NODES.map(function(nd, i) {{
      var angle = (2 * Math.PI * i / n) - Math.PI / 2;
      var r = Math.min(W, H) * 0.28;
      return {{ x: W/2 + r * Math.cos(angle), y: H/2 + r * Math.sin(angle),
               vx: 0, vy: 0, data: nd, idx: i }};
    }});
    simEdges = EDGES.map(function(e) {{ return {{ s: e[0], t: e[1] }}; }});
    // Auto-connect isolated nodes — ensure every node has at least one edge
    var nodeDeg = new Array(simNodes.length).fill(0);
    simEdges.forEach(function(e) {{ nodeDeg[e.s]++; nodeDeg[e.t]++; }});
    simNodes.forEach(function(n, i) {{
      if (nodeDeg[i] > 0) return;
      var bestJ = -1, bestDist = Infinity;
      simNodes.forEach(function(m, j) {{
        if (j === i) return;
        if (m.data.category === n.data.category) {{
          var dx = n.x - m.x, dy = n.y - m.y;
          var d = dx*dx + dy*dy;
          if (d < bestDist) {{ bestDist = d; bestJ = j; }}
        }}
      }});
      if (bestJ === -1) simNodes.forEach(function(m, j) {{
        if (j === i) return;
        var dx = n.x - m.x, dy = n.y - m.y;
        var d = dx*dx + dy*dy;
        if (d < bestDist) {{ bestDist = d; bestJ = j; }}
      }});
      if (bestJ !== -1) {{ simEdges.push({{s: i, t: bestJ}}); nodeDeg[i]++; nodeDeg[bestJ]++; }}
    }});
  }}

  var REPULSION = 4200, SPRING_LEN = 175, SPRING_K = 0.02;
  // GRAVITY is the coefficient of a LOGARITHMIC centering pull (see tick).
  // Linear gravity grew with distance and crushed far-apart concepts into the
  // centre; log scaling makes the inward pull near-constant past mid-range so
  // distant concepts keep their spread instead of compressing together.
  var DAMPING = 0.68, GRAVITY = 0.28;  // lower DAMPING = more friction; lower GRAVITY = gentler pull to center

  function tick() {{
    var cx = W/2, cy = H/2;
    for (var i = 0; i < simNodes.length; i++) {{
      for (var j = i+1; j < simNodes.length; j++) {{
        var a = simNodes[i], b = simNodes[j];
        var dx = b.x - a.x, dy = b.y - a.y;
        var dist = Math.sqrt(dx*dx + dy*dy) || 1;
        var f = REPULSION / (dist * dist);
        var fx = f * dx/dist, fy = f * dy/dist;
        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }}
    }}
    for (var k = 0; k < simEdges.length; k++) {{
      var e = simEdges[k];
      var a = simNodes[e.s], b = simNodes[e.t];
      var dx = b.x - a.x, dy = b.y - a.y;
      var dist = Math.sqrt(dx*dx + dy*dy) || 1;
      var f = SPRING_K * (dist - SPRING_LEN);
      var fx = f * dx/dist, fy = f * dy/dist;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }}
    // Live per-category centroids (semantic prior) — recomputed each frame
    var cenX = {{}}, cenY = {{}}, cenN = {{}};
    for (var i = 0; i < simNodes.length; i++) {{
      var c = simNodes[i].data.category;
      if (cenN[c] === undefined) {{ cenX[c] = 0; cenY[c] = 0; cenN[c] = 0; }}
      cenX[c] += simNodes[i].x; cenY[c] += simNodes[i].y; cenN[c]++;
    }}
    for (var c in cenN) {{ cenX[c] /= cenN[c]; cenY[c] /= cenN[c]; }}
    for (var i = 0; i < simNodes.length; i++) {{
      var n = simNodes[i];
      if (n === dragging) continue;
      var gdx = cx - n.x, gdy = cy - n.y;
      var gd = Math.sqrt(gdx*gdx + gdy*gdy) || 1;
      var gpull = GRAVITY * Math.log(1 + gd);  // logarithmic: gentle, near-constant pull at range
      n.vx += gpull * gdx / gd;
      n.vy += gpull * gdy / gd;
      var ncat = n.data.category;  // pull toward live centroid of same-category nodes
      n.vx += (cenX[ncat] - n.x) * CLUSTER_FORCE;
      n.vy += (cenY[ncat] - n.y) * CLUSTER_FORCE;
      n.vx *= DAMPING; n.vy *= DAMPING;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(50, Math.min(W - 50, n.x));
      n.y = Math.max(50, Math.min(H - 50, n.y));
    }}
    render();
    requestAnimationFrame(tick);
  }}

  function nodeVisible(n) {{
    var nd = n.data;
    if (filterCat && nd.category !== filterCat) return false;
    if (searchQuery) {{
      var q = searchQuery.toLowerCase();
      return nd.label.toLowerCase().indexOf(q) >= 0 || nd.definition.toLowerCase().indexOf(q) >= 0;
    }}
    return true;
  }}

  function render() {{
    svg.innerHTML = '';
    var defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    var filter = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
    filter.setAttribute('id', 'glow');
    var feGaussianBlur = document.createElementNS('http://www.w3.org/2000/svg', 'feGaussianBlur');
    feGaussianBlur.setAttribute('stdDeviation', '3'); feGaussianBlur.setAttribute('result', 'coloredBlur');
    var feMerge = document.createElementNS('http://www.w3.org/2000/svg', 'feMerge');
    var feMergeNode1 = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
    feMergeNode1.setAttribute('in', 'coloredBlur');
    var feMergeNode2 = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
    feMergeNode2.setAttribute('in', 'SourceGraphic');
    feMerge.appendChild(feMergeNode1); feMerge.appendChild(feMergeNode2);
    filter.appendChild(feGaussianBlur); filter.appendChild(feMerge);
    defs.appendChild(filter); svg.appendChild(defs);

    // Draw edges
    for (var k = 0; k < simEdges.length; k++) {{
      var e = simEdges[k];
      var a = simNodes[e.s], b = simNodes[e.t];
      if (!nodeVisible(a) || !nodeVisible(b)) continue;
      var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      var isActive = (activeIdx === e.s || activeIdx === e.t);
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
      line.setAttribute('stroke', isActive ? '#CF512B' : '{BORDER}');
      line.setAttribute('stroke-width', isActive ? '2' : '1');
      line.setAttribute('opacity', isActive ? '0.8' : '0.5');
      svg.appendChild(line);
    }}

    // Draw nodes
    for (var i = 0; i < simNodes.length; i++) {{
      var n = simNodes[i]; var nd = n.data;
      var visible = nodeVisible(n);
      var isActive = (activeIdx === i);
      var color = CAT_COLORS[nd.category] || '#888';
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('transform', 'translate(' + n.x + ',' + n.y + ')');
      g.setAttribute('data-idx', i);
      g.style.opacity = visible ? '1' : '0.15';
      g.style.cursor = 'pointer';

      var displayLabel = nd.label.charAt(0).toUpperCase() + nd.label.slice(1);
      var pop = POPULARITY[nd.label.toLowerCase()] || (nd.from_log ? 2 : 1);
      var baseR = 5 + pop * 1.1;
      var r = isActive ? baseR + 3 : baseR;
      if (pop >= 4 && !isActive) {{
        var ring = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        ring.setAttribute('r', r + 5); ring.setAttribute('fill', 'none');
        ring.setAttribute('stroke', color); ring.setAttribute('stroke-width', '1');
        ring.setAttribute('opacity', '0.35'); ring.setAttribute('pointer-events', 'none');
        g.appendChild(ring);
      }}
      var circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('r', r);
      circle.setAttribute('fill', color);
      circle.setAttribute('stroke', isActive ? '#0A111A' : 'rgba(10,17,26,0.22)');
      circle.setAttribute('stroke-width', isActive ? '2.5' : '1.5');
      if (isActive) circle.setAttribute('filter', 'url(#glow)');

      var label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      var onRight = n.x > W * 0.58;
      label.setAttribute('x', onRight ? -(r + 7) : (r + 7));
      label.setAttribute('text-anchor', onRight ? 'end' : 'start');
      label.setAttribute('y', '5');
      label.setAttribute('font-size', isActive ? '14' : (pop >= 4 ? '13' : '11.5'));
      label.setAttribute('font-weight', isActive ? '800' : (pop >= 4 ? '700' : '600'));
      label.setAttribute('font-family', "'Charger', Georgia, 'Times New Roman', serif");
      label.setAttribute('fill', isActive ? '{NAVY}' : '#444');
      label.setAttribute('stroke', '{BG_MAIN}');
      label.setAttribute('stroke-width', '3.5');
      label.setAttribute('paint-order', 'stroke');
      label.setAttribute('pointer-events', 'none');
      label.textContent = displayLabel;

      var hitbox = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      hitbox.setAttribute('r', '20'); hitbox.setAttribute('fill', 'transparent');

      g.appendChild(circle); g.appendChild(label); g.appendChild(hitbox);
      svg.appendChild(g);
    }}
  }}

  function showDetail(idx) {{
    activeIdx = idx;
    var nd = simNodes[idx].data;
    document.getElementById('detail-empty').style.display = 'none';
    var dc = document.getElementById('detail-content');
    dc.style.display = 'block';
    var catEl = document.getElementById('d-cat');
    catEl.textContent = nd.category;
    catEl.style.color = CAT_COLORS[nd.category] || '{ACCENT}';
    document.getElementById('d-term').textContent = nd.label.charAt(0).toUpperCase() + nd.label.slice(1);
    document.getElementById('d-def').textContent = nd.definition;

    var relWrap = document.getElementById('d-related-wrap');
    var relDiv = document.getElementById('d-related');
    relDiv.innerHTML = '';
    var neighbors = [];
    for (var k = 0; k < simEdges.length; k++) {{
      var e = simEdges[k];
      if (e.s === idx) neighbors.push(e.t);
      else if (e.t === idx) neighbors.push(e.s);
    }}
    if (neighbors.length > 0) {{
      relWrap.style.display = 'block';
      neighbors.forEach(function(ni) {{
        var chip = document.createElement('span');
        chip.className = 'related-chip';
        var nl = simNodes[ni].data.label; chip.textContent = nl.charAt(0).toUpperCase() + nl.slice(1);
        chip.style.borderColor = CAT_COLORS[simNodes[ni].data.category] || '{BORDER}';
        chip.addEventListener('click', function() {{ showDetail(ni); }});
        relDiv.appendChild(chip);
      }});
    }} else {{
      relWrap.style.display = 'none';
    }}

  }}

  // Interaction
  svg.addEventListener('mousedown', function(e) {{
    var g = e.target.closest('g[data-idx]');
    if (!g) return;
    var idx = parseInt(g.getAttribute('data-idx'));
    dragging = simNodes[idx];
    var rect = svg.getBoundingClientRect();
    dragOffX = e.clientX - rect.left - dragging.x;
    dragOffY = e.clientY - rect.top - dragging.y;
    dragging._startX = dragging.x; dragging._startY = dragging.y;
    e.preventDefault();
  }});

  svg.addEventListener('mousemove', function(e) {{
    if (!dragging) return;
    var rect = svg.getBoundingClientRect();
    dragging.x = e.clientX - rect.left - dragOffX;
    dragging.y = e.clientY - rect.top - dragOffY;
    dragging.vx = 0; dragging.vy = 0;
  }});

  window.addEventListener('mouseup', function(e) {{
    if (!dragging) return;
    var moved = Math.abs(dragging.x - dragging._startX) + Math.abs(dragging.y - dragging._startY);
    var idx = dragging.idx;
    dragging = null;
    if (moved < 5) showDetail(idx);
  }});

  // Search
  var searchTimer;
  document.getElementById('search-input').addEventListener('input', function(e) {{
    searchQuery = e.target.value.trim();
    clearTimeout(searchTimer);
    if (searchQuery.length >= 2) {{
      searchTimer = setTimeout(function() {{
        logSearch(searchQuery);
      }}, 800);
    }}
  }});

  // Legend
  var CAT_DESC = {{
    foundation: 'The core building blocks of AI',
    generation: 'How AI creates text, images & more',
    deployment: 'Putting AI to work on real tasks',
    safety:     'Risks, attacks & safeguards',
    business:   'Commercial & strategic ideas'
  }};
  var CAT_NAMES = {{
    foundation: 'Foundations', generation: 'Generation', deployment: 'Deployment',
    safety: 'Safety', business: 'Business'
  }};
  var legendEl = document.getElementById('legend');
  Object.keys(CAT_COLORS).forEach(function(cat) {{
    var item = document.createElement('div');
    item.className = 'legend-item';
    item.dataset.cat = cat;
    item.title = 'Click to show only ' + (CAT_NAMES[cat] || cat) + ' concepts';
    item.innerHTML = '<div class="legend-dot" style="background:' + CAT_COLORS[cat] + '"></div>' +
      '<div class="legend-text"><span class="legend-name">' + (CAT_NAMES[cat] || cat) + '</span>' +
      '<span class="legend-desc">' + (CAT_DESC[cat] || '') + '</span></div>';
    item.addEventListener('click', function() {{
      filterCat = (filterCat === cat) ? null : cat;
      document.querySelectorAll('.legend-item').forEach(function(li) {{
        li.style.opacity = (filterCat && li.dataset.cat !== filterCat) ? '0.3' : '1';
      }});
    }});
    legendEl.appendChild(item);
  }});

  // Trending
  function logSearch(term) {{
    var key = 'austen_searches';
    var arr = JSON.parse(localStorage.getItem(key) || '[]');
    arr.push({{term: term.toLowerCase(), ts: Date.now()}});
    if (arr.length > 200) arr = arr.slice(-200);
    localStorage.setItem(key, JSON.stringify(arr));
    if (SEARCH_URL) {{
      fetch(SEARCH_URL + '/api/search', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{term: term, page: 'glossary', ts: Date.now()/1000}})
      }}).catch(function(){{}});
    }}
  }}

  function loadTrending() {{
    function display(items) {{
      var el = document.getElementById('trending-chips');
      el.innerHTML = '';
      items.slice(0, 6).forEach(function(item) {{
        var chip = document.createElement('span');
        chip.className = 'trending-chip';
        chip.textContent = item.term;
        chip.addEventListener('click', function() {{
          document.getElementById('search-input').value = item.term;
          searchQuery = item.term;
          var found = simNodes.find(function(n) {{
            return n.data.label.toLowerCase() === item.term.toLowerCase();
          }});
          if (found) showDetail(found.idx);
        }});
        el.appendChild(chip);
      }});
    }}

    if (SEARCH_URL) {{
      fetch(SEARCH_URL + '/api/trending').then(function(r) {{ return r.json(); }})
        .then(function(d) {{ if (d.trending && d.trending.length) display(d.trending); else loadTrendingLocal(); }})
        .catch(loadTrendingLocal);
    }} else {{
      loadTrendingLocal();
    }}
  }}

  function loadTrendingLocal() {{
    var arr = JSON.parse(localStorage.getItem('austen_searches') || '[]');
    var cutoff = Date.now() - 7 * 86400000;
    var counts = {{}};
    arr.filter(function(s) {{ return s.ts >= cutoff; }}).forEach(function(s) {{
      counts[s.term] = (counts[s.term] || 0) + 1;
    }});
    var sorted = Object.entries(counts).sort(function(a,b) {{ return b[1]-a[1]; }});
    if (sorted.length) display(sorted.slice(0,6).map(function(e) {{ return {{term:e[0], count:e[1]}}; }}));
  }}

  // URL param: focus a specific node on load
  var params = new URLSearchParams(window.location.search);
  var focusTerm = params.get('focus');

  resize();
  window.addEventListener('resize', function() {{ resize(); }});
  initNodes();
  loadTrending();
  requestAnimationFrame(tick);

  if (focusTerm) {{
    setTimeout(function() {{
      var ft = focusTerm.toLowerCase().trim();
      var norm = function(s) {{ return s.toLowerCase().trim().replace(/s$/, ''); }};
      var found = simNodes.find(function(n) {{
        return n.data.label.toLowerCase() === ft;
      }});
      // Fallback: match ignoring a trailing plural 's' on either side
      if (!found) {{
        found = simNodes.find(function(n) {{ return norm(n.data.label) === norm(ft); }});
      }}
      if (found) showDetail(found.idx);
    }}, 400);
  }}

  document.getElementById('shuffle-btn').addEventListener('click', function() {{
    var pool = simNodes.filter(function(n) {{ return nodeVisible(n) && n.idx !== activeIdx; }});
    if (pool.length === 0) pool = simNodes.filter(function(n) {{ return n.idx !== activeIdx; }});
    if (pool.length === 0) return;
    var pick = pool[Math.floor(Math.random() * pool.length)];
    showDetail(pick.idx);
  }});
}})();
</script>
</body>
</html>"""


# ─── Battle cards renderer ──────────────────────────────────────────────────

def render_battlecards_html():
    nav = _nav_html("battlecards")

    cards_html = ""
    for c in BATTLE_CARDS:
        products_li = "".join(f'<li>{p}</li>' for p in c["key_products"])
        strengths_li = "".join(f'<li>{s}</li>' for s in c["strengths"])
        terms_html = ""
        for t in c["related_terms"]:
            terms_html += f'<a href="glossary.html?focus={t.replace(" ", "+")}" class="term-chip">{t}</a>'

        cards_html += f"""
<div class="bc-card" id="bc-{c['id']}">
  <div class="bc-header" style="border-left:4px solid {c['color']}">
    <div>
      <div class="bc-name">{c['name']}</div>
      <div class="bc-product">{c['product']}</div>
      <div class="bc-tagline">{c['tagline']}</div>
    </div>
  </div>
  <div class="bc-body">
    <div class="bc-section">
      <div class="bc-section-label">What it is</div>
      <p>{c['what_it_is']}</p>
    </div>
    <div class="bc-section">
      <div class="bc-section-label">Key products</div>
      <ul>{products_li}</ul>
    </div>
    <div class="bc-section">
      <div class="bc-section-label">Strengths</div>
      <ul>{strengths_li}</ul>
    </div>
    <div class="bc-section bc-watch">
      <div class="bc-section-label">Watch out for</div>
      <p>{c['watch_out']}</p>
    </div>
    <div class="bc-section bc-ramsac">
      <div class="bc-section-label">Our angle</div>
      <p>{c['ramsac_angle']}</p>
    </div>
    <div class="bc-section">
      <div class="bc-section-label">Related concepts</div>
      <div class="bc-terms">{terms_html}</div>
    </div>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Austen</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
@font-face{{font-family:'Charger';src:url('fonts/ChargerV2Condensed.ttf') format('truetype');font-weight:400;font-display:swap}}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {BG_MAIN}; font-family: Geist, Arial, sans-serif; color: {TEXT}; min-height: 100vh; }}
  a {{ color: inherit; text-decoration: none; }}
  {_nav_css()}
  .page-body {{ max-width: 1040px; margin: 0 auto; padding: 32px 16px 64px; }}
  .page-title {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 22px; font-weight: 800; color: {NAVY}; margin-bottom: 6px; }}
  .page-sub {{ font-size: 14px; color: {MUTED}; margin-bottom: 32px; line-height: 1.6; }}
  .ramsac-diff {{ background: {HERO_GRADIENT}; border-radius: 10px; padding: 28px 88px; margin-bottom: 36px; overflow: hidden; }}
  .ramsac-diff-label {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: {ON_DARK}; font-weight: 700; margin-bottom: 8px; }}
  .ramsac-diff p {{ font-size: 14px; color: rgba(255,255,255,0.85); line-height: 1.7; }}
  .bc-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }}
  .bc-card {{ background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 10px; overflow: hidden; }}
  .bc-header {{ padding: 20px 20px 16px; background: {BG_CARD}; }}
  .bc-name {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 18px; font-weight: 800; color: {NAVY}; }}
  .bc-product {{ font-size: 13px; color: {MUTED}; margin-top: 2px; }}
  .bc-tagline {{ font-size: 12px; color: {ACCENT}; font-weight: 600; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.08em; font-family: 'Charger', Georgia, 'Times New Roman', serif; }}
  .bc-body {{ padding: 0 20px 20px; }}
  .bc-section {{ margin-top: 16px; }}
  .bc-section-label {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: {ACCENT}; font-weight: 700; margin-bottom: 6px; }}
  .bc-section p {{ font-size: 13px; line-height: 1.65; color: {MUTED}; }}
  .bc-section ul {{ padding-left: 18px; }}
  .bc-section ul li {{ font-size: 13px; line-height: 1.65; color: {MUTED}; margin-bottom: 2px; }}
  .bc-watch {{ background: #F9F0D9; border-radius: 6px; padding: 12px 14px; margin-top: 16px; }}
  .bc-watch .bc-section-label {{ color: #B9793A; }}
  .bc-ramsac {{ background: #F6E6D3; border-radius: 6px; padding: 12px 14px; margin-top: 16px; border-left: 3px solid {ACCENT}; }}
  .bc-ramsac .bc-section-label {{ color: {ACCENT}; }}
  .bc-ramsac p {{ color: #41488A; }}
  .bc-terms {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
  .term-chip {{ display: inline-block; background: rgba(207,81,43,0.12); color: #0A111A; font-size: 11px; font-weight: 600; border-radius: 20px; padding: 3px 10px; border: 1px solid {ACCENT}; font-family: 'Charger', Georgia, 'Times New Roman', serif; cursor: pointer; transition: background 0.15s; }}
  .term-chip:hover {{ background: {ACCENT}; color: {ON_DARK}; }}
</style>
</head>
<body>
{nav}
<div class="page-body">
  <div class="eyebrow-row" style="margin-bottom:14px">
    <span class="pill">Know your landscape</span>
    <span class="eyebrow-count">{len(BATTLE_CARDS)} providers</span>
  </div>
  <div class="page-title">AI Battle Cards</div>
  <p class="page-sub">Understand each major AI provider, what they offer, and how we position against them.</p>
  <hr class="hairline" style="margin:24px 0 28px">
  <div class="ramsac-diff bracket">
    <div class="ramsac-diff-label">Our differentiation</div>
    <p>We are model-agnostic. We are not tied to any single AI provider. We can deploy, wrap, and switch between Anthropic, OpenAI, Google, Microsoft, Meta, and others, selecting the best model for each client's task, budget, and data requirements. Our clients get the best of every provider through one trusted partner, without vendor lock-in.</p>
  </div>
  <div class="bc-grid">
    {cards_html}
  </div>
</div>
<script>
  var SEARCH_URL = "{FEEDBACK_SERVER_URL}";
  function logView(name) {{
    if (!SEARCH_URL) return;
    fetch(SEARCH_URL + '/api/search', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{term: name, page: 'battlecards', ts: Date.now() / 1000}})
    }}).catch(function(){{}});
  }}
  document.querySelectorAll('.bc-card').forEach(function(card) {{
    logView(card.querySelector('.bc-name').textContent);
  }});
</script>
</body>
</html>"""


# ─── EML generator ──────────────────────────────────────────────────────────

def render_email_html(data, today, date_slug, digest_url):
    """Render a fully inline-styled, Outlook dark-mode-safe email HTML."""

    def story_rows(stories):
        rows = []
        for i, s in enumerate(stories, 1):
            rows.append(f"""
        <tr>
          <td style="padding:0 0 12px 0">
            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="background:#ffffff;border-radius:8px;border:1px solid #C2CCD5;border-left:3px solid #CF512B">
              <tr>
                <td style="padding:20px 22px" bgcolor="#ffffff">
                  <table cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tr>
                      <td width="48" valign="top" style="padding:0 14px 0 0">
                        <table cellpadding="0" cellspacing="0" border="0">
                          <tr><td width="36" height="36" align="center" bgcolor="#CF512B"
                                  style="width:36px;height:36px;border-radius:50%;background:#CF512B;text-align:center;line-height:36px">
                            <font color="#ffffff" face="Geist,Arial,sans-serif"><b style="font-size:15px">{i}</b></font>
                          </td></tr>
                        </table>
                      </td>
                      <td valign="middle">
                        <p style="margin:0;font-size:15px;font-weight:700;font-family:'Charger',Georgia,'Times New Roman',serif;line-height:1.3">
                          <font color="#0A111A"><b>{s['title']}</b></font>
                        </p>
                        <p style="margin:4px 0 0 0;font-size:11px;font-family:Geist,Arial,sans-serif;text-transform:uppercase;letter-spacing:0.1em">
                          <font color="#CF512B">{s['source']}</font>
                        </p>
                      </td>
                    </tr>
                    <tr>
                      <td colspan="2" style="padding-top:10px">
                        <p style="margin:0;font-size:14px;font-family:Geist,Arial,sans-serif;line-height:1.6">
                          <font color="#41488A">{s['glance']}</font>
                        </p>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </td>
        </tr>""")
        return "".join(rows)

    return f"""<!DOCTYPE html>
<html lang="en" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light only">
<!--[if gte mso 9]><xml><o:OfficeDocumentSettings><o:AllowPNG/></o:OfficeDocumentSettings></xml><![endif]-->
<style>:root {{ color-scheme: light only; }}</style>
</head>
<body style="margin:0;padding:0;background-color:#FAF7E6;font-family:Geist,Arial,Helvetica,sans-serif" bgcolor="#FAF7E6">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#FAF7E6" style="background-color:#FAF7E6">
<tr><td align="center" style="padding:32px 16px;background-color:#FAF7E6">
  <table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%">

    <!-- HEADER: fixed masthead (date, title, brand) -->
    <tr>
      <td style="background:#0A111A;border-radius:12px 12px 0 0;padding:40px 36px 32px" bgcolor="#0A111A">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td>
              <p style="margin:0 0 8px 0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;font-family:'Charger',Georgia,'Times New Roman',serif;font-weight:600">
                <font color="#ffffff">{today}</font>
              </p>
              <p style="margin:0;font-size:28px;font-weight:800;font-family:'Charger',Georgia,'Times New Roman',serif;line-height:1.2">
                <font color="#ffffff"><b>This Week</b></font><font color="#C2CCD5"><b> in AI</b></font>
              </p>
            </td>
            <td width="80" align="right" valign="top">
              <p style="margin:0;font-size:13px;font-weight:800;font-family:'Charger',Georgia,'Times New Roman',serif;letter-spacing:-0.01em;line-height:1.4">
                <font color="#ffffff"><b>Thought<br>Provoked</b></font>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- THIS EDITION'S HEADLINE: changes every week -->
    <tr>
      <td style="background:#ffffff;padding:18px 36px;border-left:1px solid #C2CCD5;border-right:1px solid #C2CCD5;border-top:3px solid #CF512B" bgcolor="#ffffff">
        <p style="margin:0 0 6px 0;font-size:10px;letter-spacing:0.14em;text-transform:uppercase;font-family:'Charger',Georgia,'Times New Roman',serif;font-weight:700">
          <font color="#CF512B">This week</font>
        </p>
        <p style="margin:0;font-size:16px;font-weight:600;font-family:Geist,Arial,sans-serif;line-height:1.5">
          <font color="#0A111A">{data['intro']}</font>
        </p>
      </td>
    </tr>

    <!-- BODY -->
    <tr>
      <td style="background:#FAF7E6;padding:28px 32px 8px;border-left:1px solid #C2CCD5;border-right:1px solid #C2CCD5" bgcolor="#FAF7E6">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding:28px 0 20px 0;border-top:1px solid #C2CCD5">
              <p style="margin:0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;font-family:'Charger',Georgia,'Times New Roman',serif;font-weight:700">
                <font color="#CF512B">Top 5 at a Glance (click to read the full edition online)</font>
              </p>
            </td>
          </tr>
          {story_rows(data['stories'])}
        </table>
      </td>
    </tr>

    <!-- READ ONLINE BUTTON -->
    <tr>
      <td style="background:#FAF7E6;padding:0 32px 24px;border-left:1px solid #C2CCD5;border-right:1px solid #C2CCD5" bgcolor="#FAF7E6">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td align="center">
              <a href="{digest_url}" target="_blank"
                 style="display:inline-block;background:#CF512B;color:#ffffff;font-family:'Charger',Georgia,'Times New Roman',serif;font-size:13px;font-weight:700;text-decoration:none;padding:12px 28px;border-radius:8px">
                <font color="#ffffff"><b>Read full edition online &rarr;</b></font>
              </a>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td style="background:#0A111A;border-radius:0 0 12px 12px;padding:28px 36px;border:1px solid #0A111A" bgcolor="#0A111A">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td>
              <p style="margin:0 0 4px 0;font-size:15px;font-weight:700;font-family:'Charger',Georgia,'Times New Roman',serif">
                <font color="#ffffff"><b>Stay curious, stay ahead.</b></font>
              </p>
              <p style="margin:0;font-size:13px;font-family:Geist,Arial,sans-serif">
                <font color="#8E949D">See you next week.</font>
              </p>
            </td>
            <td align="right">
              <p style="margin:0;font-size:11px;font-weight:800;font-family:'Charger',Georgia,'Times New Roman',serif;letter-spacing:-0.01em">
                <font color="#ffffff"><b>Thought Provoked</b></font>
              </p>
              <p style="margin:2px 0 0 0;font-size:10px;font-family:Geist,Arial,sans-serif">
                <font color="#545C65">Weekly AI Briefing</font>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>

  </table>
</td></tr>
</table>
</body>
</html>"""


def render_applescript(subject, html):
    """Return an AppleScript that opens a new Outlook compose window with the digest."""
    # Escape backslashes and double-quotes for AppleScript string literals,
    # then collapse newlines so the HTML is one continuous string.
    escaped = html.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "").replace("\r", "")
    return f'''tell application "Microsoft Outlook"
    activate
    set newMessage to make new outgoing message with properties {{subject:"{subject}", content:"{escaped}"}}
    open newMessage
end tell
'''


# ─── GitHub Pages publisher ─────────────────────────────────────────────────

PAGES_BASE_URL = "https://ironbridge-ai.github.io/Austen"  # GitHub Pages URL


def _date_label(filename):
    """Return (display label, slug) for an austen_*.html filename."""
    slug = filename.replace("austen_", "").replace(".html", "")
    try:
        dt = datetime.strptime(slug, "%Y-%m-%d")
        return dt.strftime("%-d %B %Y"), slug
    except ValueError:
        return slug, slug


def write_index(directory, html_files):
    """Generate index.html: latest briefing inline, 3 prev edition cards, AI Glossary tile."""
    import re as _re

    nav = _nav_html("digest")
    nav_css = _nav_css()

    # ── Extract latest digest content ────────────────────────────────────────
    digest_css_extra = ""
    digest_main_html = ""
    digest_script_html = ""

    if html_files:
        latest_path = os.path.join(directory, html_files[0])
        if os.path.exists(latest_path):
            with open(latest_path, encoding="utf-8") as _f:
                raw = _f.read()

            m = _re.search(r'<style>(.*?)</style>', raw, _re.DOTALL)
            if m:
                digest_css_extra = m.group(1)

            c_start = raw.find('<!-- Email container -->')
            t_start = raw.find('<div id="ai-tooltip"')
            if c_start != -1 and t_start != -1:
                digest_main_html = raw[c_start:t_start].rstrip()

            sc_start = raw.find('<script>')
            sc_end = raw.rfind('</script>') + len('</script>')
            if sc_start != -1:
                digest_script_html = raw[sc_start:sc_end]

    # ── Previous edition cards (max 3, skip latest) ──────────────────────────
    prev_cards_html = ""
    for f in html_files[1:4]:
        label, _ = _date_label(f)
        prev_cards_html += (
            f'    <div class="edition-card">\n'
            f'      <div class="edition-date">{label}</div>\n'
            f'      <a class="view-btn" href="{f}">View &rarr;</a>\n'
            f'    </div>\n'
        )

    n_total = len(html_files)

    hub_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Austen</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
@font-face{{font-family:'Charger';src:url('fonts/ChargerV2Condensed.ttf') format('truetype');font-weight:400;font-display:swap}}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {BG_MAIN}; font-family: Geist, Arial, sans-serif; color: {TEXT}; min-height: 100vh; }}
  a {{ color: inherit; text-decoration: none; }}
  {nav_css}
  .page-body {{ max-width: 720px; margin: 0 auto; padding: 32px 16px 60px; }}
  .section-label {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: {ACCENT}; font-weight: 700; border-top: 1px solid {BORDER}; padding-top: 24px; margin-bottom: 20px; }}
  .edition-card {{ background: {BG_CARD}; border: 1px solid {BORDER}; border-left: 3px solid {ACCENT}; border-radius: 8px; padding: 16px 20px; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; }}
  .edition-date {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 14px; font-weight: 700; color: {NAVY}; }}
  .view-btn {{ display: inline-block; background: {ACCENT}; color: {ON_DARK}; font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 12px; font-weight: 700; text-decoration: none; padding: 8px 16px; border-radius: 6px; white-space: nowrap; transition: opacity 0.15s; }}
  .view-btn:hover {{ opacity: 0.85; }}
  .read-prev-btn {{ display: inline-block; color: {ACCENT}; border: 2px solid {ACCENT}; font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 13px; font-weight: 700; padding: 10px 24px; border-radius: 8px; transition: all 0.15s; }}
  .read-prev-btn:hover {{ background: {ACCENT}; color: {ON_DARK}; }}
  .hub-tile {{ background: {BG_CARD}; border: 1px solid {BORDER}; border-left: 3px solid {ACCENT}; border-radius: 10px; padding: 20px 22px; display: flex; flex-direction: column; gap: 8px; transition: box-shadow 0.15s; }}
  .hub-tile:hover {{ box-shadow: 0 4px 20px rgba(10,17,26,0.08); }}
  .hub-tile-label {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; font-weight: 700; color: {ACCENT}; }}
  .hub-tile-title {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 16px; font-weight: 800; color: {NAVY}; }}
  .hub-tile-desc {{ font-size: 13px; color: {MUTED}; line-height: 1.6; flex: 1; }}
  .hub-tile-btn {{ display: inline-block; background: {ACCENT}; color: {ON_DARK}; font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 11px; font-weight: 700; padding: 7px 14px; border-radius: 6px; align-self: flex-start; transition: opacity 0.15s; }}
  .hub-tile-btn:hover {{ opacity: 0.85; }}
  .footer {{ background: {NAVY}; border-radius: 10px; padding: 22px 32px; margin-top: 32px; display: flex; align-items: center; justify-content: space-between; }}
  .footer p {{ font-size: 12px; color: rgba(255,255,255,0.5); font-family: Geist, Arial, sans-serif; }}
  .footer-brand {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 18px; font-weight: 800; color: {ON_DARK}; letter-spacing: -0.02em; }}
  /* digest-page styles injected below */
  __DIGEST_CSS__
</style>
</head>
<body>
{nav}
<div class="page-body">

  <!-- ── Latest briefing ── -->
  __DIGEST_MAIN__

  <!-- ── Earlier editions ── -->
  <div class="section-label" style="margin-top:36px">Earlier Editions</div>
{prev_cards_html}
  <div style="text-align:center;margin:20px 0 4px">
    <a href="archive.html" target="_blank" class="read-prev-btn">Read previous editions &nbsp;&rarr;</a>
  </div>

  <!-- ── AI Glossary ── -->
  <div style="border-top:1px solid {BORDER};margin:36px 0 20px"></div>
  <a class="hub-tile" href="glossary.html">
    <span class="hub-tile-label">Explore</span>
    <div class="hub-tile-title">AI Glossary</div>
    <div class="hub-tile-desc">Navigate key AI concepts as a connected constellation. Click any term to see its definition and related ideas.</div>
    <span class="hub-tile-btn">Open glossary &rarr;</span>
  </a>

  <div class="footer">
    <p>Stay curious, stay ahead.</p>
    <a href="https://thoughtprovoked.co.uk" target="_blank" rel="noopener" class="footer-brand" style="display:flex;align-items:center;gap:8px">{TP_MARK}<span>Thought Provoked</span></a>
  </div>
</div>

<div id="ai-tooltip"></div>
__DIGEST_SCRIPT__
</body>
</html>"""

    html = (hub_template
            .replace("__DIGEST_CSS__", digest_css_extra)
            .replace("__DIGEST_MAIN__", digest_main_html)
            .replace("__DIGEST_SCRIPT__", digest_script_html))

    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    write_archive(directory, html_files)


def write_archive(directory, html_files):
    """Generate archive.html listing all editions sorted newest-first."""
    nav = _nav_html("digest")
    nav_css = _nav_css()

    cards_html = ""
    for f in html_files:
        label, _ = _date_label(f)
        cards_html += (
            f'    <div class="edition-card">\n'
            f'      <div class="edition-date">{label}</div>\n'
            f'      <a class="view-btn" href="{f}">View &rarr;</a>\n'
            f'    </div>\n'
        )

    n = len(html_files)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Austen</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
@font-face{{font-family:'Charger';src:url('fonts/ChargerV2Condensed.ttf') format('truetype');font-weight:400;font-display:swap}}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {BG_MAIN}; font-family: Geist, Arial, sans-serif; color: {TEXT}; min-height: 100vh; }}
  a {{ color: inherit; text-decoration: none; }}
  {nav_css}
  .page-body {{ max-width: 720px; margin: 0 auto; padding: 40px 16px 60px; }}
  .eyebrow-row {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 20px; }}
  .eyebrow-count {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: {MUTED}; }}
  .pill {{ display: inline-block; font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 10px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: {ACCENT}; border: 1px solid {ACCENT}; border-radius: 999px; padding: 4px 13px; }}
  .edition-card {{ background: {BG_CARD}; border: 1px solid {BORDER}; border-left: 3px solid {ACCENT}; border-radius: 8px; padding: 16px 20px; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; }}
  .edition-date {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 14px; font-weight: 700; color: {NAVY}; }}
  .view-btn {{ display: inline-block; background: {ACCENT}; color: {ON_DARK}; font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 12px; font-weight: 700; text-decoration: none; padding: 8px 16px; border-radius: 6px; white-space: nowrap; transition: opacity 0.15s; }}
  .view-btn:hover {{ opacity: 0.85; }}
  .footer {{ background: {NAVY}; border-radius: 10px; padding: 22px 32px; margin-top: 32px; display: flex; align-items: center; justify-content: space-between; }}
  .footer p {{ font-size: 12px; color: rgba(255,255,255,0.5); font-family: Geist, Arial, sans-serif; }}
  .footer-brand {{ font-family: 'Charger', Georgia, 'Times New Roman', serif; font-size: 18px; font-weight: 800; color: {ON_DARK}; letter-spacing: -0.02em; }}
</style>
</head>
<body>
{nav}
<div class="page-body">
  <div style="margin-bottom:24px">
    <a href="index.html" style="display:inline-block;background:{BG_CARD};border:1px solid {BORDER};color:{ACCENT};font-family:'Charger',Georgia,'Times New Roman',serif;font-size:12px;font-weight:700;text-decoration:none;padding:9px 16px;border-radius:8px">&larr; Back to Hub</a>
  </div>
  <div class="eyebrow-row">
    <span class="pill">All Editions</span>
    <span class="eyebrow-count">{n} edition{'s' if n != 1 else ''}</span>
  </div>
{cards_html}
  <div class="footer">
    <p>Stay curious, stay ahead.</p>
    <a href="https://thoughtprovoked.co.uk" target="_blank" rel="noopener" class="footer-brand" style="display:flex;align-items:center;gap:8px">{TP_MARK}<span>Thought Provoked</span></a>
  </div>
</div>
</body>
</html>"""

    with open(os.path.join(directory, "archive.html"), "w", encoding="utf-8") as f:
        f.write(html)


def publish_to_pages(html_file, date_slug, knowledge_log):
    """Add new digest + glossary + battlecards to gh-pages, rebuild index, push."""
    import subprocess
    import shutil
    import tempfile

    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("\nPublishing to GitHub Pages...")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["git", "-C", script_dir, "worktree", "add", tmp, "gh-pages"],
            check=True, capture_output=True
        )
        try:
            shutil.copy(os.path.join(script_dir, html_file), os.path.join(tmp, html_file))

            fonts_src = os.path.join(script_dir, "fonts")
            if os.path.isdir(fonts_src):
                shutil.copytree(fonts_src, os.path.join(tmp, "fonts"), dirs_exist_ok=True)

            # Regenerate glossary and battlecards with latest data
            glossary_html = render_glossary_html(knowledge_log)
            with open(os.path.join(tmp, "glossary.html"), "w", encoding="utf-8") as f:
                f.write(glossary_html)

            battlecards_html = render_battlecards_html()
            with open(os.path.join(tmp, "battlecards.html"), "w", encoding="utf-8") as f:
                f.write(battlecards_html)

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
            subprocess.run(["git", "-C", tmp, "push", "origin", "gh-pages"], check=True)
        finally:
            subprocess.run(
                ["git", "-C", script_dir, "worktree", "remove", "--force", tmp],
                capture_output=True
            )

    print(f"--- Published:   {PAGES_BASE_URL}/")
    print(f"--- Direct link: {PAGES_BASE_URL}/{html_file}")
    print(f"--- Glossary:    {PAGES_BASE_URL}/glossary.html")
    print(f"--- Battle cards:{PAGES_BASE_URL}/battlecards.html")


def publish_command_to_main(cmd_file, date_slug):
    """Commit the .command file to main so it's always available on GitHub."""
    import subprocess
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("\nPublishing .command file to GitHub...")
    subprocess.run(["git", "-C", script_dir, "add", cmd_file], check=True)
    result = subprocess.run(
        ["git", "-C", script_dir, "commit", "-m", f"Add email command for {date_slug}"],
        capture_output=True, text=True
    )
    if result.returncode != 0 and "nothing to commit" in result.stdout:
        print("--- Command file: nothing new to commit.")
        return
    subprocess.run(["git", "-C", script_dir, "push", "origin", "main"], check=True)
    print(f"--- Command file pushed to GitHub: {cmd_file}")


# ─── Main ───────────────────────────────────────────────────────────────────

def load_dotenv():
    """Load KEY=VALUE pairs from a local .env (next to this script) into the
    environment, without overriding anything already set. No dependencies."""
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_file):
        return
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def main():
    load_dotenv()
    api_key  = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set. Create ~/workspace/ai-news-digest/.env")
        print("with ANTHROPIC_API_KEY=... and ANTHROPIC_BASE_URL=... (see .env.example).")
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

    # Cap at 50 most-recent articles — Claude only selects 5; beyond ~50 the
    # additional context adds cost without improving selection quality.
    if len(unique) > 50:
        print(f"  Capping at 50 most-recent articles (found {len(unique)}).")
        unique = unique[:50]

    print(f"\nTotal: {len(unique)} unique articles. Sending to Claude...\n")

    knowledge_log = load_knowledge_log()
    print(f"Knowledge log loaded: {len(knowledge_log.get('terms', []))} terms already taught.\n")

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**client_kwargs)

    model = os.environ.get("AUSTEN_MODEL", "eu.anthropic.claude-opus-4-6-v1")
    print(f"Model: {model}\n")
    response = client.messages.create(
        model=model,
        max_tokens=4000,
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

    # Resolve each story's source URL from the article it was based on, rather
    # than trusting the model to reproduce a URL string verbatim.
    for story in data.get("stories", []):
        idx = story.pop("source_index", None)
        story["url"] = ""
        if isinstance(idx, int) and 1 <= idx <= len(unique):
            story["url"] = unique[idx - 1].get("url", "")

    today = datetime.now().strftime("%-d %B %Y")
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
        # Basic ML/AI concepts the ramsac audience already understands
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

    append_published_stories(data.get("stories", []), date_slug)
    print(f"Stories log updated: {len(data.get('stories', []))} stories recorded.\n")

    txt_file  = f"austen_{date_slug}.txt"
    html_file = f"austen_{date_slug}.html"
    cmd_file  = f"austen_{date_slug}.command"

    txt = render_text(data, today)
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(txt)

    html = render_html(data, today, date_slug)
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)

    digest_url = f"{PAGES_BASE_URL}/{html_file}"
    email_html = render_email_html(data, today, date_slug, digest_url)
    script = render_applescript(data["subject"], email_html)
    cmd = f'#!/bin/bash\nosascript << \'APPLESCRIPT\'\n{script}\nAPPLESCRIPT\n'
    with open(cmd_file, "w", encoding="utf-8") as f:
        f.write(cmd)
    os.chmod(cmd_file, 0o755)

    print(txt)
    print(f"\n--- Text saved to {txt_file}")
    print(f"--- HTML saved to {html_file}")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"--- Email ready:  {cmd_file}")
    print(f"\n    To open in Outlook, run this on your Mac (avoids quarantine):")
    print(f"    scp rvelasquez@dev-rvelasquez:{script_dir}/{cmd_file} ~/Desktop/ && open ~/Desktop/{cmd_file}")

    publish_to_pages(html_file, date_slug, knowledge_log)
    publish_command_to_main(cmd_file, date_slug)


if __name__ == "__main__":
    main()
