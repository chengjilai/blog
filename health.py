import os
import re
from state import posts

content_urls = set()
for fname in os.listdir("content"):
    if fname.endswith(".txt"):
        with open(f"content/{fname}") as f:
            url = f.readline().strip()
            content_urls.add(url)

orphan_files = content_urls - posts
orphan_posts = posts - content_urls

if not orphan_files and not orphan_posts:
    print("OK")
else:
    for u in orphan_files:
        print(f"orphan file: {u}")
    for u in orphan_posts:
        print(f"missing file: {u}")
