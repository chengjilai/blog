import os
import xml.etree.ElementTree
import urllib.request

NS = {"atom": "http://www.w3.org/2005/Atom"}
HEADERS = {"User-Agent": "Mozilla/5.0"}
FEED_URLS = ["https://matklad.github.io/feed.xml",
             "https://www.scattered-thoughts.net/atom.xml"]

seed = []
for url in FEED_URLS:
    root = xml.etree.ElementTree.parse(
        urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS))
    ).getroot()
    for entry in root.findall("atom:entry", NS):
        seed.append(entry.find("atom:link", namespaces=NS).attrib.get("href"))

os.makedirs("content", exist_ok=True)

with open("state.py.tmp", "w") as f:
    f.write("posts = set()\n")
    f.write("indexes = set()\n")
    f.write(f"pending = {repr(seed)}\n")
os.replace("state.py.tmp", "state.py")

print(f"Seeded {len(seed)} URLs")
