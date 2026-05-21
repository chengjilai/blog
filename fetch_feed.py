import xml.etree.ElementTree
import urllib.request
import html2text
import readability
from lxml import html as lxml_html
from collections import deque
from urllib.parse import urljoin

NS = {"atom": "http://www.w3.org/2005/Atom"}
HEADERS = {"User-Agent": "Mozilla/5.0"}

h = html2text.HTML2Text()
h.ignore_links = True
h.ignore_images = True
h.body_width = 0

links = {
    entry.find("atom:link", namespaces=NS).attrib.get("href")
    for url in ["https://matklad.github.io/feed.xml", "https://www.scattered-thoughts.net/atom.xml"]
    for entry in xml.etree.ElementTree.parse(
        urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS))
    ).getroot().findall("atom:entry", NS)
}

MAX_FETCH = 20

seen = set()
queue = deque(sorted(links))

while queue and len(seen) < MAX_FETCH:
    link = queue.popleft()
    assert not link in seen
    seen.add(link)

    print(f"FETCH: {link}")

    try:
        html = urllib.request.urlopen(
            urllib.request.Request(link, headers=HEADERS)
        ).read().decode("utf-8")
        doc = readability.Document(html)
        content_html = doc.summary()
        plain = h.handle(content_html).strip()
        print(f"  plain text: {len(plain)} chars")

        for a in lxml_html.fromstring(content_html).findall(".//a"):
            href = a.attrib.get("href")
            if href and not href.startswith("#"):
                full = urljoin(link, href)
                if full not in seen:
                    links.add(full)
                    queue.append(full)
                    print(f"  NEW LINK: {full}")
    except Exception as e:
        print(f"  ERROR: {e}")
