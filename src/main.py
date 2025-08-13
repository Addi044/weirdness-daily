import os, re, textwrap, hashlib, datetime
from urllib.parse import urlparse

import feedparser
import requests
import trafilatura
import yaml

# ---------- Config ----------
N_POSTS = 5
PER_FEED = 25
DOMAIN_CAP = 2
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DEBUG = True  # turn on logging

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "site")
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "template.html")
SOURCES_PATH = os.path.join(os.path.dirname(__file__), "sources.yaml")
USER_AGENT = "Mozilla/5.0 (compatible; WeirdnessBot/1.0; +https://github.com/)"

def log(*args):
    if DEBUG:
        print(*args)

# ---------- Helpers ----------
def domain(u):
    try:
        return urlparse(u).netloc.replace("www.", "")
    except Exception:
        return ""

def stable_id(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]

WEIRD_KEYWORDS = [
    "weird","odd","bizarre","unusual","strange","peculiar","quirky","surreal","eccentric",
    "offbeat","freaky","curious","unexplained","mystery","mysterious","unorthodox","outlandish",
    "zany","whimsical","wacky","absurd","nonsensical","ridiculous","hilarious","comic","comical",
    "satire","spoof","parody","peculiarity","anomaly","curio","oddity",
    "escaped","zoo","animal","wildlife","bear","goat","cow","chicken","duck","ostrich","emu",
    "kangaroo","koala","llama","alpaca","sheep","pig","boar","squirrel","otter","penguin","parrot",
    "macaw","cockatoo","pigeon","rat","snake","python","cobra","alligator","crocodile","frog","toad",
    "turtle","tortoise","lizard","iguana","gecko","shark","whale","dolphin","seal","octopus","squid",
    "crab","lobster","spider","tarantula","scorpion","bee","wasp","hornet","insect","beetle","moth",
    "butterfly","moose","reindeer","hedgehog","badger","raccoon","opossum","beaver","walrus","mantis",
    "ferret","hamster","cat","kitten","dog","puppy","hyena","buffalo",
    "cheese","chocolate","pizza","burger","sandwich","taco","burrito","pasta","spaghetti","sushi",
    "ramen","noodle","tofu","cake","cookie","biscuit","donut","croissant","bagel","coffee","tea",
    "beer","wine","vodka","whiskey","cocktail","smoothie","milkshake","ice cream","dessert","snack",
    "ketchup","mustard","mayonnaise","pickle","hot sauce","cereal","breakfast","buffet","banquet",
    "guinness","world record","record-breaking","championship","contest","tournament","lottery",
    "jackpot","prize","winner","champion","medal","trophy","award","competition","challenge","stunt",
    "dare","marathon","speedrun","feat","largest","smallest","longest","shortest","fastest","slowest",
    "alien","ufo","extraterrestrial","spaceship","flying saucer","meteor","asteroid","planet","moon",
    "martian","space","haunted","ghost","cryptid","bigfoot","yeti","loch ness","nessie","sighting",
    "apparition","poltergeist","vampire","werewolf","witch","wizard","fairy","gnome","troll",
    "mythical","legend","folklore","superstition","omen","curse","ritual","ceremony","festival",
    "parade","eerie","spooky","ouija","seance","haunting","possession","enchanted","supernatural",
    "prank","hoax","meme","viral","trend","streaker","flashmob","cosplay","impersonator","lookalike",
    "superfan","obsession","eccentricity","collection","collector","hobbyist","invention","gadget",
    "contraption","device","innovation","prototype","robot","android","drone","3d-printed","hack",
    "lifehack","challenge","challenge accepted","stuntman","influencer","streamer","tiktoker",
    "youtuber","livestream","emote","emoji","shitpost","shitposting","copypasta","fanfic",
    "heist","bandit","thief","robber","burglary","smuggling","contraband","counterfeit","fraud",
    "scam","swindle","arrested","busted","police chase","mugshot","lawsuit","verdict","trial",
    "weird law","ban","prohibition","loophole","citation","fine","ordinance","bylaw","permit",
    "confiscated","seized","sting operation","undercover",
    "glitch","bug","easter egg","exploit","softlock","physics","ragdoll","ai-generated","deepfake",
    "prompt","chatbot","neural","quantum","laser","hologram","magnet","electromagnet","tesla coil",
    "arduino","raspberry pi","drone swarm","robot dog","boston dynamics",
    "toilet","bathroom","restroom","plumbing","sewer","underground","subway","tunnel","bridge",
    "monument","statue","sculpture","artwork","graffiti","museum","exhibit","installation",
    "performance","street art","installation art","fountain","roundabout","parking","traffic cone",
    "dumpster","elevator","escalator","vending machine","arcade","claw machine","jukebox","karaoke",
    "florida","bavaria","berlin","texas","alaska","siberia","iceland","antarctica","sahara","amazon",
    "outback","transylvania","village","hamlet","remote","island","desert","jungle","tundra","glacier",
    "mascot","pitch invasion","streak","streaker","zamboni","curling","sumo","cheerleader","air guitar",
    "chess boxing","bog snorkelling","wife-carrying","pumpkin regatta","cheese rolling","toe wrestling",
    "auction","auctioned","antique","relic","artifact","collectible","trading card","pokemon card",
    "mint condition","rare","one-of-a-kind","prototype","limited edition","garage sale","yard sale",
    "typo","engrish","misspelled","mistranslation","sign","billboard","warning sign","road sign",
    "menu fail","label fail","packaging fail","instructions fail"
]

