import os
import sys
from state import posts

content_urls = set()
for fname in os.listdir("content"):
    if fname.endswith(".txt"):
        with open(f"content/{fname}") as f:
            content_urls.add(f.readline().strip())

extra = content_urls - posts
if extra:
    print(f"orphan files: {extra}")
    sys.exit(1)
print("OK")
