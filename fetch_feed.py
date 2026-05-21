import os
import re
import urllib.request
from html.parser import HTMLParser
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from lxml import html as lxml_html
from urllib.parse import urljoin, urlparse

from vendor.readability import Document
from state import posts, indexes, pending

posts.update(open(f"content/{f}").readline().strip() for f in os.listdir("content"))


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip = 0
        self._pre = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title", "noscript"):
            self._skip += 1
        elif tag in ("pre", "code"):
            self._pre += 1
            self._parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title", "noscript"):
            self._skip -= 1
        elif tag in ("pre", "code"):
            self._pre -= 1
            self._parts.append("\n\n")
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                     "li", "blockquote", "hr", "tr", "br", "ul", "ol"):
            if not self._pre:
                self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self):
        text = "".join(self._parts)
        text = re.sub(r"\n[ \t]+\n", "\n\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"^[ \t]+|[ \t]+$", "", text, flags=re.MULTILINE)
        return text.strip()


def fetch(link):
    content = Document(
        urllib.request.urlopen(
            urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
        ).read().decode("utf-8"),
        url=link,
    ).summary()

    s = _Stripper()
    s.feed(content)
    plain = s.get_text()

    tree = lxml_html.fromstring(content)
    anchors = tree.findall(".//a")
    out_links = [urljoin(link, a.attrib["href"])
                 for a in anchors
                 if a.attrib.get("href") and not a.attrib["href"].startswith("#")]
    out_links = [u.split("#")[0] for u in out_links]

    a_text = sum(len(e.text or "") + len(e.tail or "") for e in tree.findall(".//a"))
    total = len(tree.text_content() or "")
    ld = a_text / max(total, 1)

    if len(plain) < 800:
        kind = "empty"
    elif ld > 0.4:
        kind = "link_page"
    else:
        kind = "post"
    return (kind, plain, out_links)


pending = deque(pending)

with ThreadPoolExecutor(max_workers=8) as pool:
    while pending:
        batch = [pending.popleft() for _ in range(min(len(pending), 8))]
        futures = {pool.submit(fetch, u): u for u in batch}
        for f in as_completed(futures):
            link = futures[f]
            kind, text, out_links = f.result()
            print(f"FETCH [{kind}]: {link}  ({len(text)} chars)")

            if kind == "post" and text:
                _slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", link)[:120]
                with open(f"content/{_slug}.txt", "w") as fp:
                    fp.write(f"{link}\n\n{text}")

            (posts if kind == "post" else indexes).add(link)

            for u in out_links:
                if urlparse(u).netloc.removeprefix("www.") in {"web.archive.org", "en.wikipedia.org", "youtube.com", "x.com", "twitter.com", "goodreads.com", "amazon.com", "reddit.com", "marketplace.visualstudio.com", "xkcd.com", "codeberg.org", "gist.github.com", "github.com"}:
                    continue
                if u not in posts and u not in indexes:
                    pending.append(u)
                    print(f"  NEW: {u}")

        with open("state.py.tmp", "w") as f:
            f.write(f"posts = {repr(posts)}\n")
            f.write(f"indexes = {repr(indexes)}\n")
            f.write(f"pending = {repr(list(pending))}\n")
        os.replace("state.py.tmp", "state.py")
