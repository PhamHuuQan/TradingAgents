from __future__ import annotations

import ast
import json
import re
import time
import unittest
from pathlib import Path

NOTEBOOK = (
    Path(__file__).resolve().parents[1]
    / "notebooks"
    / "TradingAgents_FPT_Fresh_Run_And_Report.ipynb"
)


class RunnableStub:
    def __init__(self, *args, **kwargs):
        pass


def load_fallback_symbols():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cell_source = "".join(notebook["cells"][4]["source"])
    tree = ast.parse(cell_source)

    wanted = {
        "is_transient_gemini_error",
        "_gemini_status",
        "GeminiFallbackRunnable",
    }
    selected = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted
    ]
    assert {node.name for node in selected} == wanted
    namespace = {"Runnable": RunnableStub, "time": time, "re": re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(NOTEBOOK), "exec"), namespace)
    return namespace["GeminiFallbackRunnable"]


class FakeModel:
    def __init__(self, name, failures=()):
        self.name = name
        self.failures = list(failures)
        self.calls = 0

    def invoke(self, value, config=None, **kwargs):
        self.calls += 1
        if self.failures:
            raise RuntimeError(self.failures.pop(0))
        return f"OK:{self.name}"

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        return self


class FreshNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        cls.source = ["".join(c.get("source", [])) for c in cls.nb["cells"]]
        cls.Fallback = load_fallback_symbols()

    def test_notebook_json_and_every_code_cell_compile(self):
        self.assertEqual(self.nb["nbformat"], 4)
        for index, cell in enumerate(self.nb["cells"]):
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), f"cell-{index}", "exec")

    def test_graph_keeps_all_default_analysts_and_vietnam_sources(self):
        run_cell = self.source[5]
        self.assertIn('ANALYSTS = ["market", "social", "news", "fundamentals"]', run_cell)
        self.assertIn('config["data_vendors"]["core_stock_apis"] = "ssi"', run_cell)
        self.assertIn('config["data_vendors"]["technical_indicators"] = "ssi"', run_cell)
        self.assertIn('config["data_vendors"]["fundamental_data"] = "vnstock"', run_cell)
        self.assertIn("TradingAgentsGraph(selected_analysts=ANALYSTS", run_cell)

    def test_model_candidates_start_with_flash_lite_fallbacks(self):
        run_cell = self.source[5]
        self.assertLess(run_cell.index('"gemini-3.1-flash-lite"'), run_cell.index('"gemini-3.5-flash-lite"'))
        self.assertIn('"gemini-3.6-flash"', run_cell)
        self.assertIn('"gemini-3.8-flash"', run_cell)

    def test_offline_self_test_has_no_api_credentials_or_network_calls(self):
        offline_cell = self.source[4]
        self.assertIn("OFFLINE SELF-TEST PASSED: 4/4 cases", offline_cell)
        self.assertNotIn("GOOGLE_API_KEY", offline_cell)
        self.assertNotIn("ChatGoogleGenerativeAI", offline_cell)
        self.assertNotIn("requests.", offline_cell)

    def test_runtime_503_switches_once_and_keeps_using_fallback(self):
        state = {"active_index": 0}
        primary = FakeModel("primary", ["503 UNAVAILABLE"])
        backup = FakeModel("backup")
        chain = self.Fallback([primary, backup], ["primary", "backup"], state)

        result = chain.bind_tools([]).invoke("test")
        self.assertEqual(result, "OK:backup")
        self.assertEqual(state["active_index"], 1)
        self.assertEqual(primary.calls, 1)
        self.assertEqual(backup.calls, 1)

        # A later wrapper (such as the deep-thinking tier) shares the same circuit state.
        second_primary = FakeModel("primary-again")
        second_backup = FakeModel("backup-again")
        second_chain = self.Fallback([second_primary, second_backup], ["primary", "backup"], state)
        self.assertEqual(second_chain.invoke("test"), "OK:backup-again")
        self.assertEqual(second_primary.calls, 0)
        self.assertEqual(second_backup.calls, 1)

    def test_structured_output_path_can_fallback_too(self):
        state = {"active_index": 0}
        chain = self.Fallback(
            [
                FakeModel("first-structured", ["503 UNAVAILABLE"]),
                FakeModel("second-structured"),
            ],
            ["first-structured", "second-structured"],
            state,
        )
        result = chain.with_structured_output(dict).invoke("test")
        self.assertEqual(result, "OK:second-structured")
        self.assertEqual(state["active_index"], 1)

    def test_non_transient_400_does_not_switch_models(self):
        state = {"active_index": 0}
        primary = FakeModel("primary", ["400 INVALID_ARGUMENT"])
        backup = FakeModel("backup")
        chain = self.Fallback([primary, backup], ["primary", "backup"], state)

        with self.assertRaisesRegex(RuntimeError, "400 INVALID_ARGUMENT"):
            chain.invoke("test")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(backup.calls, 0)
        self.assertEqual(state["active_index"], 0)

    def test_all_transient_models_fail_with_sanitized_message(self):
        state = {"active_index": 0}
        chain = self.Fallback(
            [FakeModel("one", ["503 UNAVAILABLE"]), FakeModel("two", ["503 UNAVAILABLE"])],
            ["one", "two"],
            state,
        )
        with self.assertRaisesRegex(RuntimeError, "last_model=two, status=503"):
            chain.invoke("test")

    def test_download_cell_validates_archive_without_running_model(self):
        download_cell = self.source[6]
        self.assertIn("zf.testzip()", download_cell)
        self.assertIn("complete_report.md missing or empty", download_cell)
        self.assertIn("colab_files.download(str(archive))", download_cell)
        self.assertNotIn("TradingAgentsGraph(", download_cell)
        self.assertNotIn("ChatGoogleGenerativeAI", download_cell)


if __name__ == "__main__":
    unittest.main(verbosity=2)
