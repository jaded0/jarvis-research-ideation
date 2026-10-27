"""Check source references and literal excerpts without browser/parser dependencies."""

import ast
from html import unescape
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DiagramParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs = []
        self.snippets = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-ref" in attrs:
            self.refs.append(attrs["data-ref"])
        if "data-snippet-for" in attrs:
            assert tag == "pre", "Excerpts must be preformatted"
            assert self.current is None, "Nested excerpts"
            self.current = (attrs["data-snippet-for"], [])

    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == "pre" and self.current is not None:
            ref, chunks = self.current
            self.snippets.append((ref, "".join(chunks)))
            self.current = None


def defined_names(tree, prefix=""):
    """Include nested functions (build_parser.sub) and assigned constants."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = prefix + node.name
            names.add(name)
            names.update(defined_names(node, name + "."))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(prefix + target.id)
    return names


def normalize(text):
    return " ".join(unescape(text).split())


def test_diagram_source_references_and_snippets():
    parser = DiagramParser()
    parser.feed((ROOT / "docs/how-it-works.html").read_text())
    parser.close()
    assert parser.current is None
    assert parser.refs, "The diagram must link to source"
    assert parser.snippets, "The diagram must include source excerpts"
    sources = {}
    for ref in set(parser.refs) | {r for r, _ in parser.snippets}:
        path, name = ref.split(":", 1)
        assert path.startswith("src/jarvis/") and path.endswith(".py"), ref
        file = (ROOT / path).resolve()
        assert file.is_relative_to(ROOT / "src/jarvis"), ref
        assert file.is_file(), ref
        source = file.read_text()
        assert name in defined_names(ast.parse(source)), ref
        sources[ref] = source
    for ref, snippet in parser.snippets:
        assert ref in parser.refs, f"Excerpt without a source link: {ref}"
        assert snippet.strip(), ref
        assert 3 <= len(snippet.strip("\n").splitlines()) <= 10, ref
        assert normalize(snippet) in normalize(sources[ref]), f"Drifted excerpt: {ref}"
