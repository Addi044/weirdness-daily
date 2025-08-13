import os, re, json, textwrap, hashlib, datetime
from urllib.parse import urlparse
import feedparser
import trafilatura
import yaml

# ---------- Config ----------
N_POSTS = 5
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "site")
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "template.html")
SOURCES_PATH = os.path.join(os.path.dirname(__file__), "sources.yaml")

# ---------- Helpers ----------
def domain(u): 
    try:
        return urlparse(u).netloc.replace("www.","")
    except Exception:
        return ""

def stable_id(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]

WEIRD_KEYWORDS = [
    # core
    "weird","odd","bizarre","unusual","strange","peculiar","quirky","surreal",
    "mystery","mysterious","escaped","giant","miniature","ufo","alien",
    "zoo","animal","bandit","toilet","cheese","squirrel","bear","goat",
    "lottery","guinness","world record","strange news","odd news","curious",
    "unexplained","viral","prank","museum","cryptid","haunted","sighting"
]

def score_weird(title, text):
    t = (title + " " + text[:1200]).lower()
    score = 0
    for k in WEIRD_KEYWORDS:
        if k in t:
            score += 1
    if len(text) > 300:  # has some substance
        score += 1
    # penalize grim topics
    if re.search(r"\b(murder|war|assault|shooting|tragedy|suicide|hate)\b", t):
        score -= 5
    return score


def score_weird(title, text):
    t = (title + " " + text[:1200]).lower()
    score = sum(k in t for k in WEIRD_KEYWORDS)
    if len(text) > 400: score += 1
    if re.search(r"\b(murder|war|assault|tragedy|shooting)\b", t): score -= 5
    return score

def load_sources():
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["rss"]

def collect_entries(rss_urls, per_feed=25):
    seen = set()
    out = []
    for u in rss_urls:
        try:
            feed = feedparser.parse(u)
            for e in feed.entries[:per_feed]:
                link  = e.get("link") or ""
                title = (e.get("title") or "").strip()
                desc  = (e.get("summary") or e.get("description") or "").strip()
                if not link or (link in seen):
                    continue
                seen.add(link)
                out.append({"title": title, "link": link, "summary_hint": desc})
        except Exception:
            continue
    return out

def extract_article(url):
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=True)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False) or ""
        return text.strip()
    except Exception:
        return ""

# ---------- OpenAI summarization ----------
def summarize_openai(text, src_domain):
    # Keep prompt compact; aim ~60-90 words; neutral & playful.
    import openai
    openai.api_key = os.getenv("OPENAI_API_KEY")
    prompt = (
        "Summarize this odd/quirky news item in 1–2 punchy sentences (max ~70 words). "
        "Be light and playful but not mean or sensitive. Include 0–1 emoji at most. "
        f"End with '— via {src_domain}'.\n\nTEXT:\n{text[:4000]}"
    )
    # Use Chat Completions (works with gpt-4o-mini, gpt-4.1-mini, etc.)
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.6,
        max_tokens=120,
    )
    return resp.choices[0].message["content"].strip()

# ---------- Build HTML ----------
def render(posts):
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        tpl = f.read()
    articles_html = []
    for p in posts:
        block = f"""
        <article>
          <a href="{p['link']}" target="_blank" rel="noopener">
            <h1>{p['title']}</h1>
          </a>
          <div>{p['summary']}</div>
          <div class="src">{domain(p['link'])}</div>
        </article>
        """
        articles_html.append(block)
    html = tpl.replace("{{POSTS}}", "\n".join(articles_html))
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    html = html.replace("{{DATE}}", now)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

def main():
    entries = collect_entries(load_sources())
    candidates = []
    for it in entries:
        text = extract_article(it["link"])
        if not text:
            text = it.get("summary_hint", "")
        if not text:
            continue
        s = score_weird(it["title"], text)
        if s >= 1:  # passable weirdness
            candidates.append((s, it, text))
    # rank best-first, then take top N
    candidates.sort(key=lambda x: -x[0])
    # cap per-domain so one source can't dominate
    domain_cap = 2
    picked = []
    per_domain = {}
    
    for _, it, text in candidates:
        d = domain(it["link"])
        if per_domain.get(d, 0) >= domain_cap:
            continue
        picked.append((it, text))
        per_domain[d] = per_domain.get(d, 0) + 1
        if len(picked) >= N_POSTS:
            break

    top = picked

    posts = []
    for _, it, text in top:
        try:
            summ = summarize_openai(text, domain(it["link"]))
        except Exception as e:
            summ = textwrap.shorten(text, width=180, placeholder="…")
        posts.append({"title": it["title"], "link": it["link"], "summary": summ})

    render(posts)

if __name__ == "__main__":
    main()
