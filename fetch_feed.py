import re
import xml.etree.ElementTree
import urllib.request
from html.parser import HTMLParser
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from lxml import html as lxml_html
from urllib.parse import urljoin

from vendor.readability import Document

NS = {"atom": "http://www.w3.org/2005/Atom"}
HEADERS = {"User-Agent": "Mozilla/5.0"}
FEED_URLS = ["https://matklad.github.io/feed.xml",
             "https://www.scattered-thoughts.net/atom.xml"]


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip = 0

    def handle_starttag(self, tag, _):
        if tag in ("script", "style", "head", "title", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title", "noscript"):
            self._skip -= 1
        elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                     "li", "blockquote", "pre", "hr", "tr", "br", "ul", "ol"):
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


def html_to_text(html):
    s = _Stripper()
    s.feed(html)
    return s.get_text()


def fetch(link):
    html = urllib.request.urlopen(
        urllib.request.Request(link, headers=HEADERS)
    ).read().decode("utf-8")
    content = Document(html, url=link).summary()
    plain = html_to_text(content)
    anchors = lxml_html.fromstring(content).findall(".//a")
    out_links = [urljoin(link, a.attrib["href"])
                 for a in anchors
                 if a.attrib.get("href") and not a.attrib["href"].startswith("#")]
    return plain, out_links


links = {
    entry.find("atom:link", namespaces=NS).attrib.get("href")
    for url in FEED_URLS
    for entry in xml.etree.ElementTree.parse(
        urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS))
    ).getroot().findall("atom:entry", NS)
}

queue = deque(links)
MAX_FETCH = 20
n = 0

with ThreadPoolExecutor(max_workers=8) as pool:
    while queue and n < MAX_FETCH:
        batch_size = min(len(queue), 8)
        batch = [queue.popleft() for _ in range(batch_size)]
        futures = {pool.submit(fetch, l): l for l in batch}
        for f in as_completed(futures):
            link = futures[f]
            n += 1
            try:
                plain, out_links = f.result()
                print(f"FETCH: {link}  ({len(plain)} chars)")
                for l in out_links:
                    if l not in links:
                        links.add(l)
                        queue.append(l)
                        print(f"  NEW: {l}")
            except Exception as e:
                print(f"FETCH: {link}  ERROR: {e}")
