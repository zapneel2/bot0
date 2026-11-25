import os
import re
import json
import html
import requests

SUBREDDIT = "wallstreetbets"
GIST_ID = os.environ["GIST_ID"]
GIST_TOKEN = os.environ["GIST_TOKEN"]
HEADERS = {"User-Agent": "linux:wsb-x-bridge:v1.0 (by /u/local_builder_2026)"}

def fetch_latest_wsb_posts():
    url = f"https://reddit.com{SUBREDDIT}/new.json?limit=15"
    res = requests.get(url, headers=HEADERS, timeout=15)
    posts = []

    if res.status_code == 200:
        for child in res.json().get("data", {}).get("children", []):
            d = child["data"]
            if d.get("stickied") or d.get("over_18"):
                continue

            img_url = None
            post_url = d.get("url", "")

            # 1. Direct single image (i.redd.it / ://imgur.com)
            if any(post_url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
                img_url = post_url
            # 2. Reddit multi-image gallery -> grab first image
            elif d.get("is_gallery") and d.get("media_metadata"):
                first_id = next(iter(d["media_metadata"]))
                media = d["media_metadata"][first_id]
                if media.get("s", {}).get("u"):
                    img_url = html.unescape(media["s"]["u"])

            # Filter: only grab image/meme posts (skip pure text discussions if desired)
            if img_url:
                posts.append({
                    "id": d["id"],
                    "text": f"{d['title']}\n\n#wallstreetbets #stocks",
                    "image_url": img_url
                })
    else:
        # Fallback to Fastly-cached RSS feed if .json gets 429/403 on cloud IP
        rss = requests.get(f"https://reddit.com{SUBREDDIT}/new/.rss", headers=HEADERS, timeout=15)
        rss.raise_for_status()
        entries = re.findall(r"<entry>(.*?)</entry>", rss.text, re.DOTALL)
        for entry in entries[:10]:
            id_match = re.search(r"<id>t3_([a-z0-9]+)</id>", entry)
            title_match = re.search(r"<title>(.*?)</title>", entry)
            img_match = re.search(r'href="(https://i\.redd\.it/[^"]+)"', entry)
            if id_match and title_match and img_match:
                posts.append({
                    "id": id_match.group(1),
                    "text": f"{html.unescape(title_match.group(1))}\n\n#wallstreetbets #stocks",
                    "image_url": html.unescape(img_match.group(1))
                })

    return posts

def update_gist_queue():
    gist_api = f"https://github.com{GIST_ID}"
    gh_headers = {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    # Read existing queue & seen IDs from Gist
    gist_data = requests.get(gist_api, headers=gh_headers, timeout=15).json()
    raw_content = gist_data["files"]["x-queue.json"]["content"]
    state = json.loads(raw_content) if raw_content.strip() else {"seen_ids": [], "queue": []}

    seen = set(state.get("seen_ids", []))
    queue = state.get("queue", [])

    new_posts = fetch_latest_wsb_posts()
    added = 0

    for p in reversed(new_posts):  # Oldest-first so chronological order is preserved
        if p["id"] not in seen:
            seen.add(p["id"])
            queue.append(p)
            added += 1

    # Keep only last 100 seen IDs and cap pending queue at 10 items
    state["seen_ids"] = list(seen)[-100:]
    state["queue"] = queue[-10:]

    if added > 0:
        requests.patch(
            gist_api,
            headers=gh_headers,
            json={"files": {"x-queue.json": {"content": json.dumps(state, indent=2)}}},
            timeout=15
        ).raise_for_status()
        print(f"Added {added} new WSB post(s) to queue.")
    else:
        print("No new WSB image posts found.")

if __name__ == "__main__":
    update_gist_queue()
