# blog

Fetch blog posts, extract plain text

## Usage

Edit `state.py` with seed URLs:

```python
posts = set()
indexes = set()
pending = ["https://example.com/post-1", "https://example.com/post-2"]
```

```shell
uv sync
uv run python fetch_feed.py
```

Content is saved to `content/*.txt`. State persists in `state.py` — restart resumes where it left off.
