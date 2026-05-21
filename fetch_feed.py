import xml.etree.ElementTree
import urllib.request
import html2text
import readability
from lxml import html as lxml_html
from collections import deque
from urllib.parse import urljoin

NS = {"atom": "http://www.w3.org/2005/Atom"}
HEADERS = {"User-Agent": "Mozilla/5.0"}
FEED_URLS = ["https://matklad.github.io/feed.xml",
             "https://www.scattered-thoughts.net/atom.xml"]

h = html2text.HTML2Text()
h.ignore_links = True
h.ignore_images = True
h.body_width = 0


def fetch(link):
    html = urllib.request.urlopen(
        urllib.request.Request(link, headers=HEADERS)
    ).read().decode("utf-8")
    content = readability.Document(html).summary()
    plain = h.handle(content).strip()
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

while queue and n < MAX_FETCH:
    link = queue.popleft()
    n += 1
    print(f"FETCH: {link}")
    try:
        plain, out_links = fetch(link)
        print(f"  plain text: {len(plain)} chars")
        for l in out_links:
            if l not in links:
                links.add(l)
                queue.append(l)
                print(f"  NEW: {l}")
    except Exception as e:
        print(f"  ERROR: {e}")
