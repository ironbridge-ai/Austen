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

FEEDBACK_SERVER_URL = os.environ.get("FEEDBACK_SERVER_URL", "https://ramsac-austen.ironbridge.tech")

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

# ─── Glossary data ──────────────────────────────────────────────────────────

CATEGORY_COLORS = {
    "foundation": "#f97316",
    "generation":  "#8b5cf6",
    "deployment":  "#3b82f6",
    "safety":      "#ef4444",
    "business":    "#10b981",
}

TERM_CATEGORIES = {
    "ai agent": "deployment", "data isolation": "safety",
    "prompt injection": "safety", "multi-agent interaction": "deployment",
    "emergent behaviour": "safety", "frontier model": "foundation",
    "token consumption": "business", "searchleak": "safety",
    "multi-model architectures": "business", "diffusion-based generation": "generation",
    "search-grounding": "deployment", "open-weight model": "foundation",
    "diffusiongemma": "generation", "ai agent governance": "business",
    "model diversification": "business", "record and replay": "deployment",
    "llm": "foundation", "transformer": "foundation",
    "neural network": "foundation", "context window": "deployment",
    "rag": "deployment", "hallucination": "safety",
    "rlhf": "safety", "multimodal": "generation",
    "agentic workflow": "deployment", "alignment": "safety",
    "autoregressive model": "generation", "copilot": "business",
}

GLOSSARY_SEED_TERMS = [
    {"term": "LLM", "definition": "Large Language Model. An AI trained on vast amounts of text that can understand and generate human language. Think of it as an extremely well-read assistant that has absorbed billions of documents and can write, summarise, answer questions, and hold a conversation."},
    {"term": "Transformer", "definition": "The architecture that powers most modern AI models. Invented by Google in 2017, it lets AI process entire paragraphs at once and understand how words relate to each other, rather than reading one word at a time. It is the engine inside GPT, Claude, Gemini, and nearly every other AI you use today."},
    {"term": "Neural Network", "definition": "The basic building block of modern AI. Loosely inspired by the human brain, it is a layered system that learns patterns by adjusting millions of tiny connections based on examples. Train it on enough data and it learns to recognise faces, translate languages, or generate code."},
    {"term": "Context Window", "definition": "The maximum amount of text an AI can see and work with at one time. Think of it like the AI's short-term memory. A small context window limits the AI to a few pages; a large one can handle an entire book. Bigger context windows mean the AI can work on longer, more complex tasks."},
    {"term": "RAG", "definition": "Retrieval-Augmented Generation. A technique where an AI first searches a database of documents to find relevant information, then writes its answer based on what it found. This stops the AI from making things up and keeps answers grounded in your actual company data."},
    {"term": "Hallucination", "definition": "When an AI confidently states something that is factually wrong. Like a student who does not know the answer but writes something plausible-sounding anyway. Hallucination is one of the main risks of using AI output without human review."},
    {"term": "RLHF", "definition": "Reinforcement Learning from Human Feedback. A training method where humans rate the AI's responses as good or bad, and the AI learns to produce more of what got positive ratings. This is how ChatGPT and Claude became helpful and conversational."},
    {"term": "Multimodal", "definition": "An AI that can work with more than one type of input or output — text, images, audio, and video. A multimodal model can describe a photograph, read a chart, listen to a voice recording, or analyse a document without switching tools."},
    {"term": "Agentic workflow", "definition": "A process where an AI takes a series of actions over time to complete a goal, rather than just answering a single question. An AI told to book a meeting might check calendars, draft an email, send it, and update a spreadsheet — all in sequence without human prompting at each step."},
    {"term": "Alignment", "definition": "The challenge of making AI systems do what humans actually want, safely and reliably. An aligned AI follows instructions without harmful side effects, respects rules, and does not pursue goals that conflict with human values. It is the difference between a helpful assistant and an unpredictable one."},
    {"term": "Autoregressive model", "definition": "An AI that generates text one word at a time, where each word is predicted based on everything that came before it. This is how GPT models work. It is like autocomplete on your phone, but applied thousands of times in sequence at extraordinary speed."},
]

GLOSSARY_EDGES = [
    ["LLM", "Transformer"], ["LLM", "frontier model"], ["LLM", "Context Window"],
    ["LLM", "Hallucination"], ["LLM", "multi-model architectures"],
    ["LLM", "Autoregressive model"],
    ["Transformer", "diffusion-based generation"], ["Transformer", "Autoregressive model"],
    ["AI agent", "Agentic workflow"], ["AI agent", "multi-agent interaction"],
    ["AI agent", "AI agent governance"], ["AI agent", "Record and Replay"],
    ["prompt injection", "SearchLeak"], ["prompt injection", "Data isolation"],
    ["prompt injection", "Hallucination"],
    ["search-grounding", "SearchLeak"], ["search-grounding", "RAG"],
    ["RAG", "Context Window"],
    ["model diversification", "multi-model architectures"],
    ["model diversification", "open-weight model"],
    ["diffusion-based generation", "DiffusionGemma"],
    ["multi-agent interaction", "emergent behaviour"],
    ["multi-agent interaction", "AI agent governance"],
    ["frontier model", "open-weight model"],
    ["token consumption", "Context Window"],
    ["RLHF", "Alignment"], ["RLHF", "frontier model"],
    ["Multimodal", "diffusion-based generation"],
    ["Agentic workflow", "AI agent governance"],
    ["Neural Network", "Transformer"], ["Neural Network", "LLM"],
]

