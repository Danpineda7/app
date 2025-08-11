import streamlit as st
import google.generativeai as genai

def load_custom_styles():
    with open("style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Load custom styles
load_custom_styles()


# --- 🔑 Configure API Key ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# --- 🔮 Load Gemini Model ---
model = genai.GenerativeModel(model_name="models/gemini-2.5-flash")
chat = model.start_chat(history=[])

# --- SESSION STATE ---
if "step" not in st.session_state:
    st.session_state.step = 1
if "company_info" not in st.session_state:
    st.session_state.company_info = ""
if "topic_context" not in st.session_state:
    st.session_state.topic_context = ""
if "chosen_topic" not in st.session_state:
    st.session_state.chosen_topic = ""
if "related_keywords" not in st.session_state:
    st.session_state.related_keywords = ""
if "word_range" not in st.session_state:
    st.session_state.word_range = "800–1200"
if "blog_output" not in st.session_state:
    st.session_state.blog_output = ""
if "trend_list" not in st.session_state:
    st.session_state.trend_list = []

# --- STEP 1: Company Website Input ---
if st.session_state.step == 1:
    st.title("🚀 AI Blog Generator")
    st.subheader("Step 1: Learn About Your Company")

    website = st.text_input("Please enter your company website (required):", "")

    if st.button("Analyze Website"):
        if not website.strip():
            st.warning("🚨 Please enter a company website before continuing.")
        else:
            with st.spinner("⏳ We are reviewing your company website to learn about you..."):
                website_prompt = f"""
You are now learning about a company through its website: {website}

Use this to understand the company in general — its purpose, audience, industry, and market position.
Then extract:
- Tone of voice
- Writing style
- Brand values
- Services offered
- Common vocabulary and messaging

Use this understanding in all future outputs.
"""
                try:
                    response = chat.send_message(website_prompt)
                    if not response.text.strip():
                        raise ValueError("Empty response")
                    st.session_state.company_info = website_prompt
                    st.success("✅ Company understanding completed.")
                    st.session_state.step = 2
                except Exception:
                    st.warning("⚠️ Couldn't process the website. Please describe your company manually.")
                    st.session_state.step = "fallback"

# --- STEP 1 (Fallback): Manual Company Description ---
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

# --- STEP 2: Trend Discovery ---
if st.session_state.step == 2:
    st.title("📈 Step 2: Trend Discovery")

    choice = st.radio("What would you like to base the trend research on?", ["Specific Topic", "Industry", "Both"])

    keyword = industry = ""

    if choice == "Specific Topic":
        keyword = st.text_input("Enter a specific topic:")
        if keyword:
            st.session_state.topic_context = f"Topic: {keyword}"

    elif choice == "Industry":
        industry = st.text_input("Enter an industry:")
        if industry:
            st.session_state.topic_context = f"Industry: {industry}"

    elif choice == "Both":
        keyword = st.text_input("Enter a topic:")
        industry = st.text_input("Enter an industry:")
        if keyword and industry:
            st.session_state.topic_context = f"Topic: {keyword} | Industry: {industry}"

    if st.button("Generate Topics"):
        with st.spinner("🔍 Gemini is analyzing your inputs and generating trending blog ideas..."):
            trend_prompt = f"""
You are an SEO strategist and expert blog planner for the following company:

{st.session_state.company_info}

Based on this company's brand and the following input:
{st.session_state.topic_context}

Suggest 5–10 SEO-friendly, high-interest blog post ideas that:
- Reflect current search and market trends
- Are relevant to the company’s audience and services
- Could perform well in organic search and social media
- Sound natural and aligned with the company’s tone and content style

Return ONLY the list, no extra commentary.
"""
            response = chat.send_message(trend_prompt)
            st.session_state.trend_list = response.text.strip().split("\n")
            st.session_state.step = 3
            st.rerun()

# --- STEP 3: Topic Selection ---
if st.session_state.step == 3:
    st.title("🧠 Step 3: Choose a Blog Topic")
    st.markdown("### 💡 Gemini-suggested trending topics:")

    selected = st.radio("Select one topic:", options=[t.strip() for t in st.session_state.trend_list])

    if st.button("Confirm Topic"):
        with st.spinner("🧠 Processing your selected topic..."):
            st.session_state.chosen_topic = selected.strip()
            st.session_state.step = 4
            st.rerun()

# --- STEP 4: SEO Keywords & Blog Length ---
if st.session_state.step == 4:
    st.title("🔑 Step 4: Keywords & Blog Length")
    st.markdown(f"### Selected Topic: **{st.session_state.chosen_topic}**")

    # 🔒 Only generate keywords once
    if "keywords_generated" not in st.session_state or not st.session_state.keywords_generated:
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
            st.session_state.keywords_generated = True  # ✅ prevent re-running

    st.markdown("### ✅ Related SEO Keywords:")
    st.code(st.session_state.related_keywords)

    word_option = st.radio("Choose blog post length:", ["400–800", "800–1200", "1200–1500"])
    st.session_state.word_range = word_option

    if st.button("Generate Blog Post"):
        with st.spinner("✍️ Creating your SEO-optimized blog post..."):
            blog_prompt = f"""
You are an experienced SEO expert and content strategist.

Your task is to write a high-performing, SEO-optimized blog post for a company whose tone, audience, and style you've already learned.

Topic: **{st.session_state.chosen_topic}**

You must use the following SEO keywords:
{st.session_state.related_keywords}

⚠️ Important instructions:
- DO NOT keyword-stuff or force exact matches unnaturally (e.g., “car repair near me”).
- You MAY adjust or rephrase keywords slightly to ensure human readability.
- Use keywords strategically in:
  • Title
  • Meta description
  • First paragraph
  • One or two H2 subheadings
  • Conclusion/CTA

The blog must:
- Be {st.session_state.word_range} words long
- Be structured with H2 subheadings and short paragraphs
- Use clear, persuasive, conversational language
- Include a compelling SEO title and meta description (under 160 characters)
- End with a clear and strong call to action
- Reflect the company’s tone, values, and audience expectations
"""
            response = chat.send_message(blog_prompt)
            st.session_state.blog_output = response.text.strip()
            st.session_state.step = 5
            st.rerun()

# --- STEP 5: Final Blog Output --- 
if st.session_state.step == 5:
    st.title("📄 Final Blog Output")

    st.markdown("### ✅ Your Blog Post:")
    st.markdown(st.session_state.blog_output, unsafe_allow_html=True)

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

import re

# --- STEP 6: Alternative Formats ---
if st.session_state.step == 6:
    st.title("🪄 Repurposed Content Formats")

    format_prompt = f"""
You are a marketing copywriter creating platform-specific content.

Your task: Produce two separate posts based on the blog below.

---

### 1. Google Business Profile (GBP) Post
- **MUST be 750 characters or less** (including spaces)
- One paragraph only
- Professional, friendly, local-focused tone
- Clear urgency and a strong CTA
- No emojis, no hashtags
- Output the character count in brackets at the end

---

### 2. Social Media Post (Facebook or Instagram)
- **MUST be 900 characters or less** (including spaces)
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

    # --- Extract Sections Safely ---
    gbp_post = ""
    social_post = ""

    match = re.search(r"1\..*?(?=2\.)", st.session_state.alt_formats, re.DOTALL)
    if match:
        gbp_post = match.group(0).strip()

    match = re.search(r"2\..*", st.session_state.alt_formats, re.DOTALL)
    if match:
        social_post = match.group(0).strip()

    # --- Show Outputs ---
    st.markdown("---")
    st.subheader("📍 Google Business Profile Post")
    st.markdown(gbp_post)

    st.subheader("📣 Social Media Post")
    st.markdown(social_post)

    if st.button("🔁 Start Over"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

