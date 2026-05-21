import re
import lxml.html
from lxml.etree import tounicode, tostring
from lxml.html import document_fromstring, fragment_fromstring

REGEXES = {
    "unlikelyCandidatesRe": re.compile(
        r"combx|comment|community|disqus|extra|foot|header|menu|remark|rss|shoutbox|sidebar|sponsor|ad-break|agegate|pagination|pager|popup|tweet|twitter",
        re.I,
    ),
    "okMaybeItsACandidateRe": re.compile(r"and|article|body|column|main|shadow", re.I),
    "positiveRe": re.compile(
        r"article|body|content|entry|hentry|main|page|pagination|post|text|blog|story",
        re.I,
    ),
    "negativeRe": re.compile(
        r"combx|comment|com-|contact|foot|footer|footnote|masthead|media|meta|outbrain|promo|related|scroll|shoutbox|sidebar|sponsor|shopping|tags|tool|widget",
        re.I,
    ),
    "divToPElementsRe": re.compile(
        r"<(a|blockquote|dl|div|img|ol|p|pre|table|ul)", re.I
    ),
}

_attr_strip = re.compile(
    r"<([^>]+) (?:width|height|style|[-a-z]*color|background[-a-z]*|on\w*)"
    r'= *(?:[^ "\'<>]+|\'[^\']+\'|"[^"]+")([^>]*)>',
    re.I,
)

def clean(text):
    text = re.sub(r"\s{255,}", " " * 255, text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\t|[ \t]{2,}", " ", text)
    return text.strip()


def text_length(i):
    return len(clean(i.text_content() or ""))


utf8_parser = lxml.html.HTMLParser(encoding="utf-8")


class Document:
    def __init__(self, input, url=None):
        self.input = input
        self.html = None
        self.url = url

    def _html(self):
        if self.html is None:
            doc = lxml.html.document_fromstring(
                self.input.encode("utf-8", "replace"), parser=utf8_parser
            )
            if self.url:
                doc.make_links_absolute(self.url, resolve_base_href=True, handle_failures="discard")
            for tag in doc.findall(".//script") + doc.findall(".//style"):
                tag.drop_tree()
            self.html = doc
        return self.html

    def summary(self):
        self._html()
        self.remove_unlikely_candidates()
        self.transform_misused_divs_into_paragraphs()
        candidates = self.score_paragraphs()
        best = self.select_best_candidate(candidates)
        body = self.html.find("body")
        article = self.get_article(candidates, best) if best else (body if body is not None else self.html)  # type: ignore
        return self.sanitize(article, candidates)

    def get_article(self, candidates, best):
        threshold = max(10, best["content_score"] * 0.2)
        output = document_fromstring("<div/>")
        parent = best["elem"].getparent()
        for sibling in (parent.getchildren() if parent is not None else [best["elem"]]):
            if sibling is best["elem"]:
                output.getchildren()[0].getchildren()[0].append(sibling)
            elif sibling in candidates and candidates[sibling]["content_score"] >= threshold:
                output.getchildren()[0].getchildren()[0].append(sibling)
        return output

    def select_best_candidate(self, candidates):
        if not candidates:
            return None
        return max(candidates.values(), key=lambda x: x["content_score"])

    def get_link_density(self, elem):
        link_length = sum(text_length(i) for i in elem.findall(".//a"))
        return float(link_length) / max(text_length(elem), 1)

    def score_paragraphs(self):
        candidates = {}
        ordered = []
        for elem in self.tags(self.html, "p", "pre", "td"):
            parent = elem.getparent()
            if parent is None:
                continue
            grand = parent.getparent()
            inner = clean(elem.text_content() or "")
            if len(inner) < self.min_text_length:
                continue
            if parent not in candidates:
                candidates[parent] = self.score_node(parent)
                ordered.append(parent)
            if grand is not None and grand not in candidates:
                candidates[grand] = self.score_node(grand)
                ordered.append(grand)
            score = 1 + len(inner.split(",")) + min(len(inner) / 100, 3)
            candidates[parent]["content_score"] += score
            if grand is not None:
                candidates[grand]["content_score"] += score / 2.0
        for elem in ordered:
            candidates[elem]["content_score"] *= 1 - self.get_link_density(elem)
        return candidates

    def class_weight(self, e):
        weight = 0
        for feature in [e.get("class", None), e.get("id", None)]:
            if feature:
                if REGEXES["negativeRe"].search(feature):
                    weight -= 25
                if REGEXES["positiveRe"].search(feature):
                    weight += 25
        return weight

    def score_node(self, elem):
        content_score = self.class_weight(elem)
        name = elem.tag.lower()
        if name in ["div", "article"]:
            content_score += 5
        elif name in ["pre", "td", "blockquote"]:
            content_score += 3
        elif name in ["address", "ol", "ul", "dl", "dd", "dt", "li", "form", "aside"]:
            content_score -= 3
        elif name in ["h1", "h2", "h3", "h4", "h5", "h6", "th", "header", "footer", "nav"]:
            content_score -= 5
        return {"content_score": content_score, "elem": elem}

    def remove_unlikely_candidates(self):
        for elem in self.html.findall(".//*"):  # type: ignore
            s = "{} {}".format(elem.get("class", ""), elem.get("id", ""))
            if len(s) < 2:
                continue
            if (
                REGEXES["unlikelyCandidatesRe"].search(s)
                and not REGEXES["okMaybeItsACandidateRe"].search(s)
                and elem.tag not in ["html", "body"]
            ):
                elem.drop_tree()

    def transform_misused_divs_into_paragraphs(self):
        for elem in self.tags(self.html, "div"):
            children_html = b"".join(
                tostring(c, encoding="utf-8") if hasattr(c, 'tag') else b""
                for c in elem
            )
            if not REGEXES["divToPElementsRe"].search(str(children_html)):
                elem.tag = "p"
        for elem in self.tags(self.html, "div"):
            if elem.text and elem.text.strip():
                p = fragment_fromstring("<p/>")
                p.text = elem.text
                elem.text = None
                elem.insert(0, p)
            for pos, child in reversed(list(enumerate(elem))):
                if child.tail and child.tail.strip():
                    p = fragment_fromstring("<p/>")
                    p.text = child.tail
                    child.tail = None
                    elem.insert(pos + 1, p)
                if child.tag == "br":
                    child.drop_tree()

    def tags(self, node, *tag_names):
        for tag_name in tag_names:
            yield from node.findall(".//%s" % tag_name)

    def sanitize(self, node, candidates):
        for header in self.tags(node, "h1", "h2", "h3", "h4", "h5", "h6"):
            if self.class_weight(header) < 0 or self.get_link_density(header) > 0.33:
                header.drop_tree()
        for el in self.tags(node, "table", "ul", "div", "aside", "header", "footer", "section"):
            weight = self.class_weight(el)
            score = candidates[el]["content_score"] if el in candidates else 0
            if weight + score < 0 or not text_length(el) or self.get_link_density(el) > 0.5:
                el.drop_tree()
        self.html = node
        html = tounicode(self.html, method="html")
        while _attr_strip.search(html):
            html = _attr_strip.sub(r"<\1\2>", html)
        return html

    min_text_length = 25
