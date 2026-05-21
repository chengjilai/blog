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
    "videoRe": re.compile(r"https?:\/\/(www\.)?(youtube|vimeo)\.com", re.I),
}

bad_attrs = ["width", "height", "style", "[-a-z]*color", "background[-a-z]*", "on*"]
single_quoted = "'[^']+'"
double_quoted = '"[^"]+"'
non_space = "[^ \"'>]+"
htmlstrip = re.compile(
    "<([^>]+) (?:{}) *= *(?:{}|{}|{})([^>]*)>".format(
        "|".join(bad_attrs), non_space, single_quoted, double_quoted
    ),
    re.I,
)


def clean(text):
    text = re.sub(r"\s{255,}", " " * 255, text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\t|[ \t]{2,}", " ", text)
    return text.strip()


def text_length(i):
    return len(clean(i.text_content() or ""))


def clean_attributes(html):
    while htmlstrip.search(html):
        html = htmlstrip.sub(r"<\1\2>", html)
    return html


def build_doc(page):
    if isinstance(page, str):
        return lxml.html.document_fromstring(page.encode("utf-8", "replace"), parser=utf8_parser), None
    return lxml.html.document_fromstring(page, parser=utf8_parser), None


utf8_parser = lxml.html.HTMLParser(encoding="utf-8")


class Document:
    def __init__(self, input, url=None):
        self.input = input
        self.html = None
        self.url = url

    def _html(self, force=False):
        if force or self.html is None:
            self.html = self._parse(self.input)
        return self.html

    def _parse(self, input):
        doc, _ = build_doc(input)
        if self.url:
            doc.make_links_absolute(self.url, resolve_base_href=True, handle_failures="discard")
        for tag in doc.findall(".//script") + doc.findall(".//style"):
            tag.drop_tree()
        return doc

    def summary(self):
        ruthless = True
        while True:
            self._html(True)
            for i in self.tags(self.html, "body"):
                i.set("id", "readabilityBody")
            if ruthless:
                self.remove_unlikely_candidates()
            self.transform_misused_divs_into_paragraphs()
            candidates = self.score_paragraphs()
            best = self.select_best_candidate(candidates)
            if best:
                article = self.get_article(candidates, best)
            else:
                if ruthless:
                    ruthless = False
                    continue
                else:
                    article = self.html.find("body") or self.html
            cleaned = self.sanitize(article, candidates)
            if ruthless and len(cleaned or "") < self.retry_length:
                ruthless = False
                continue
            return cleaned

    def get_article(self, candidates, best):
        sibling_score_threshold = max(10, best["content_score"] * 0.2)
        output = document_fromstring("<div/>")
        best_elem = best["elem"]
        parent = best_elem.getparent()
        siblings = parent.getchildren() if parent is not None else [best_elem]
        for sibling in siblings:
            append = sibling is best_elem
            if sibling in candidates and candidates[sibling]["content_score"] >= sibling_score_threshold:
                append = True
            if sibling.tag == "p":
                link_density = self.get_link_density(sibling)
                node_length = len(sibling.text or "")
                if node_length > 80 and link_density < 0.25:
                    append = True
                elif node_length <= 80 and link_density == 0 and re.search(r"\.( |$)", sibling.text or ""):
                    append = True
            if append:
                output.getchildren()[0].getchildren()[0].append(sibling)
        return output

    def select_best_candidate(self, candidates):
        if not candidates:
            return None
        sorted_candidates = sorted(candidates.values(), key=lambda x: x["content_score"], reverse=True)
        return sorted_candidates[0]

    def get_link_density(self, elem):
        link_length = sum(text_length(i) for i in elem.findall(".//a"))
        total_length = text_length(elem)
        return float(link_length) / max(total_length, 1)

    def score_paragraphs(self):
        candidates = {}
        ordered = []
        for elem in self.tags(self._html(), "p", "pre", "td"):
            parent_node = elem.getparent()
            if parent_node is None:
                continue
            grand_parent_node = parent_node.getparent()
            inner_text = clean(elem.text_content() or "")
            inner_text_len = len(inner_text)
            if inner_text_len < self.min_text_length:
                continue
            if parent_node not in candidates:
                candidates[parent_node] = self.score_node(parent_node)
                ordered.append(parent_node)
            if grand_parent_node is not None and grand_parent_node not in candidates:
                candidates[grand_parent_node] = self.score_node(grand_parent_node)
                ordered.append(grand_parent_node)
            content_score = 1
            content_score += len(inner_text.split(","))
            content_score += min((inner_text_len / 100), 3)
            candidates[parent_node]["content_score"] += content_score
            if grand_parent_node is not None:
                candidates[grand_parent_node]["content_score"] += content_score / 2.0
        for elem in ordered:
            ld = self.get_link_density(elem)
            candidates[elem]["content_score"] *= 1 - ld
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
        for elem in self.html.findall(".//*"):
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

    def reverse_tags(self, node, *tag_names):
        for tag_name in tag_names:
            yield from reversed(node.findall(".//%s" % tag_name))

    def sanitize(self, node, candidates):
        for header in self.tags(node, "h1", "h2", "h3", "h4", "h5", "h6"):
            if self.class_weight(header) < 0 or self.get_link_density(header) > 0.33:
                header.drop_tree()
        for elem in self.tags(node, "form", "textarea"):
            elem.drop_tree()
        for elem in self.tags(node, "iframe"):
            if "src" in elem.attrib and REGEXES["videoRe"].search(elem.attrib["src"]):
                elem.text = "VIDEO"
            else:
                elem.drop_tree()
        allowed = {}
        for el in self.reverse_tags(node, "table", "ul", "div", "aside", "header", "footer", "section"):
            if el in allowed:
                continue
            weight = self.class_weight(el)
            content_score = candidates[el]["content_score"] if el in candidates else 0
            tag = el.tag
            if weight + content_score < 0:
                el.drop_tree()
            elif el.text_content().count(",") < 10:
                counts = {kind: len(el.findall(".//%s" % kind)) for kind in ["p", "img", "li", "a", "embed", "input"]}
                counts["li"] -= 100
                counts["input"] -= len(el.findall('.//input[@type="hidden"]'))
                content_length = text_length(el)
                link_density = self.get_link_density(el)
                parent_node = el.getparent()
                if parent_node is not None:
                    if parent_node in candidates:
                        content_score = candidates[parent_node]["content_score"]
                    else:
                        content_score = 0
                to_remove = False
                if counts["p"] and counts["img"] > 1 + counts["p"] * 1.3:
                    to_remove = True
                elif counts["li"] > counts["p"] and tag not in ("ol", "ul"):
                    to_remove = True
                elif counts["input"] > (counts["p"] / 3):
                    to_remove = True
                elif content_length < self.min_text_length and counts["img"] == 0:
                    to_remove = True
                elif content_length < self.min_text_length and counts["img"] > 2:
                    to_remove = True
                elif weight < 25 and link_density > 0.2:
                    to_remove = True
                elif weight >= 25 and link_density > 0.5:
                    to_remove = True
                elif (counts["embed"] == 1 and content_length < 75) or counts["embed"] > 1:
                    to_remove = True
                elif not content_length:
                    to_remove = True
                if to_remove:
                    i, j = 0, 0
                    siblings = []
                    for sib in el.itersiblings():
                        sib_content_length = text_length(sib)
                        if sib_content_length:
                            i += 1
                            siblings.append(sib_content_length)
                            if i == 1:
                                break
                    for sib in el.itersiblings(preceding=True):
                        sib_content_length = text_length(sib)
                        if sib_content_length:
                            j += 1
                            siblings.append(sib_content_length)
                            if j == 1:
                                break
                    if siblings and sum(siblings) > 1000:
                        to_remove = False
                        for desnode in self.tags(el, "table", "ul", "div", "section"):
                            allowed[desnode] = True
                if to_remove:
                    el.drop_tree()
        self.html = node
        return clean_attributes(tounicode(self.html, method="html"))

    min_text_length = 25
    retry_length = 250
