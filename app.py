# app.py
# ---------------------------------------------
# AI Blog Generator with Internal Link Suggestions
# ---------------------------------------------
import streamlit as st
import google.generativeai as genai
import json
import re
import time
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, urldefrag
from bs4 import BeautifulSoup

# -----------------------
# Styling
# -----------------------
def load_custom_styles():
    try:
        with open("style.css") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass

load_custom_styles()

# -----------------------
# Gemini setup
# -----------------------
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel(model_name="models/gemini-2.5-flash")
chat = model.start_chat(history=[])

# -----------------------
# Session state
# -----------------------
defaults = {
    "step": 1,
    "company_info": "",
    "topic_context": "",
    "chosen_topic": "",
    "related_keywords": "",
    "word_range": "800–1200",
    "blog_output": "",
    "trend_list": [],
    "keywords_generated": False,
    "site_inventory": [],
    "internal_links": [],
    "alt_formats": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -----------------------
# Site discovery helpers
# -----------------------
def _norm(u: str) -> str:
    u = urldefrag(u)[0]
    if u.endswith("/"):
        u = u[:-1]
    return u

def _same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc

def discover_sitemaps(base_url: str, timeout: int = 10):
    out = {urljoin(base_url, "/sitemap.xml")}
    try:
        r = requests.get(urljoin(base_url, "/robots.txt"), timeout=timeout)
        if r.ok:
            for line in r.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    out.add(line.split(":", 1)[1].strip())
    except Exception:
        pass
    return list(out)

def parse_sitemap(sm_url: str, timeout: int = 10, cap: int = 500):
    urls = []
    try:
        r = requests.get(sm_url, timeout=timeout)
        if not r.ok:
            return []
        root = ET.fromstring(r.content)
        ns = {"ns": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
        # sitemapindex or urlset
        if root.tag.endswith("sitemapindex"):
            locs = root.findall(".//ns:loc", ns) if ns else root.findall(".//loc")
            for p in locs:
                if p is not None and p.text:
                    urls += parse_sitemap(p.text.strip(), timeout=timeout, cap=cap)
        else:
            locs = root.findall(".//ns:loc", ns) if ns else root.findall(".//loc")
            for p in locs[:cap]:
                if p is not None and p.text:
                    urls.append(_norm(p.text.strip()))
    except Exception:
        return []
    return urls[:cap]

def fetch_page_meta(u: str, timeout: int = 10):
    try:
        r = requests.get(u, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok or "text/html" not in r.headers.get("Content-Type", ""):
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        title = (soup.title.string or "").strip() if soup.title else ""
        md = soup.find("meta", attrs={"name": "description"})
        desc = (md.get("content", "").strip() if md else "")
        h1 = soup.find("h1")
        h1_text = h1.get_text(" ", strip=True) if h1 else ""
        return {"url": _norm(u), "title": title, "description": desc, "h1": h1_text}
    except Exception:
        return None

def polite_crawl(seed: str, max_pages: int = 60, delay: float = 0.4, excludes=None):
    excludes = excludes or []
    q = [_norm(seed)]
    seen = set(q)
    pages = []
    while q and len(pages) < max_pages:
        u = q.pop(0)
        meta = fetch_page_meta(u)
        if meta:
            pages.append(meta)
        try:
            r = requests.get(u, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if not r.ok:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                v = _norm(urljoin(u, a["href"]))
                if not _same_host(v, seed):
                    continue
                if any(pat in v for pat in excludes):
                    continue
                if v not in seen:
                    seen.add(v)
                    q.append(v)
            time.sleep(delay)
        except Exception:
            continue
    return pages

@st.cache_data(show_spinner=False)
def build_site_inventory(website: str, max_pages: int = 80, excludes=None):
    excludes = excludes or []
    # Try sitemaps first
    inventory = []
    for sm in discover_sitemaps(website):
        urls = parse_sitemap(sm, cap=max_pages * 2)
        if urls:
            for u in urls[:max_pages]:
                m = fetch_page_meta(u)
                if m:
                    inventory.append(m)
            break
    # Fallback: crawl
    if not inventory:
        inventory = polite_crawl(website, max_pages=max_pages, excludes=excludes)
    # Prioritize likely “money” pages
    priority_words = ("service", "services", "product", "solutions", "pricing", "features", "case", "contact", "about")
    inventory.sort(key=lambda x: (0 if any(w in x["url"] for w in priority_words) else 1, len(x["url"])))
    # De-dupe
    seen = set()
    out = []
    for p in inventory:
        if p["url"] in seen:
            continue
        seen.add(p["url"])
        out.append(p)
    return out

# -----------------------
# STEP 1: Company Website
# -----------------------
if st.session_state.step == 1:
    st.title("🚀 AI Blog Generator")
    st.subheader("Step 1: Learn About Your Company")

    website = st.text_input("Please enter your company website (required):", "")

    if st.button("Analyze Website"):
        if not website.strip():
            st.warning("🚨 Please enter a company website before continuing.")
        else:
            with st.spinner("⏳ Reviewing your company website to learn about you..."):
                website_prompt = f"""
You are reviewing the company's website at: {website}

IMPORTANT:
1. First, extract and summarize actual visible homepage and top-level content before drawing conclusions.
   - Identify brand name, tagline, hero section, service/product descriptions, industries served, and any About Us info.
   - Quote short excerpts of actual text when possible.

2. Do NOT guess the meaning of abbreviations in the domain or company name unless clearly supported by on-page evidence.
   (For example, "MS" could mean many things — only assign meaning if explicitly stated in the site's content.)

3. Base your analysis ONLY on observed on-page content from this website.
   Do not use assumptions from the domain name or external sources.
   If uncertain, clearly state that uncertainty.

OUTPUT:
- Company overview (based strictly on visible content)
- Tone of voice
- Writing style
- Brand values
- Services or products offered
- Common vocabulary and messaging

This company understanding will be used for all future outputs.
"""
                try:
                    response = chat.send_message(website_prompt)
                    if not response.text or not response.text.strip():
                        raise ValueError("Empty response")

                    # ✅ Save the MODEL'S OUTPUT, not the prompt
                    st.session_state.company_info = response.text.strip()
                    st.success("✅ Company understanding completed.")

                    # Build site inventory here so we can use it later automatically
                    with st.spinner("🔎 Scanning your website for internal link targets..."):
                        st.session_state.site_inventory = build_site_inventory(
                            website=website,
                            max_pages=80,
                            excludes=["/wp-json/", "?", "/tag/", "/category/", "/feed/", "/cart", "/account"]
                        )
                        if st.session_state.site_inventory:
                            st.info(f"Found {len(st.session_state.site_inventory)} internal pages for linking.")
                        else:
                            st.warning("No internal pages found. Internal link suggestions may be empty.")

                    st.session_state.step = 2
                    st.rerun()

                except Exception:
                    st.warning("⚠️ Couldn't process the website. Please describe your company manually.")
                    # Still attempt inventory so links work later
                    with st.spinner("🔎 Attempting to scan your website for internal link targets..."):
                        try:
                            st.session_state.site_inventory = build_site_inventory(
                                website=website,
                                max_pages=80,
                                excludes=["/wp-json/", "?", "/tag/", "/category/", "/feed/", "/cart", "/account"]
                            )
                        except Exception:
                            st.session_state.site_inventory = []
                    st.session_state.step = "fallback"

# -----------------------
# STEP 1 (Fallback)
# -----------------------
if st.session_state.step == "fallback":
    st.subheader("📝 Manual Company Description")
    fallback = st.text_area("Please describe your company (and optionally a blog/post sample):", height=200)

    if st.button("Submit Description"):
        if not fallback.strip():
            st.warning("🚨 Please provide a description before continuing.")
        else:
            fallback_text = f"""
Here’s a description of the company and sample content:

\"\"\"{fallback}\"\"\"

Use this to understand the company’s:
- Voice
- Values
- Audience
- Content tone
- Style
- Messaging
"""
            chat.send_message(fallback_text)
            st.session_state.company_info = fallback_text
            st.success("✅ Company info submitted.")
            st.session_state.step = 2
            st.rerun()

# -----------------------
# --- STEP 2: Trend Discovery (At least one required, multi-signal) ---
if st.session_state.step == 2:
    st.title("📈 Step 2: Trend Discovery")

    st.markdown(
        "Tell us what to base the **trending topic research** on. "
        "You can provide **one or more** signals below (at least one is required)."
    )

    # Inputs (all optional individually; we'll require at least one overall)
    industry = st.text_input("Industry / niche")
    audience = st.text_input("Primary target audience")
    region   = st.text_input("Region / market")
    seasonal = st.text_input("Seasonal or event focus")
    seed_topic = st.text_input("Seed topic to explore")

    # Save (so later steps/prompts can reuse)
    st.session_state.industry_focus = industry.strip()
    st.session_state.target_audience = audience.strip()
    st.session_state.geo_focus = region.strip()
    st.session_state.seasonal_focus = seasonal.strip()
    st.session_state.seed_topic = seed_topic.strip()

    if st.button("Generate Topics"):
        # Require at least one non-empty signal
        provided = {
            "Industry": st.session_state.industry_focus,
            "Audience": st.session_state.target_audience,
            "Region":   st.session_state.geo_focus,
            "Seasonal": st.session_state.seasonal_focus,
            "Seed":     st.session_state.seed_topic,
        }
        non_empty = {k: v for k, v in provided.items() if v}
        if not non_empty:
            st.warning("🚨 Please fill **at least one** field (Industry, Audience, Region, Seasonal, or Seed topic).")
        else:
            with st.spinner("🔍 Researching *current* trends and generating topic ideas..."):
                from datetime import datetime
                today = datetime.now().strftime("%Y-%m-%d")

                # Build a compact “signals used” block
                signals_lines = "\n".join([f"- {k}: {v}" for k, v in non_empty.items()])

                trending_prompt = f"""
You are an expert SEO strategist with deep knowledge of **current** search trends,
seasonality, news cycles, and social buzz. Generate **8–12 high-potential, trending**
blog topics that are relevant **right now** ({today}).

COMPANY CONTEXT (voice/tone/services to follow):
{st.session_state.company_info}

SIGNALS TO USE (only these were provided; do not invent others):
{signals_lines}

RESEARCH GUIDANCE
- Lean on current search interest, seasonality, recent news, and social chatter for the signals above.
- Prefer angles the company can credibly cover (avoid speculation).
- Mix fast-moving trends with near-evergreen topics that are currently peaking.

OUTPUT RULES
- Return **only** a clean **numbered list** of 8–12 topics; no extra text.
- Each topic 6–12 words, compelling but not clickbait.
- Keep on-brand and aligned with the provided signals.
"""
                response = chat.send_message(trending_prompt)
                raw = (response.text or "").strip()

                import re
                topics = [re.sub(r"^\d+[\).\s-]*", "", t).strip(" -•\t") for t in raw.splitlines() if t.strip()]
                topics = topics[:12] if len(topics) > 12 else topics
                st.session_state.trend_list = topics

                if not topics:
                    st.warning("⚠️ No topics returned. Try adding one more signal (e.g., Industry + Audience).")
                else:
                    # Small UX touch: show what signals were used
                    st.info("Signals used: " + ", ".join(non_empty.keys()))
                    st.session_state.step = 3
                    st.rerun()

# -----------------------
# STEP 3: Topic Selection
# -----------------------
if st.session_state.step == 3:
    st.title("🧠 Step 3: Choose a Blog Topic")
    st.markdown("### 💡 Gemini-suggested trending topics:")

    selected = st.radio("Select one topic:", options=[t.strip() for t in st.session_state.trend_list])

    if st.button("Confirm Topic"):
        with st.spinner("🧠 Processing your selected topic..."):
            st.session_state.chosen_topic = selected.strip()
            st.session_state.step = 4
            st.rerun()

# -----------------------
# STEP 4: Keywords & All Inputs (pre-blog)
# -----------------------
if st.session_state.step == 4:
    st.title("🔑 Step 4: Keywords & Blog Settings")
    st.markdown(f"### Selected Topic: **{st.session_state.chosen_topic}**")

    # Generate keywords once
    if not st.session_state.keywords_generated:
        with st.spinner("🔍 Gemini is researching trending keywords..."):
            seo_prompt = f"""
You are an SEO expert.

Based on the topic: "{st.session_state.chosen_topic}"

Return a list of 5-10 trending, high-interest keywords that:
- Are actively searched
- Relate to the topic
- Help increase visibility in blog and social content
- Can be used for SEO and metadata

Return just the list. No extra commentary.
"""
            response = chat.send_message(seo_prompt)
            st.session_state.related_keywords = response.text.strip()
            st.session_state.keywords_generated = True

    st.markdown("### ✅ Related SEO Keywords:")
    st.code(st.session_state.related_keywords)

    # Additional inputs BEFORE creating the blog (so links are delivered with it)
      # Clarify this is word count and add your options
    st.markdown("**Choose approximate blog length (word count):**")

    length_choice = st.radio(
        label="Word count",
        options=["<400", "400–600", "600–800", "800–1000", ">1000"],
        index=2  # default to 600–800
    )

    # Map UI choice to a clear instruction for the model
    length_spec_map = {
        "<400": "less than 400 words (aim for 300–399)",
        "400–600": "between 400 and 600 words",
        "600–800": "between 600 and 800 words",
        "800–1000": "between 800 and 1000 words",
        ">1000": "more than 1000 words (aim for 1000–1300)",
    }

    # Store both the raw choice and the expanded spec
    st.session_state.word_range = length_choice
    st.session_state.word_spec = length_spec_map[length_choice]


    anchor_style = st.radio("Preferred anchor text style for internal links:",
                            ["Natural phrases", "Exact match keywords", "Mix"], index=0)

    num_links = st.slider("How many internal link suggestions?", 3, 8, 5)

    # (Optional) show what we discovered
    with st.expander("🔎 Pages discovered for internal linking (from your site)"):
        inv = st.session_state.site_inventory or []
        st.write(f"{len(inv)} pages found.")
        for p in inv[:50]:
            st.markdown(f"- **{p['title'] or p['h1'] or p['url']}**  \n  {p['url']}")

    if st.button("Generate Blog Post"):
        with st.spinner("✍️ Creating your SEO-optimized blog post with internal link plan..."):
            internal_pages_block = "\n".join(
                f"- URL: {p['url']}\n  Title: {p['title']}\n  H1: {p['h1']}\n  Description: {p['description']}"
                for p in (st.session_state.site_inventory or [])[:80]
            )

            blog_prompt = f"""
You are a senior SEO editor and brand copywriter. Write like a human, not a bot.

CONTEXT
- Company voice/tone/audience were learned earlier and must be followed.
- Topic: **{st.session_state.chosen_topic}**
- Target length: {st.session_state.word_spec}. Allow ±10% for natural flow.
- Keywords to use NATURALLY (no stuffing; variations allowed): 
{st.session_state.related_keywords}

INTERNAL LINK CANDIDATES (use ONLY these):
{internal_pages_block or "(none found)"}

GOALS
- Produce a search-worthy, helpful blog that demonstrates expertise and builds trust.
- Optimize for clicks from SERP and time-on-page while staying human and readable.

STRICT WRITING RULES
- Title: compelling, ≤60 characters. One H1 only (as the SEO title).
- Meta description: ≤155 characters, action-oriented, includes 1 primary concept.
- Structure: short intro hook; H2 sections with skimmable paragraphs (2–4 sentences each); include bullets or numbered steps where useful.
- Tone: confident, friendly, and plain-spoken. No clichés or fluff. Avoid over-promising or unverifiable claims.
- Style: use active voice; vary sentence length; avoid repetitive openings; no generic filler.
- Clarity: define any jargon in simple terms.
- Evidence: use practical tips/examples; do NOT fabricate data, prices, certifications, or quotes.
- CTA: 1 strong, specific CTA aligned with the brand and topic.
- Accessibility: avoid wall-of-text; prefer clear headings and lists.

SEO RULES
- Place 1–2 important keywords early (first 100 words) without forcing exact matches.
- Use semantic variations in H2s/H3s (no keyword spam).
- Include 3–5 FAQs at the end if they add value (optional).
- Do NOT invent outbound sources. No external links.

INTERNAL LINK PLAN
- Suggest {num_links} internal links from the provided inventory only.
- Anchor style: {anchor_style}. Anchors must read naturally inside the sentence.
- Link placement must be contextually helpful (not the first sentence of the article, not in the H1).
- Prefer high-intent pages (services, key products, pricing, cornerstone posts).
- Avoid duplicate target URLs and avoid linking to the homepage unless clearly best.
- Each suggestion must specify an exact insertion point tied to the content (refer to the H2 and paragraph number).
- If no suitable page exists for a concept, skip it (do not invent URLs).

OUTPUT FORMAT (exactly this, no extra text before/after)
===BLOG===
# <SEO Title (H1)>

<meta_description>...</meta_description>

<Body in Markdown with H2/H3, short paragraphs, and a final CTA>

===INTERNAL_LINKS_JSON===
[
  {{
    "anchor_text": "natural phrase that appears in the blog",
    "target_url": "https://...",
    "placement_note": "After H2 '...', paragraph 2. Link the phrase '...'.",
    "why": "≤15 words on value to reader"
  }}
]
"""

            response = chat.send_message(blog_prompt)
            text = response.text or ""

            # split sections
            parts = text.split("===INTERNAL_LINKS_JSON===")
            st.session_state.blog_output = parts[0].replace("===BLOG===", "").strip()

            st.session_state.internal_links = []
            if len(parts) > 1:
                raw_json = parts[1].strip()
                try:
                    st.session_state.internal_links = json.loads(raw_json)
                except Exception:
                    # try to extract JSON block if extra text wraps it
                    m = re.search(r"\[\s*\{.*\}\s*\]", raw_json, re.DOTALL)
                    if m:
                        try:
                            st.session_state.internal_links = json.loads(m.group(0))
                        except Exception:
                            st.session_state.internal_links = []

            st.session_state.step = 5
            st.rerun()

# -----------------------
# STEP 5: Final Blog Output + Internal Links
# -----------------------
if st.session_state.step == 5:
    st.title("📄 Final Blog Output")

    st.markdown("### ✅ Your Blog Post:")
    st.markdown(st.session_state.blog_output, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🔗 Internal Link Suggestions")
    links = st.session_state.internal_links or []
    if not links:
        st.info("No internal link suggestions were produced.")
    else:
        # Pretty print as a table
        def _safe(d, k): return d.get(k, "")
        rows = []
        for it in links:
            rows.append({
                "Anchor text": _safe(it, "anchor_text"),
                "Target URL": _safe(it, "target_url"),
                "Placement note": _safe(it, "placement_note"),
                "Why": _safe(it, "why"),
            })
        st.dataframe(rows, use_container_width=True)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔁 Start Over"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    with col2:
        if st.button("➡️ Repurpose as GBP + Social Post"):
            st.session_state.step = 6
            st.rerun()

# -----------------------
# STEP 6: Repurposed Formats
# -----------------------
if st.session_state.step == 6:
    st.title("🪄 Repurposed Content Formats")

    format_prompt = f"""
You are a marketing copywriter creating platform-specific content.

Your task: Produce two separate posts based on the blog below.

---

### 1. Google Business Profile (GBP) Post
- MUST be 750 characters or less (including spaces)
- One paragraph only
- Professional, friendly, local-focused tone
- Clear urgency and a strong CTA
- No emojis, no hashtags
- Output the character count in brackets at the end

---

### 2. Social Media Post (Facebook or Instagram)
- MUST be 900 characters or less (including spaces)
- Engaging, conversational tone
- Use emojis naturally
- Keep sentences short (max 12 words)
- 3–5 short paragraphs for easy reading
- Include exactly one question to encourage comments
- End with a CTA
- Add 3–5 relevant hashtags
- Output the character count in brackets at the end

---

📝 Blog Post Reference:
\"\"\"{st.session_state.blog_output}\"\"\"

⚠ IMPORTANT:
- Do not copy full sentences from the blog — rewrite concisely
- Ensure the character limits are respected
"""
    with st.spinner("💫 Creating alternative content formats..."):
        response = chat.send_message(format_prompt)
        st.session_state.alt_formats = response.text.strip()

    # Extract sections
    gbp_post = ""
    social_post = ""
    match = re.search(r"1\..*?(?=2\.)", st.session_state.alt_formats, re.DOTALL)
    if match:
        gbp_post = match.group(0).strip()
    match = re.search(r"2\..*", st.session_state.alt_formats, re.DOTALL)
    if match:
        social_post = match.group(0).strip()

    st.markdown("---")
    st.subheader("📍 Google Business Profile Post")
    st.markdown(gbp_post)

    st.subheader("📣 Social Media Post")
    st.markdown(social_post)

    if st.button("🔁 Start Over"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
