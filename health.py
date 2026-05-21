import os
import sys
from state import posts

content_urls = set()
for fname in os.listdir("content"):
    if fname.endswith(".txt"):
        with open(f"content/{fname}") as f:
            content_urls.add(f.readline().strip())

if posts != content_urls:
    print(f"posts only: {posts - content_urls}")
    print(f"files only: {content_urls - posts}")
    sys.exit(1)
print("OK")