BLOCKLIST_REGEX = re.compile(
    r"\b(murder|war|assault|shooting|tragedy|suicide|terror|rape|genocide|massacre)\b",
    re.IGNORECASE
)

def score_weird(title, text):
    t = (title + " " + text[:1200]).lower()
    score = 0
    for k in WEIRD_KEYWORDS:
        if k in t:
            score += 1
    if len(text) > 300:
        score += 1
    if BLOCKLIST_REGEX.search(t):
        score -= 5
    return score

def load_sources():
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("rss", [])

def collect_entries(rss_urls, per_feed=PER_FEED):
    seen = set()
    out = []
    total = 0
    for u in rss_urls:
        try:
            feed = feedparser.parse(u)
            n = len(feed.entries)
            log(f"[FEED] {u} -> {n} entries")
            for e in feed.entries[:per_feed]:
                link  = (e.get("link") or "").strip()
                title = (e.get("title") or "").strip()
                desc  = (e.get("summary") or e.get("description") or "").strip()
                if not link or not title or link in seen:
                    continue
                seen.add(link)
                out.append({"title": title, "link": link, "summary_hint": desc})
                total += 1
        except Exception as ex:
            log(f"[FEED ERROR] {u}: {ex}")
            continue
    log(f"[COLLECT] unique items: {total}")
    return out

def extract_article(url):
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=12)
        if not resp.ok or not resp.text:
            return ""
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False) or ""
        return text.strip()
    except Exception as ex:
        log(f"[EXTRACT ERROR] {url}: {ex}")
        return ""

# ---------- OpenAI summarization ----------
def summarize_openai(text, src_domain):
    api_key = os.getenv("OPENAI_API_KEY")
    base = textwrap.shorten(text.replace("\n"," "), width=180, placeholder="…") + f" — via {src_domain}"
    if not api_key:
        return base
    try:
        import openai
        openai.api_key = api_key
        prompt = (
            "Summarize this odd/quirky news item in 1–2 punchy sentences (max ~70 words). "
            "Be light and playful but not mean or insensitive. Include 0–1 emoji at most. "
            f"End with '— via {src_domain}'.\n\nTEXT:\n{text[:4000]}"
        )
        resp = openai.ChatCompletion.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=120,
        )
        return resp.choices[0].message["content"].strip()
    except Exception as ex:
        log(f"[OPENAI ERROR] {ex}")
        return base

# ---------- HTML ----------
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
        """.strip()
        articles_html.append(block)
    html = tpl.replace("{{POSTS}}", "\n\n".join(articles_html))
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    html = html.replace("{{DATE}}", now)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

def pick_with_cap(candidates, n=N_POSTS, cap=DOMAIN_CAP):
    picked = []
    per_domain = {}
    for _, it, text in candidates:
        d = domain(it["link"])
        if per_domain.get(d, 0) >= cap:
            continue
        picked.append((it, text))
        per_domain[d] = per_domain.get(d, 0) + 1
        if len(picked) >= n:
            break
    return picked

def main():
    entries = collect_entries(load_sources())
    log(f"[STEP] scoring full-text/desc candidates")

    candidates = []
    extracted = 0
    for it in entries:
        text = extract_article(it["link"])
        if text:
            extracted += 1
        if not text:
            text = it.get("summary_hint", "")
        if not text:
            continue
        s = score_weird(it["title"], text)
        if s >= 1:
            candidates.append((s, it, text))

    log(f"[STATS] extracted full text: {extracted}, candidates after scoring: {len(candidates)}")

    # rank best-first
    candidates.sort(key=lambda x: -x[0])

    # pick with per-domain cap
    picked = pick_with_cap(candidates, n=N_POSTS, cap=DOMAIN_CAP)

    # top up ignoring domain cap if needed
    if len(picked) < N_POSTS:
        used = {it["link"] for it, _ in picked}
        for _, it, text in candidates:
            if it["link"] in used:
                continue
            picked.append((it, text))
            used.add(it["link"])
            if len(picked) >= N_POSTS:
                break

    # LAST-RESORT FALLBACK: title/description-only scoring (no extraction)
    if len(picked) < N_POSTS:
        log("[FALLBACK] using title/description-only scoring to fill remaining slots")
        td_candidates = []
        for it in entries:
            ttext = (it.get("summary_hint") or it["title"]).strip()
            if not ttext:
                continue
            s = score_weird(it["title"], ttext)
            if s >= 1:
                td_candidates.append((s, it, ttext))
        td_candidates.sort(key=lambda x: -x[0])

        used = {it["link"] for it, _ in picked}
        for _, it, text in td_candidates:
            if it["link"] in used:
                continue
            picked.append((it, text))
            used.add(it["link"])
            if len(picked) >= N_POSTS:
                break

    log(f"[RESULT] picked: {len(picked)} (target {N_POSTS})")

    # summarize and render
    posts = []
    for it, text in picked[:N_POSTS]:
        summ = summarize_openai(text, domain(it["link"]))
        posts.append({"title": it["title"], "link": it["link"], "summary": summ})

    render(posts)

if __name__ == "__main__":
    main()
