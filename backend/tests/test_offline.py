"""
Offline tests - no network, no Node.js, no API keys.   Run from backend/:

    python -m unittest discover -s tests -v

They run the real MCP manager, tool wrappers, academic server logic and citation checker
against simulated servers / mocked HTTP responses. (Live checks: python check_tools.py)
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import fake_mcp  # noqa: E402

fake_mcp.install()

TAVILY_TEXT = """Detailed Results:

Title: Adaptive learning in schools
URL: https://example.org/adaptive
Content: Adaptive platforms adjust difficulty to each pupil. 42% of schools use them.

Title: AI tutors review
URL: https://example.org/tutors
Content: Tutors give instant feedback.
"""
STATIC_PAGE = "Full article text about adaptive learning. " * 20


def _handlers():
    fs: dict[str, str] = {}

    def tavily_search(a):
        if "quota" in a["query"]:
            raise fake_mcp.ToolErr("Usage limit exceeded (432)")
        return TAVILY_TEXT

    def fetch(a):
        url = a["url"]
        if "down.example" in url:
            raise fake_mcp.ToolErr("Failed to fetch robots.txt")
        if "js.example" in url:
            return f"Contents of {url}:\nPlease enable JavaScript to continue."
        return f"Contents of {url}:\n{STATIC_PAGE}"

    def read(a):
        if a["path"] in fs:
            return fs[a["path"]]
        raise fake_mcp.ToolErr("ENOENT: no such file")

    def write(a):
        fs[a["path"]] = a["content"]
        return "Successfully wrote"

    rendered = "Rendered by browser. " * 30

    def navigate(a):
        if "down.example" in a["url"]:
            raise fake_mcp.ToolErr("net::ERR_CONNECTION_REFUSED")   # site really is unreachable
        return "navigated"

    return {
        "tavily": {"tavily-search": tavily_search, "tavily-extract": lambda a: "x"},
        "fetch": {"fetch": fetch},
        "filesystem": {"read_text_file": read, "write_file": write,
                       "create_directory": lambda a: "ok", "list_directory": lambda a: ""},
        "academic": {"search_papers": lambda a: {"papers": [
            {"title": "Deep learning for education", "url": "https://doi.org/10.1/x", "doi": "10.1/x",
             "abstract": "A long enough abstract about deep learning in classrooms " * 3,
             "authors": ["Ada Lovelace"], "published": "2021-01-01", "venue": "J. Edu", "source": "openalex"},
            {"title": "Title only paper", "url": "https://doi.org/10.1/y", "doi": "10.1/y",
             "abstract": "", "authors": [], "published": "", "venue": "", "source": "crossref"}],
            "errors": {"semantic_scholar": "HTTP 429"}}},
        "playwright": {"browser_navigate": navigate,
                       "browser_evaluate": lambda a: f"### Result\n{json.dumps(rendered)}\n### Ran Playwright code\n..."},
    }, fs


class MCPLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.env = mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test", "RESEARCH_DIR": cls.tmp,
                                               "ENABLE_PLAYWRIGHT_MCP": "true"})
        cls.env.start()
        cls.spec = mock.patch("importlib.util.find_spec", lambda name, *a: object()
                              if name == "mcp_server_fetch" else importlib.util.find_spec.__wrapped__(name)
                              if hasattr(importlib.util.find_spec, "__wrapped__") else None)
        handlers, cls.fs = _handlers()
        fake_mcp.HANDLERS.update(handlers)
        from tools import mcp_client
        cls.mgr = mcp_client.mcp_manager
        with mock.patch("importlib.util.find_spec", return_value=object()), \
                mock.patch("shutil.which", return_value="npx"):
            cls.mgr.start()
        for name in ("tavily", "fetch", "filesystem", "academic", "playwright"):
            cls.mgr.is_ready(name)

    @classmethod
    def tearDownClass(cls):
        cls.mgr.stop()
        cls.env.stop()

    def setUp(self):
        fake_mcp.CALLS.clear()

    def calls(self, server):
        return [c for c in fake_mcp.CALLS if c[0] == server]

    # ---- manager
    def test_all_five_servers_connect(self):
        status = self.mgr.status()
        for name in ("tavily", "fetch", "filesystem", "academic", "playwright"):
            self.assertEqual(status[name]["state"], "ready", status[name])

    def test_filesystem_server_gets_only_the_research_folder(self):
        cfg = [c for c in self.mgr.build_configs() if c.name == "filesystem"] or None
        with mock.patch("shutil.which", return_value="npx"):
            cfg = [c for c in self.mgr.build_configs() if c.name == "filesystem"][0]
        self.assertEqual(cfg.args[-1], str(Path(self.tmp).resolve()))
        self.assertEqual(len([a for a in cfg.args if not a.startswith("-")]), 2)  # package + ONE dir

    def test_unknown_tool_and_timeout_handling(self):
        from tools.mcp_client import MCPUnavailable
        with self.assertRaises(MCPUnavailable):
            self.mgr.call("fetch", ["does_not_exist"], {})
        with self.assertRaises(MCPUnavailable):
            self.mgr.call("nonexistent_server", ["x"], {})

    def test_failed_server_is_reported_not_raised(self):
        from tools.mcp_client import MCPManager
        fake_mcp.FAIL_START.add("fetch")
        try:
            m = MCPManager()
            with mock.patch("importlib.util.find_spec", return_value=object()), \
                    mock.patch("shutil.which", return_value="npx"):
                m.start()
            self.assertFalse(m.is_ready("fetch"))
            self.assertEqual(m.status()["fetch"]["state"], "failed")
            self.assertTrue(m.is_ready("academic"))
            m.stop()
        finally:
            fake_mcp.FAIL_START.discard("fetch")

    # ---- Tavily MCP + DuckDuckGo fallback
    def test_tavily_parse_and_cache(self):
        from tools import web_search
        web_search._cache = web_search.TTLCache()
        results = web_search.search_web("adaptive learning")
        self.assertEqual([r["url"] for r in results], ["https://example.org/adaptive", "https://example.org/tutors"])
        self.assertIn("42%", results[0]["content"])
        web_search.search_web("Adaptive   Learning")          # same query, different spacing
        self.assertEqual(len(self.calls("tavily")), 1, "duplicate search must be served from cache")

    def test_quota_exhaustion_falls_back_to_duckduckgo(self):
        from tools import web_search
        web_search._cache = web_search.TTLCache()
        web_search._tavily.update(blocked_until=0.0, disabled=False)
        ddg = [{"title": "DDG", "url": "https://ddg.example/1", "content": "c", "source_type": "web", "published": ""}]
        with mock.patch.object(web_search, "_search_duckduckgo", return_value=ddg) as m:
            first = web_search.search_web("quota test")
            second = web_search.search_web("another query")  # Tavily is now paused -> no more MCP calls
        self.assertEqual(first[0]["url"], "https://ddg.example/1")
        self.assertEqual(second[0]["url"], "https://ddg.example/1")
        self.assertEqual(len(self.calls("tavily")), 1)
        self.assertEqual(m.call_count, 2)
        web_search._tavily.update(blocked_until=0.0, disabled=False)

    # ---- Fetch MCP + Playwright MCP + Filesystem cache
    def test_fetch_then_cache_hit_without_refetching(self):
        from tools import page_fetch
        page_fetch._memory = page_fetch.TTLCache()
        page = page_fetch.fetch_page("https://static.example/a")
        self.assertEqual(page["method"], "fetch")
        self.assertFalse(page["text"].startswith("Contents of"))
        self.assertEqual(len(self.calls("fetch")), 1)
        self.assertEqual(len(self.calls("filesystem")), 2)     # 1 cache miss read + 1 write
        page_fetch._memory = page_fetch.TTLCache()             # simulate a NEW run: only the file cache remains
        again = page_fetch.fetch_page("https://static.example/a")
        self.assertEqual(again["text"], page["text"])
        self.assertEqual(len(self.calls("fetch")), 1, "second run must reuse research/documents/")

    def test_js_page_falls_back_to_playwright(self):
        from tools import page_fetch
        page_fetch._memory = page_fetch.TTLCache()
        page = page_fetch.fetch_page("https://js.example/app")
        self.assertEqual(page["method"], "playwright")
        self.assertIn("Rendered by browser", page["text"])
        self.assertEqual([c[1] for c in self.calls("playwright")], ["browser_navigate", "browser_evaluate"])

    def test_fetch_failure_is_rescued_by_playwright(self):
        from tools import page_fetch
        page_fetch._memory = page_fetch.TTLCache()
        with mock.patch.object(page_fetch, "_fetch_with_fetch_mcp", return_value=None):
            page = page_fetch.fetch_page("https://blocked-for-fetch.example/p")
        self.assertEqual(page["method"], "playwright")

    def test_failed_page_is_not_retried(self):
        from tools import page_fetch
        page_fetch._memory = page_fetch.TTLCache()
        self.assertIsNone(page_fetch.fetch_page("https://down.example/x"))
        n = len(self.calls("fetch"))
        self.assertIsNone(page_fetch.fetch_page("https://down.example/x"))
        self.assertEqual(len(self.calls("fetch")), n)

    # ---- Academic MCP client wrapper
    def test_academic_wrapper_keeps_metadata_and_skips_abstractless_papers(self):
        from tools import academic_search
        academic_search._cache = academic_search.TTLCache()
        res = academic_search.search_papers("deep learning education")
        self.assertEqual(len(res), 1)
        r = res[0]
        self.assertEqual((r["doi"], r["authors"], r["published"], r["source_type"]),
                         ("10.1/x", ["Ada Lovelace"], "2021-01-01", "academic"))

    # ---- Filesystem MCP: report saving
    def test_report_saved_inside_research_folder_only(self):
        from tools import file_store
        report = {"title": "T", "introduction": "i", "research_questions": ["q"], "key_findings": ["k [1]."],
                  "references": [{"title": "Ref", "url": "https://x", "doi": "10.1/x", "authors": ["A"],
                                  "published": "2021", "n": 1}], "visuals": [], "meta": {}}
        folder = file_store.save_report(7, "My Topic!", report)
        self.assertTrue(folder.startswith(str(Path(self.tmp).resolve())))
        written = [p for p in self.fs if p.startswith(folder)]
        self.assertEqual(sorted(Path(p).name for p in written), ["references.json", "report.json", "report.md"])
        self.assertIn("DOI: 10.1/x", self.fs[f"{folder}/report.md"])


class AcademicServerTests(unittest.TestCase):
    ARXIV = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry><id>http://arxiv.org/abs/2101.00001v1</id><published>2021-01-01T00:00:00Z</published>
      <title>Deep  Learning
        for Education</title><summary>Arxiv abstract text.</summary>
      <author><name>Ada Lovelace</name></author><author><name>Alan Turing</name></author>
      <arxiv:doi>10.1000/XYZ123</arxiv:doi></entry>
      <entry><id>http://arxiv.org/abs/2202.00002v1</id><published>2022-02-02T00:00:00Z</published>
      <title>Only on arXiv</title><summary>Unique abstract.</summary><author><name>Grace Hopper</name></author></entry></feed>"""
    OPENALEX = {"results": [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1000/xyz123",
                             "display_name": "Deep learning for education", "publication_date": "2021-01-01",
                             "authorships": [{"author": {"display_name": "Ada Lovelace"}},
                                             {"author": {"display_name": "Alan Turing"}},
                                             {"author": {"display_name": "Katherine Johnson"}}],
                             "primary_location": {"landing_page_url": "https://journal.example/1",
                                                  "source": {"display_name": "Journal of X"}},
                             "abstract_inverted_index": {"Deep": [0], "learning": [1], "helps": [2], "pupils.": [3]},
                             "cited_by_count": 10}]}
    CROSSREF = {"message": {"items": [{"DOI": "10.1000/xyz123", "title": ["Deep learning for education"],
                                       "author": [{"given": "Ada", "family": "Lovelace"}],
                                       "issued": {"date-parts": [[2021, 1]]}, "container-title": ["Journal of X"],
                                       "URL": "http://dx.doi.org/10.1000/xyz123",
                                       "abstract": "<jats:p>Crossref abstract.</jats:p>",
                                       "is-referenced-by-count": 10}]}}

    class Resp:
        def __init__(self, status=200, body=None, content=b""):
            self.status_code, self._body, self.content, self.headers = status, body, content, {}

        def json(self):
            return self._body

        def raise_for_status(self):
            if self.status_code >= 400:
                import requests
                raise requests.HTTPError(str(self.status_code))

    def setUp(self):
        import mcp_servers.academic_server as srv
        self.srv = srv
        for limiter in srv.LIMITS.values():
            limiter.interval = 0
        self.calls = []

        def fake_get(url, params=None, timeout=None, headers=None):
            self.calls.append(url)
            if "arxiv" in url:
                return self.Resp(content=self.ARXIV.encode())
            if "openalex" in url:
                return self.Resp(body=self.OPENALEX)
            if "crossref" in url and "/works/" in url:
                return self.Resp(body={"message": self.CROSSREF["message"]["items"][0]})
            if "crossref" in url:
                return self.Resp(body=self.CROSSREF)
            return self.Resp(status=429)  # Semantic Scholar rate-limited

        patches = [mock.patch("requests.get", fake_get), mock.patch("time.sleep")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_merge_dedupes_by_doi_and_keeps_metadata(self):
        out = self.srv.search_papers("deep learning education", max_results=5)
        titles = [p["title"] for p in out["papers"]]
        self.assertEqual(sorted(titles), ["Deep learning for education", "Only on arXiv"])
        paper = [p for p in out["papers"] if p["doi"] == "10.1000/xyz123"][0]
        self.assertEqual(len(paper["authors"]), 3)                      # longest author list kept
        self.assertEqual(paper["abstract"], "Deep learning helps pupils.")  # rebuilt from OpenAlex index
        self.assertEqual((paper["published"], paper["venue"]), ("2021-01-01", "Journal of X"))
        self.assertEqual(sorted(paper["found_in"]), ["arxiv", "crossref", "openalex"])

    def test_one_failing_api_does_not_break_the_others(self):
        out = self.srv.search_papers("deep learning education")
        self.assertIn("semantic_scholar", out["errors"])
        self.assertEqual(len(out["papers"]), 2)
        self.assertEqual(sum("semanticscholar" in c for c in self.calls), self.srv.MAX_RETRIES)  # retried, then gave up

    def test_crossref_date_and_doi_lookup(self):
        out = self.srv.get_paper_by_doi("https://doi.org/10.1000/xyz123")
        self.assertEqual(out["paper"]["published"], "2021-01")
        self.assertEqual(out["paper"]["abstract"], "Crossref abstract.")


class CitationTests(unittest.TestCase):
    def setUp(self):
        from agent.citations import apply_citations
        self.apply = apply_citations
        self.facts = [(1, "Adaptive platforms adjust difficulty to each pupil. 42% of schools use them."),
                      (2, "Tutors give instant feedback to students.")]
        self.refs = {1: {"title": "Adaptive learning", "url": "https://a", "published": "2021"},
                     2: {"title": "AI tutors", "url": "https://b", "published": ""},
                     3: {"title": "Never shown", "url": "https://c", "published": ""}}

    def report(self, **kw):
        base = dict(title="T", executive_summary="", introduction="Intro text.", research_questions=[],
                    key_findings=[], detailed_analysis="", advantages=[], challenges=[], conclusion="")
        base.update(kw)
        return base

    def test_uncited_invented_number_and_fake_source_statements_are_removed(self):
        rep = self.report(detailed_analysis=(
            "Adaptive platforms adjust difficulty [1]. "          # ok
            "Sales grew by 87% last year [1]. "                  # number not in the source -> dropped
            "Teachers love it. "                                 # no citation -> dropped
            "Tutors give instant feedback [2][9]."))             # [9] does not exist -> stripped, kept via [2]
        out = self.apply(rep, self.facts, self.refs)
        text = out["detailed_analysis"]
        self.assertIn("Adaptive platforms adjust difficulty [1].", text)
        self.assertIn("Tutors give instant feedback [2].", text)
        self.assertNotIn("87", text)
        self.assertNotIn("Teachers love it", text)
        self.assertNotIn("9", text.replace("[1]", "").replace("[2]", ""))
        self.assertEqual(out["citation_stats"], {"statements_cited": 2, "statements_removed": 2})

    def test_numbers_present_in_source_are_accepted(self):
        out = self.apply(self.report(key_findings=["42% of schools use adaptive platforms [1]."]), self.facts, self.refs)
        self.assertEqual(out["key_findings"], ["42% of schools use adaptive platforms [1]."])

    def test_markers_after_full_stop_are_understood(self):
        out = self.apply(self.report(conclusion="Tutors give instant feedback. [2]"), self.facts, self.refs)
        self.assertEqual(out["conclusion"], "Tutors give instant feedback [2].")

    def test_references_renumbered_and_only_cited_sources_listed(self):
        rep = self.report(key_findings=["Tutors give feedback [2].", "Platforms adjust difficulty [1]."])
        out = self.apply(rep, self.facts, self.refs)
        self.assertEqual(out["key_findings"], ["Tutors give feedback [1].", "Platforms adjust difficulty [2]."])
        self.assertEqual([(r["n"], r["title"]) for r in out["references"]], [(1, "AI tutors"), (2, "Adaptive learning")])

    def test_fallback_findings_come_straight_from_facts(self):
        out = self.apply(self.report(key_findings=["Totally uncited claim."]), self.facts, self.refs)
        self.assertTrue(out["key_findings"] and all("[" in k for k in out["key_findings"]))
        self.assertEqual(len(out["references"]), 2)

    def test_abbreviations_do_not_split_sentences(self):
        out = self.apply(self.report(conclusion="Tools e.g. tutors help students [2]."), self.facts, self.refs)
        self.assertEqual(out["conclusion"], "Tools e.g. tutors help students [2].")


if __name__ == "__main__":
    unittest.main()
