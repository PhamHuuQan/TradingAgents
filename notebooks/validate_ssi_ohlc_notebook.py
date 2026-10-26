#!/usr/bin/env python3
"""Offline validation for the SSI FastConnect Colab notebook.

This checks notebook syntax, the installed official SDK's API contract, data mapping,
and secret redaction. It does NOT call SSI or require real credentials.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import ssi_sdk
from ssi_sdk import Auth, Config, Data
from ssi_sdk.enums import Timeframe
from ssi_sdk.services.market_data import MarketDataService

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "SSI_FastConnect_OHLC_FPT_Fixed.ipynb"


def cell_source(cell: dict) -> str:
    source = cell.get("source", [])
    return "".join(source) if isinstance(source, list) else str(source)


def strip_ipython_magics(source: str) -> str:
    # The notebook has one install line (%pip) which only runs inside IPython.
    return "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith("%pip ")
    )


def check_notebook_and_sdk() -> list[str]:
    raw = NOTEBOOK.read_text(encoding="utf-8")
    nb = json.loads(raw)
    assert nb.get("nbformat") == 4, "Unsupported notebook format"
    cells = nb.get("cells", [])
    assert len(cells) == 6, f"Expected 6 cells; found {len(cells)}"
    code_cells = [cell for cell in cells if cell.get("cell_type") == "code"]
    assert len(code_cells) == 5, f"Expected 5 code cells; found {len(code_cells)}"

    for index, cell in enumerate(cells):
        if cell.get("cell_type") == "code":
            code = strip_ipython_magics(cell_source(cell))
            compile(code, f"{NOTEBOOK.name}:cell-{index}", "exec")

    assert ssi_sdk.__version__ == "3.3.2", f"SDK version drifted: {ssi_sdk.__version__}"
    assert callable(getattr(MarketDataService, "get_ohlc_1day_historical", None))
    assert callable(getattr(MarketDataService, "get_ohlc_all", None))
    params = __import__("inspect").signature(MarketDataService.get_ohlc_all).parameters
    for name in ("symbol", "timeframe", "from_date", "to_date", "size", "ascending"):
        assert name in params, f"SDK get_ohlc_all missing parameter {name}"
    assert Timeframe.DAY_1.value == "1d"

    probe = Config(client_id="client-test", api_key="key-test", api_secret="secret-test")
    rendered = repr(probe)
    assert "secret-test" not in rendered, "Config repr exposes API secret"
    assert "key-test" not in rendered, "Config repr exposes full API key"

    assert "get_ohlc_all(" in raw, "Notebook is not using SDK pagination helper"
    assert "requests.get(" not in raw and "requests.request(" not in raw, "Notebook bypasses SDK"
    assert "private_key" in raw, "Expected documentation comment about private_key to be present"
    code_text = "\n".join(cell_source(cell) for cell in cells if cell.get("cell_type") == "code")
    assert not re.search(r"(?i)(api_secret|api_key|client_id)\s*=\s*['\"][^'\"]{8,}['\"]", code_text), "Possible hard-coded credential"
    return [
        "PASS: notebook JSON and all Python cells compile",
        "PASS: SSI SDK 3.3.2 method signatures and day timeframe",
        "PASS: Config repr masks API secret and full API key",
        "PASS: notebook calls SDK pagination; no direct REST bypass",
        "PASS: no obvious hard-coded credentials in notebook",
    ]


@dataclass
class FakeBar:
    symbol: str
    trading_date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    value: float


def _globals_for_notebook(bars: list[FakeBar], *, error: Exception | None = None) -> dict:
    # Fake clients deliberately implement only the read-only API used by this notebook.
    class FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAuth:
        def __init__(self, config):
            self.config = config
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def authenticate(self):
            return object()

    class FakeMarketData:
        def get_ohlc_all(self, symbol, timeframe, from_date=None, to_date=None, size=100, ascending=False):
            assert symbol == "FPT"
            assert timeframe.value == "1d"
            assert from_date and to_date and from_date <= to_date
            if error is not None:
                raise error
            return bars

    class FakeData:
        def __init__(self, auth):
            self.market_data = FakeMarketData()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None

    class FakeTimeframe:
        DAY_1 = SimpleNamespace(value="1d")

    return {
        "CLIENT_ID": "client-test-secret",
        "API_KEY": "key-test-secret",
        "API_SECRET": "api-secret-test-secret",
        "Config": FakeConfig,
        "Auth": FakeAuth,
        "Data": FakeData,
        "Timeframe": FakeTimeframe,
        "pd": pd,
        "re": re,
        "display": lambda dataframe: display_buffer.append(dataframe.copy()),
    }


def check_mocked_runtime() -> list[str]:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    core = strip_ipython_magics(cell_source(nb["cells"][4]))
    normalizer = strip_ipython_magics(cell_source(nb["cells"][5]))
    samples = [
        FakeBar("FPT", "2026/10/23 00:00:00", 100.0, 105.0, 99.0, 103.0, 123456, 123.4),
        FakeBar("FPT", "2026/10/26 00:00:00", 103.0, 108.0, 102.0, 107.0, 234567, 234.5),
    ]

    global display_buffer
    display_buffer = []
    env = _globals_for_notebook(samples)
    # Run the actual notebook cells, substituting only the remote SSI client with a fake.
    exec(compile(core, "ssi_notebook_core_cell", "exec"), env)
    exec(compile(normalizer, "ssi_notebook_normalizer_cell", "exec"), env)
    frame = display_buffer[-1]
    assert len(frame) == 2
    assert list(frame.columns) == ["time", "symbol", "open", "high", "low", "close", "volume", "value"]
    assert frame.iloc[0]["symbol"] == "FPT"
    assert float(frame.iloc[0]["close"]) == 103.0
    assert int(frame.iloc[1]["volume"]) == 234567
    assert str(frame.iloc[0]["time"].date()) == "2026-10-23"

    # Duplicate trading dates must fail rather than silently corrupt the candles.
    display_buffer = []
    duplicate_env = _globals_for_notebook([samples[0], samples[0]])
    exec(compile(core, "ssi_notebook_core_duplicate_cell", "exec"), duplicate_env)
    try:
        exec(compile(normalizer, "ssi_notebook_normalizer_duplicate_cell", "exec"), duplicate_env)
    except ValueError as exc:
        assert "trùng lặp" in str(exc)
    else:
        raise AssertionError("Duplicate dates were not rejected")

    # A failed remote API call must not expose any of the credentials.
    display_buffer = []
    fake_error = SimpleNamespace(
        message="bad request bearer eyJabcdefghijklmno.abcdefghijklmno.abcdefghi api-secret-test-secret",
        status_code=400,
        code="400213",
    )
    # Add SDK-like metadata without including real secrets anywhere.
    class FakeAPIError(Exception):
        message = fake_error.message
        status_code = 400
        code = "400213"
    error_env = _globals_for_notebook([], error=FakeAPIError())
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            exec(compile(core, "ssi_notebook_core_error_cell", "exec"), error_env)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Notebook should fail visibly when the API fails")
    logged = output.getvalue()
    for secret in ("client-test-secret", "key-test-secret", "api-secret-test-secret"):
        assert secret not in logged, "Error output leaked a credential"
    assert "HTTP=400" in logged and "400213" in logged
    assert "[REDACTED]" in logged or "[REDACTED_TOKEN]" in logged

    # Invalid high/low relationships must never be silently passed downstream.
    display_buffer = []
    bad_bar = FakeBar("FPT", "2026/10/23 00:00:00", 100.0, 98.0, 99.0, 103.0, 123456, 123.4)
    bad_env = _globals_for_notebook([bad_bar])
    exec(compile(core, "ssi_notebook_core_invalid_cell", "exec"), bad_env)
    try:
        exec(compile(normalizer, "ssi_notebook_normalizer_invalid_cell", "exec"), bad_env)
    except ValueError as exc:
        assert "vi phạm quan hệ OHLC" in str(exc)
    else:
        raise AssertionError("Invalid OHLC candle was not rejected")

    # No bars for a 60-calendar-day FPT window is not reported as a successful test.
    empty_env = _globals_for_notebook([])
    try:
        exec(compile(core, "ssi_notebook_core_empty_cell", "exec"), empty_env)
    except RuntimeError as exc:
        assert "0 nến" in str(exc)
    else:
        raise AssertionError("An empty SSI result was reported as success")

    return [
        "PASS: actual notebook cells map fake SDK OHLC bars into the expected DataFrame",
        "PASS: duplicate dates fail loudly",
        "PASS: API error output includes status/code but redacts credentials and JWT-like tokens",
    ]


if __name__ == "__main__":
    results = check_notebook_and_sdk() + check_mocked_runtime()
    print("\n".join(results))
    print(f"\nALL {len(results)} OFFLINE CHECKS PASSED. No live SSI request was made.")