# ─── Battle card data ────────────────────────────────────────────────────────

BATTLE_CARDS = [
    {
        "id": "anthropic",
        "name": "Anthropic",
        "product": "Claude",
        "tagline": "Safety-first frontier AI",
        "color": "#d97706",
        "what_it_is": "Anthropic is an AI safety company founded by former OpenAI researchers. Their flagship product is Claude — a family of AI models (Opus, Sonnet, Haiku) known for being exceptionally safe, accurate, and capable of handling long, complex documents. Claude powers many enterprise AI applications behind the scenes.",
        "key_products": ["Claude Opus (most capable)", "Claude Sonnet (balanced)", "Claude Haiku (fastest, cheapest)"],
        "strengths": ["Highest-rated for accuracy and instruction-following", "Best-in-class for long document analysis", "Strong safety record with enterprise clients", "Excellent at coding and technical reasoning"],
        "watch_out": "Available primarily via API — no standalone consumer app with wide adoption yet. Anthropic focuses on the model layer, not the application layer.",
        "ramsac_angle": "Claude is one of the models RAMSAC can deploy and wrap for clients. Because we are model-agnostic, we can use Anthropic's strengths — accuracy, safety, long-context — for the right use cases without locking clients into a single vendor.",
        "related_terms": ["frontier model", "AI agent", "Context Window", "Alignment", "RLHF"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "product": "ChatGPT / GPT-4o",
        "tagline": "The brand that made AI mainstream",
        "color": "#10b981",
        "what_it_is": "OpenAI created ChatGPT, the product that brought AI to 200 million users. Their GPT-4o model powers ChatGPT and is embedded in thousands of third-party products. OpenAI also makes Codex (code generation), DALL-E (images), and Operator (web browsing agent).",
        "key_products": ["ChatGPT (consumer + enterprise)", "GPT-4o API", "Codex (coding)", "Operator (agentic web browsing)"],
        "strengths": ["Largest user base and brand recognition", "Strong ecosystem of integrations", "Broad multimodal capability (text, images, audio, video)", "Fastest at shipping new features"],
        "watch_out": "Quality can be inconsistent across versions. Microsoft has exclusive cloud rights, meaning Azure OpenAI Service is the enterprise path — which ties clients to Microsoft pricing and infrastructure.",
        "ramsac_angle": "Most clients will already have heard of ChatGPT. RAMSAC can build on that familiarity while offering something they cannot get alone: proper deployment, governance, and the ability to switch to a better model when OpenAI is not the right fit.",
        "related_terms": ["LLM", "Multimodal", "Agentic workflow", "Autoregressive model", "frontier model"],
    },
    {
        "id": "microsoft",
        "name": "Microsoft",
        "product": "Copilot / Azure AI",
        "tagline": "AI baked into tools your clients already pay for",
        "color": "#0078d4",
        "what_it_is": "Microsoft has embedded AI across its entire product stack. Copilot appears in Word, Excel, Outlook, Teams, and SharePoint. Azure OpenAI Service gives enterprises access to GPT-4 through Microsoft's cloud. Copilot Studio lets businesses build custom AI agents without writing code.",
        "key_products": ["Microsoft 365 Copilot (Office AI)", "Azure OpenAI Service", "Copilot Studio (custom agents)", "Security Copilot"],
        "strengths": ["Already inside tools clients pay for — no new vendor", "Deep integration with M365 data (emails, Teams, SharePoint)", "Enterprise-grade compliance and data residency", "Security Copilot for threat intelligence"],
        "watch_out": "Copilot licensing adds cost on top of existing M365 subscriptions. Some features require specific licence tiers. Privacy and data handling policies have been a concern for regulated industries.",
        "ramsac_angle": "This is core RAMSAC territory. As an M365 specialist, we are the natural partner for Copilot deployment, governance, and training. We understand which clients are ready, what data needs preparing, and how to get ROI — something Microsoft's own sales team cannot deliver at the SME level.",
        "related_terms": ["Agentic workflow", "search-grounding", "prompt injection", "Data isolation", "multi-model architectures"],
    },
    {
        "id": "google",
        "name": "Google / DeepMind",
        "product": "Gemini",
        "tagline": "The multimodal powerhouse",
        "color": "#4285f4",
        "what_it_is": "Google DeepMind develops Gemini, Google's flagship AI model family. Gemini powers Google Search AI, Google Workspace AI (Docs, Gmail, Meet), and Google Cloud AI. DeepMind — Google's research arm — also produces breakthrough research models like AlphaFold and DiffusionGemma.",
        "key_products": ["Gemini Ultra / Pro / Flash", "Google Workspace AI", "NotebookLM (document intelligence)", "Google Cloud Vertex AI"],
        "strengths": ["Best multimodal capabilities (text, image, audio, video, code)", "Deep integration with Google Workspace", "Real-time web search grounding built in", "Strong research pedigree from DeepMind"],
        "watch_out": "Gemini's consumer reputation has suffered from high-profile errors at launch. Enterprise adoption is growing but still behind Microsoft. Google Cloud customers are the natural target, not M365 shops.",
        "ramsac_angle": "Most RAMSAC clients are in the Microsoft ecosystem, not Google. But Gemini's multimodal strengths and research pace mean it is a model worth including in any multi-model deployment strategy — especially for image, video, or search-heavy workflows.",
        "related_terms": ["Multimodal", "diffusion-based generation", "frontier model", "search-grounding", "RAG"],
    },
    {
        "id": "xai",
        "name": "xAI",
        "product": "Grok",
        "tagline": "Elon Musk's unfiltered AI",
        "color": "#1da1f2",
        "what_it_is": "xAI is Elon Musk's AI company, launched in 2023. Grok is its flagship model, integrated into X (formerly Twitter) and available as a standalone API. Grok 3 is positioned as a frontier model competing directly with GPT-4 and Claude. Aurora is xAI's image generation model.",
        "key_products": ["Grok 3 (frontier model)", "Grok API", "Aurora (image generation)", "X/Twitter integration"],
        "strengths": ["Real-time access to X/Twitter data", "Fewer content restrictions than competitors", "Growing model quality — Grok 3 benchmarks are competitive", "Strong coding capabilities"],
        "watch_out": "Brand association with Elon Musk and X creates reputational risk for enterprise clients. Data privacy policies are less mature than established providers. Not a natural fit for regulated industries.",
        "ramsac_angle": "Grok is unlikely to be the right choice for RAMSAC clients in regulated or professional services sectors. Worth knowing about because clients will ask. In a model-agnostic architecture, it could serve specific use cases where real-time social data or fewer content restrictions matter.",
        "related_terms": ["LLM", "frontier model", "open-weight model", "Multimodal"],
    },
    {
        "id": "meta",
        "name": "Meta AI",
        "product": "Llama",
        "tagline": "Open-weight AI anyone can run",
        "color": "#0866ff",
        "what_it_is": "Meta releases its Llama model family as open-weight — anyone can download and run the models on their own hardware. Llama 3 and 3.1 are among the most capable open models available. Meta AI is also the assistant embedded in WhatsApp, Instagram, and Facebook.",
        "key_products": ["Llama 3.x (open-weight models)", "Meta AI (consumer assistant)", "Llama API (hosted inference)"],
        "strengths": ["Open-weight means clients can run models on-premise with no data leaving their environment", "No per-token cost when self-hosted", "Strong community of fine-tuned variants for specific industries", "Competitive quality, especially for code and instruction-following"],
        "watch_out": "Running Llama requires technical infrastructure — it is not plug-and-play for most SMEs. Meta's consumer products (WhatsApp AI) are separate from enterprise Llama deployments. Meta does not provide enterprise support.",
        "ramsac_angle": "Llama is the clearest illustration of why model-agnostic matters. Some clients in legal, finance, or healthcare need AI that never touches an external server. RAMSAC can deploy Llama on the client's own infrastructure — something no single-vendor AI provider will ever offer.",
        "related_terms": ["open-weight model", "LLM", "model diversification", "frontier model"],
    },
]


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
<html lang="en" style="color-scheme:light only;background-color:#f5fbff">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light only">
<title>{data['subject']}</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{ color-scheme: light only; }}
  html {{ background-color: #f5fbff !important; }}
  body {{ background-color: #f5fbff !important; color: #373c46 !important; }}
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
<body style="margin:0;padding:0;background-color:#f5fbff !important;font-family:Manrope,Arial,Helvetica,sans-serif;color:#373c46 !important">

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
            <p style="margin:0 0 8px 0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#4ddcc3;font-family:Montserrat,Arial,sans-serif;font-weight:600">Weekly Briefing &nbsp;·&nbsp; {today}</p>
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
            <p style="margin:2px 0 0 0;font-size:10px;color:rgba(255,255,255,0.4);font-family:Manrope,Arial,sans-serif">Weekly AI Briefing</p>
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


# ─── Shared nav helpers ─────────────────────────────────────────────────────

def _nav_css():
    return f"""
  .site-nav {{ background: {NAVY}; padding: 0 24px; display: flex; align-items: center; gap: 0; border-bottom: 3px solid {ACCENT}; }}
  .nav-brand {{ font-family: Montserrat, Arial, sans-serif; font-size: 16px; font-weight: 800; color: {ACCENT}; letter-spacing: -0.02em; padding: 14px 20px 14px 0; border-right: 1px solid rgba(255,255,255,0.1); margin-right: 4px; white-space: nowrap; }}
  .nav-link {{ font-family: Montserrat, Arial, sans-serif; font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.6); padding: 14px 16px; text-transform: uppercase; letter-spacing: 0.08em; transition: color 0.15s; border-bottom: 3px solid transparent; margin-bottom: -3px; }}
  .nav-link:hover {{ color: #fff; }}
  .nav-link.active {{ color: {ACCENT}; border-bottom-color: {ACCENT}; }}"""


def _nav_html(active):
    links = [
        ("index.html", "Digest"),
        ("glossary.html", "Glossary"),
        ("battlecards.html", "Battle Cards"),
    ]
    items = ""
    for href, label in links:
        cls = "nav-link active" if label.lower().replace(" ", "") == active.lower().replace(" ", "") else "nav-link"
        items += f'<a href="{href}" class="{cls}">{label}</a>'
    return f'<nav class="site-nav"><div class="nav-brand">ramsac</div>{items}</nav>'


# ─── Glossary constellation renderer ────────────────────────────────────────

def render_glossary_html(knowledge_log):
    # Merge seed terms with knowledge_log — knowledge_log takes priority for definitions
    kl_terms = {t["term"].lower(): t for t in knowledge_log.get("terms", [])}
    all_nodes = {}

    for seed in GLOSSARY_SEED_TERMS:
        key = seed["term"].lower()
        if key in kl_terms:
            t = kl_terms[key]
            all_nodes[key] = {"label": t["term"], "definition": t["definition"],
                               "category": TERM_CATEGORIES.get(key, "foundation"), "from_log": True}
        else:
            all_nodes[key] = {"label": seed["term"], "definition": seed["definition"],
                               "category": TERM_CATEGORIES.get(key, "foundation"), "from_log": False}

    for t in knowledge_log.get("terms", []):
        key = t["term"].lower()
        if key not in all_nodes:
            all_nodes[key] = {"label": t["term"], "definition": t["definition"],
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
<title>AI Glossary — RAMSAC</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&family=Manrope:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {BG_MAIN}; font-family: Manrope, Arial, sans-serif; color: {TEXT}; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
  a {{ color: inherit; text-decoration: none; }}
  {_nav_css()}
  .workspace {{ display: flex; flex: 1; overflow: hidden; }}
  .graph-col {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }}
  .toolbar {{ display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: {BG_CARD}; border-bottom: 1px solid {BORDER}; flex-shrink: 0; }}
  .search-wrap {{ position: relative; flex: 1; max-width: 300px; }}
  .search-wrap input {{ width: 100%; padding: 8px 12px 8px 32px; border: 1px solid {BORDER}; border-radius: 20px; font-size: 13px; font-family: Manrope, Arial, sans-serif; outline: none; color: {TEXT}; background: {BG_MAIN}; transition: border-color 0.15s; }}
  .search-wrap input:focus {{ border-color: {ACCENT}; }}
  .search-icon {{ position: absolute; left: 10px; top: 50%; transform: translateY(-50%); font-size: 13px; opacity: 0.5; pointer-events: none; }}
  .legend {{ display: flex; gap: 10px; flex-wrap: wrap; }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 11px; color: {MUTED}; font-family: Montserrat, Arial, sans-serif; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; cursor: pointer; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .trending-bar {{ font-size: 11px; color: {MUTED}; display: flex; align-items: center; gap: 6px; flex-shrink: 0; }}
  .trending-bar span {{ font-family: Montserrat, Arial, sans-serif; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: {ACCENT}; }}
  .trending-chip {{ display: inline-block; background: rgba(77,220,195,0.1); color: {NAVY}; border-radius: 12px; padding: 2px 9px; font-size: 11px; cursor: pointer; border: 1px solid rgba(77,220,195,0.3); }}
  .trending-chip:hover {{ background: {ACCENT}; color: {NAVY}; }}
  #graph-svg {{ flex: 1; width: 100%; display: block; cursor: grab; }}
  #graph-svg:active {{ cursor: grabbing; }}
  .detail-col {{ width: 320px; flex-shrink: 0; border-left: 1px solid {BORDER}; background: {BG_CARD}; display: flex; flex-direction: column; overflow: hidden; }}
  .detail-empty {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 32px; text-align: center; opacity: 0.5; }}
  .detail-empty .hint-icon {{ font-size: 36px; margin-bottom: 12px; }}
  .detail-empty p {{ font-size: 13px; color: {MUTED}; line-height: 1.6; }}
  .detail-content {{ flex: 1; overflow-y: auto; padding: 28px 24px; display: none; }}
  .detail-category {{ font-family: Montserrat, Arial, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 700; margin-bottom: 8px; }}
  .detail-term {{ font-family: Montserrat, Arial, sans-serif; font-size: 22px; font-weight: 800; color: {NAVY}; margin-bottom: 16px; line-height: 1.2; }}
  .detail-def {{ font-size: 14px; line-height: 1.75; color: {TEXT}; margin-bottom: 24px; }}
  .detail-section-label {{ font-family: Montserrat, Arial, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: {ACCENT}; font-weight: 700; margin-bottom: 8px; border-top: 1px solid {BORDER}; padding-top: 16px; }}
  .related-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .related-chip {{ display: inline-block; background: {BG_MAIN}; border: 1px solid {BORDER}; border-radius: 16px; padding: 4px 12px; font-size: 12px; font-family: Montserrat, Arial, sans-serif; font-weight: 600; cursor: pointer; transition: all 0.15s; }}
  .related-chip:hover {{ border-color: {ACCENT}; background: rgba(77,220,195,0.1); }}
  .bc-link {{ display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: {BG_MAIN}; border: 1px solid {BORDER}; border-radius: 8px; margin-bottom: 8px; font-size: 13px; font-weight: 600; color: {NAVY}; font-family: Montserrat, Arial, sans-serif; transition: border-color 0.15s; }}
  .bc-link:hover {{ border-color: {ACCENT}; }}
  .bc-link-arrow {{ margin-left: auto; color: {ACCENT}; }}
</style>
</head>
<body>
{nav}
<div class="workspace">
  <div class="graph-col">
    <div class="toolbar">
      <div class="search-wrap">
        <span class="search-icon">&#128269;</span>
        <input type="text" id="search-input" placeholder="Search concepts..." autocomplete="off">
      </div>
      <div class="legend" id="legend"></div>
    </div>
    <div class="toolbar" style="padding-top:8px;padding-bottom:8px;border-top:none">
      <div class="trending-bar" id="trending-bar"><span>Trending</span><span id="trending-chips" style="display:flex;gap:6px"></span></div>
    </div>
    <svg id="graph-svg"></svg>
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
      <div id="d-bc-wrap" style="display:none">
        <div class="detail-section-label" style="margin-top:16px">See in battle cards</div>
        <div id="d-bc"></div>
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
      var r = Math.min(W, H) * 0.32;
      return {{ x: W/2 + r * Math.cos(angle), y: H/2 + r * Math.sin(angle),
               vx: 0, vy: 0, data: nd, idx: i }};
    }});
    simEdges = EDGES.map(function(e) {{ return {{ s: e[0], t: e[1] }}; }});
  }}

  var REPULSION = 2800, SPRING_LEN = 130, SPRING_K = 0.04;
  var DAMPING = 0.82, GRAVITY = 0.025, CAT_PULL = 0.012;

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
    for (var i = 0; i < simNodes.length; i++) {{
      var n = simNodes[i];
      if (n === dragging) continue;
      n.vx += (cx - n.x) * GRAVITY;
      n.vy += (cy - n.y) * GRAVITY;
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
      line.setAttribute('stroke', isActive ? '#4ddcc3' : '{BORDER}');
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

      var r = isActive ? 10 : 8;
      var circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('r', r);
      circle.setAttribute('fill', color);
      circle.setAttribute('stroke', isActive ? '#fff' : 'rgba(255,255,255,0.6)');
      circle.setAttribute('stroke-width', isActive ? '2.5' : '1.5');
      if (isActive) circle.setAttribute('filter', 'url(#glow)');

      var label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', r + 6); label.setAttribute('y', '5');
      label.setAttribute('font-size', isActive ? '13' : '12');
      label.setAttribute('font-weight', isActive ? '700' : '600');
      label.setAttribute('font-family', 'Montserrat, Arial, sans-serif');
      label.setAttribute('fill', isActive ? '{NAVY}' : '#444');
      label.setAttribute('pointer-events', 'none');
      label.textContent = nd.label;

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
    document.getElementById('d-term').textContent = nd.label;
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
        chip.textContent = simNodes[ni].data.label;
        chip.style.borderColor = CAT_COLORS[simNodes[ni].data.category] || '{BORDER}';
        chip.addEventListener('click', function() {{ showDetail(ni); }});
        relDiv.appendChild(chip);
      }});
    }} else {{
      relWrap.style.display = 'none';
    }}

    var bcWrap = document.getElementById('d-bc-wrap');
    var bcDiv = document.getElementById('d-bc');
    bcDiv.innerHTML = '';
    if (nd.battlecards && nd.battlecards.length > 0) {{
      bcWrap.style.display = 'block';
      nd.battlecards.forEach(function(bc) {{
        var a = document.createElement('a');
        a.className = 'bc-link';
        a.href = 'battlecards.html#bc-' + bc.id;
        a.innerHTML = bc.name + '<span class="bc-link-arrow">&#8599;</span>';
        bcDiv.appendChild(a);
      }});
    }} else {{
      bcWrap.style.display = 'none';
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
  var legendEl = document.getElementById('legend');
  Object.keys(CAT_COLORS).forEach(function(cat) {{
    var item = document.createElement('div');
    item.className = 'legend-item';
    item.innerHTML = '<div class="legend-dot" style="background:' + CAT_COLORS[cat] + '"></div>' + cat;
    item.addEventListener('click', function() {{
      filterCat = (filterCat === cat) ? null : cat;
      document.querySelectorAll('.legend-item').forEach(function(li) {{
        li.style.opacity = (filterCat && li.textContent.trim() !== filterCat) ? '0.35' : '1';
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
      var found = simNodes.find(function(n) {{
        return n.data.label.toLowerCase() === focusTerm.toLowerCase();
      }});
      if (found) showDetail(found.idx);
    }}, 400);
  }}
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
      <div class="bc-section-label">RAMSAC angle</div>
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
<title>AI Battle Cards — RAMSAC</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&family=Manrope:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {BG_MAIN}; font-family: Manrope, Arial, sans-serif; color: {TEXT}; min-height: 100vh; }}
  a {{ color: inherit; text-decoration: none; }}
  {_nav_css()}
  .page-body {{ max-width: 1040px; margin: 0 auto; padding: 32px 16px 64px; }}
  .page-title {{ font-family: Montserrat, Arial, sans-serif; font-size: 22px; font-weight: 800; color: {NAVY}; margin-bottom: 6px; }}
  .page-sub {{ font-size: 14px; color: {MUTED}; margin-bottom: 32px; line-height: 1.6; }}
  .ramsac-diff {{ background: {NAVY}; border-radius: 10px; padding: 20px 24px; margin-bottom: 36px; }}
  .ramsac-diff-label {{ font-family: Montserrat, Arial, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: {ACCENT}; font-weight: 700; margin-bottom: 8px; }}
  .ramsac-diff p {{ font-size: 14px; color: rgba(255,255,255,0.85); line-height: 1.7; }}
  .bc-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }}
  .bc-card {{ background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 10px; overflow: hidden; }}
  .bc-header {{ padding: 20px 20px 16px; background: {BG_CARD}; }}
  .bc-name {{ font-family: Montserrat, Arial, sans-serif; font-size: 18px; font-weight: 800; color: {NAVY}; }}
  .bc-product {{ font-size: 13px; color: {MUTED}; margin-top: 2px; }}
  .bc-tagline {{ font-size: 12px; color: {ACCENT}; font-weight: 600; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.08em; font-family: Montserrat, Arial, sans-serif; }}
  .bc-body {{ padding: 0 20px 20px; }}
  .bc-section {{ margin-top: 16px; }}
  .bc-section-label {{ font-family: Montserrat, Arial, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: {ACCENT}; font-weight: 700; margin-bottom: 6px; }}
  .bc-section p {{ font-size: 13px; line-height: 1.65; color: {MUTED}; }}
  .bc-section ul {{ padding-left: 18px; }}
  .bc-section ul li {{ font-size: 13px; line-height: 1.65; color: {MUTED}; margin-bottom: 2px; }}
  .bc-watch {{ background: #fff8f0; border-radius: 6px; padding: 12px 14px; margin-top: 16px; }}
  .bc-watch .bc-section-label {{ color: #d97706; }}
  .bc-ramsac {{ background: #f0fdf8; border-radius: 6px; padding: 12px 14px; margin-top: 16px; }}
  .bc-ramsac .bc-section-label {{ color: #059669; }}
  .bc-ramsac p {{ color: #065f46; }}
  .bc-terms {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
  .term-chip {{ display: inline-block; background: rgba(77,220,195,0.12); color: #11383f; font-size: 11px; font-weight: 600; border-radius: 20px; padding: 3px 10px; border: 1px solid {ACCENT}; font-family: Montserrat, Arial, sans-serif; cursor: pointer; transition: background 0.15s; }}
  .term-chip:hover {{ background: {ACCENT}; color: {NAVY}; }}
</style>
</head>
<body>
{nav}
<div class="page-body">
  <div class="page-title">AI Battle Cards</div>
  <p class="page-sub">Know your landscape. Understand each major AI provider, what they offer, and how RAMSAC positions against them.</p>
  <div class="ramsac-diff">
    <div class="ramsac-diff-label">Our differentiation</div>
    <p>RAMSAC is model-agnostic. We are not tied to any single AI provider. We can deploy, wrap, and switch between Anthropic, OpenAI, Google, Microsoft, Meta, and others — selecting the best model for each client's task, budget, and data requirements. Our clients get the best of every provider through one trusted partner, without vendor lock-in.</p>
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
                   style="background:#ffffff;border-radius:8px;border:1px solid #c7e6ff;border-left:3px solid #4ddcc3">
              <tr>
                <td style="padding:20px 22px" bgcolor="#ffffff">
                  <table cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tr>
                      <td width="48" valign="top" style="padding:0 14px 0 0">
                        <table cellpadding="0" cellspacing="0" border="0">
                          <tr><td width="36" height="36" align="center" bgcolor="#4ddcc3"
                                  style="width:36px;height:36px;border-radius:50%;background:#4ddcc3;text-align:center;line-height:36px">
                            <font color="#152230" face="Montserrat,Arial,sans-serif"><b style="font-size:15px">{i}</b></font>
                          </td></tr>
                        </table>
                      </td>
                      <td valign="middle">
                        <p style="margin:0;font-size:15px;font-weight:700;font-family:Montserrat,Arial,sans-serif;line-height:1.3">
                          <font color="#152230"><b>{s['title']}</b></font>
                        </p>
                        <p style="margin:4px 0 0 0;font-size:11px;font-family:Montserrat,Arial,sans-serif;text-transform:uppercase;letter-spacing:0.1em">
                          <font color="#4ddcc3">{s['source']}</font>
                        </p>
                      </td>
                    </tr>
                    <tr>
                      <td colspan="2" style="padding-top:10px">
                        <p style="margin:0;font-size:14px;font-family:Manrope,Arial,sans-serif;line-height:1.6">
                          <font color="#5a5a5a">{s['glance']}</font>
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
<body style="margin:0;padding:0;background-color:#f5fbff;font-family:Manrope,Arial,Helvetica,sans-serif" bgcolor="#f5fbff">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f5fbff" style="background-color:#f5fbff">
<tr><td align="center" style="padding:32px 16px;background-color:#f5fbff">
  <table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%">

    <!-- HEADER -->
    <tr>
      <td style="background:#152230;border-radius:12px 12px 0 0;padding:40px 36px 36px;border-bottom:3px solid #4ddcc3" bgcolor="#152230">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td>
              <p style="margin:0 0 8px 0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;font-family:Montserrat,Arial,sans-serif;font-weight:600">
                <font color="#4ddcc3">Weekly Briefing &nbsp;·&nbsp; {today}</font>
              </p>
              <p style="margin:0;font-size:28px;font-weight:800;font-family:Montserrat,Arial,sans-serif;line-height:1.2">
                <font color="#4ddcc3"><b>This Week</b></font><font color="#ffffff"><b> in AI</b></font>
              </p>
              <p style="margin:12px 0 0 0;font-size:14px;font-family:Manrope,Arial,sans-serif;line-height:1.6">
                <font color="#cccccc">{data['intro']}</font>
              </p>
            </td>
            <td width="80" align="right" valign="top">
              <p style="margin:0;font-size:22px;font-weight:800;font-family:Montserrat,Arial,sans-serif;letter-spacing:-0.03em;line-height:1">
                <font color="#4ddcc3"><b>ramsac</b></font>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- BODY -->
    <tr>
      <td style="background:#f5fbff;padding:28px 32px 8px;border-left:1px solid #c7e6ff;border-right:1px solid #c7e6ff" bgcolor="#f5fbff">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding:28px 0 20px 0;border-top:1px solid #c7e6ff">
              <p style="margin:0;font-size:11px;letter-spacing:0.12em;text-transform:uppercase;font-family:Montserrat,Arial,sans-serif;font-weight:700">
                <font color="#4ddcc3">Top 5 at a Glance — click to read the full edition online</font>
              </p>
            </td>
          </tr>
          {story_rows(data['stories'])}
        </table>
      </td>
    </tr>

    <!-- READ ONLINE BUTTON -->
    <tr>
      <td style="background:#f5fbff;padding:0 32px 24px;border-left:1px solid #c7e6ff;border-right:1px solid #c7e6ff" bgcolor="#f5fbff">
        <table cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td align="center">
              <a href="{digest_url}" target="_blank"
                 style="display:inline-block;background:#4ddcc3;color:#152230;font-family:Montserrat,Arial,sans-serif;font-size:13px;font-weight:700;text-decoration:none;padding:12px 28px;border-radius:8px">
                <font color="#152230"><b>Read full edition online &rarr;</b></font>
              </a>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td style="background:#152230;border-radius:0 0 12px 12px;padding:28px 36px;border:1px solid #152230" bgcolor="#152230">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td>
              <p style="margin:0 0 4px 0;font-size:15px;font-weight:700;font-family:Montserrat,Arial,sans-serif">
                <font color="#ffffff"><b>Stay curious, stay ahead.</b></font>
              </p>
              <p style="margin:0;font-size:13px;font-family:Manrope,Arial,sans-serif">
                <font color="#999999">See you next week.</font>
              </p>
            </td>
            <td align="right">
              <p style="margin:0;font-size:11px;font-weight:800;font-family:Montserrat,Arial,sans-serif;letter-spacing:-0.02em">
                <font color="#4ddcc3"><b>ramsac</b></font>
              </p>
              <p style="margin:2px 0 0 0;font-size:10px;font-family:Manrope,Arial,sans-serif">
                <font color="#666666">Weekly AI Briefing</font>
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


def write_index(directory, html_files):
    """Generate hub index.html with navigation and edition archive."""
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
            f'      <div class="edition-date">{label}</div>\n'
            f'      <a class="view-btn" href="{f}">View &rarr;</a>\n'
            f'    </div>'
        )
    cards_html = "\n".join(cards)

    nav = _nav_html("digest")
    nav_css = _nav_css()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Austen — AI Briefing Hub by RAMSAC</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&family=Manrope:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: {BG_MAIN}; font-family: Manrope, Arial, sans-serif; color: {TEXT}; min-height: 100vh; }}
  a {{ color: inherit; text-decoration: none; }}
  {nav_css}
  .page-body {{ max-width: 720px; margin: 0 auto; padding: 40px 16px 60px; }}
  .hub-hero {{ background: linear-gradient(135deg, {NAVY} 0%, {DARK_TEAL} 100%); border-radius: 12px; padding: 36px 36px 32px; border-bottom: 3px solid {ACCENT}; margin-bottom: 32px; display: flex; align-items: flex-end; justify-content: space-between; }}
  .hub-hero h1 {{ font-family: Montserrat, Arial, sans-serif; font-size: 26px; font-weight: 800; color: #fff; line-height: 1.2; }}
  .hub-hero h1 span {{ color: {ACCENT}; }}
  .hub-hero-sub {{ font-family: Montserrat, Arial, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: {ACCENT}; font-weight: 600; margin-bottom: 8px; }}
  .hub-hero-brand {{ font-family: Montserrat, Arial, sans-serif; font-size: 20px; font-weight: 800; color: {ACCENT}; letter-spacing: -0.03em; }}
  .hub-tiles {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 32px; }}
  .hub-tile {{ background: {BG_CARD}; border: 1px solid {BORDER}; border-left: 3px solid {ACCENT}; border-radius: 10px; padding: 20px 22px; display: flex; flex-direction: column; gap: 8px; transition: box-shadow 0.15s; }}
  .hub-tile:hover {{ box-shadow: 0 4px 20px rgba(21,34,48,0.08); }}
  .hub-tile-label {{ font-family: Montserrat, Arial, sans-serif; font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; font-weight: 700; color: {ACCENT}; }}
  .hub-tile-title {{ font-family: Montserrat, Arial, sans-serif; font-size: 16px; font-weight: 800; color: {NAVY}; }}
  .hub-tile-desc {{ font-size: 13px; color: {MUTED}; line-height: 1.6; flex: 1; }}
  .hub-tile-btn {{ display: inline-block; background: {ACCENT}; color: {NAVY}; font-family: Montserrat, Arial, sans-serif; font-size: 11px; font-weight: 700; padding: 7px 14px; border-radius: 6px; align-self: flex-start; transition: opacity 0.15s; }}
  .hub-tile-btn:hover {{ opacity: 0.85; }}
  .section-label {{ font-family: Montserrat, Arial, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: {ACCENT}; font-weight: 700; border-top: 1px solid {BORDER}; padding-top: 24px; margin-bottom: 20px; }}
  .edition-card {{ background: {BG_CARD}; border: 1px solid {BORDER}; border-left: 3px solid {ACCENT}; border-radius: 8px; padding: 16px 20px; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; }}
  .edition-date {{ font-family: Montserrat, Arial, sans-serif; font-size: 14px; font-weight: 700; color: {NAVY}; }}
  .view-btn {{ display: inline-block; background: {ACCENT}; color: {NAVY}; font-family: Montserrat, Arial, sans-serif; font-size: 12px; font-weight: 700; text-decoration: none; padding: 8px 16px; border-radius: 6px; white-space: nowrap; transition: opacity 0.15s; }}
  .view-btn:hover {{ opacity: 0.85; }}
  .footer {{ background: {NAVY}; border-radius: 10px; padding: 22px 32px; margin-top: 32px; display: flex; align-items: center; justify-content: space-between; }}
  .footer p {{ font-size: 12px; color: rgba(255,255,255,0.5); font-family: Manrope, Arial, sans-serif; }}
  .footer-brand {{ font-family: Montserrat, Arial, sans-serif; font-size: 18px; font-weight: 800; color: {ACCENT}; letter-spacing: -0.02em; }}
</style>
</head>
<body>
{nav}
<div class="page-body">
  <div class="hub-hero">
    <div>
      <p class="hub-hero-sub">Austen &middot; AI Knowledge Hub</p>
      <h1><span>This Week</span> in AI</h1>
    </div>
    <div class="hub-hero-brand">ramsac</div>
  </div>
  <div class="hub-tiles">
    <a class="hub-tile" href="glossary.html">
      <div class="hub-tile-label">Explore</div>
      <div class="hub-tile-title">AI Glossary</div>
      <div class="hub-tile-desc">Navigate key AI concepts as a connected constellation. Click any term to see its definition and related ideas.</div>
      <span class="hub-tile-btn">Open glossary &rarr;</span>
    </a>
    <a class="hub-tile" href="battlecards.html">
      <div class="hub-tile-label">Know your landscape</div>
      <div class="hub-tile-title">Battle Cards</div>
      <div class="hub-tile-desc">Understand the major AI players, what they offer, and how RAMSAC positions against them in client conversations.</div>
      <span class="hub-tile-btn">View battle cards &rarr;</span>
    </a>
  </div>
  <p class="section-label">All Editions</p>
{cards_html}
  <div class="footer">
    <p>Stay curious, stay ahead.</p>
    <div class="footer-brand">ramsac</div>
  </div>
</div>
</body>
</html>"""

    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as f:
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
