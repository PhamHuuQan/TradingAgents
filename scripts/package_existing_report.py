"""Package an existing TradingAgents report in Colab. Does not call any model/API.

In an already-running Colab runtime, run this in a new code cell:

    import urllib.request
    url = "https://raw.githubusercontent.com/PhamHuuQan/TradingAgents/feature/vietnam-market-foundation/scripts/package_existing_report.py"
    exec(compile(urllib.request.urlopen(url).read().decode("utf-8"),
                 "package_existing_report.py", "exec"),
         {"__name__": "__main__"})

It locates the latest FPT complete_report.md in the runtime, validates the ZIP,
and invokes Colab's browser download. It will never rerun TradingAgents.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

DEFAULT_REPORT_ROOTS = (
    Path("/root/.tradingagents/logs/reports"),
    Path("/content/TradingAgents/results/reports"),
    Path("/content/results/reports"),
)
DEFAULT_ARCHIVE = Path("/content/TradingAgents_FPT_report.zip")


def find_report_file(candidate=None, roots=DEFAULT_REPORT_ROOTS, ticker="FPT") -> Path:
    """Find a completed Markdown report from a run directory, report file, or reports root."""
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_file():
            if path.suffix.lower() == ".md":
                return path.resolve()
            raise FileNotFoundError(f"Given file is not a Markdown report: {path}")
        if not path.is_dir():
            raise FileNotFoundError(f"Report path does not exist: {path}")
        preferred = path / "complete_report.md"
        if preferred.is_file():
            return preferred.resolve()
        markdown_files = sorted(
            (p for p in path.glob("*.md") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if markdown_files and path.name.startswith(ticker.upper() + "_"):
            return markdown_files[0].resolve()
        roots = (path, *tuple(roots))

    prefix = ticker.upper() + "_"
    matches = []
    for root in roots:
        root = Path(root).expanduser()
        if not root.exists():
            continue
        if root.is_file() and root.suffix.lower() == ".md":
            matches.append(root)
            continue
        if not root.is_dir():
            continue
        matches.extend(p for p in root.glob(f"{prefix}*/complete_report.md") if p.is_file())
        if root.name.startswith(prefix) and (root / "complete_report.md").is_file():
            matches.append(root / "complete_report.md")
        if root.name == "reports":
            matches.extend(
                p for p in root.rglob("complete_report.md")
                if p.is_file() and p.parent.name.startswith(prefix)
            )

    unique = {p.resolve() for p in matches}
    if not unique:
        searched = ", ".join(str(Path(p)) for p in roots)
        raise FileNotFoundError(
            f"No completed {ticker} report found. Searched: {searched}. "
            "The Colab runtime containing the report may have been reset."
        )
    return max(unique, key=lambda p: p.stat().st_mtime)


def package_report(report_file, archive=DEFAULT_ARCHIVE) -> dict:
    """Package report plus sibling report assets; verify before replacing the ZIP."""
    report_file = Path(report_file).resolve()
    archive = Path(archive).resolve()
    if not report_file.is_file() or report_file.stat().st_size <= 0:
        raise FileNotFoundError(f"Report is missing or empty: {report_file}")

    report_dir = report_file.parent
    files = sorted(
        p for p in report_dir.rglob("*")
        if p.is_file() and not p.is_symlink() and p.resolve() != archive
    )
    if report_file not in files:
        files.append(report_file)
    files = sorted(set(p.resolve() for p in files))
    if not files:
        raise RuntimeError(f"No files found in report directory: {report_dir}")

    archive.parent.mkdir(parents=True, exist_ok=True)
    temp_archive = archive.with_suffix(archive.suffix + ".tmp")
    temp_archive.unlink(missing_ok=True)
    try:
        with ZipFile(temp_archive, "w", compression=ZIP_DEFLATED) as zf:
            for item in files:
                zf.write(item, arcname=f"{report_dir.name}/{item.relative_to(report_dir)}")

        with ZipFile(temp_archive, "r") as zf:
            names = zf.namelist()
            corrupt = zf.testzip()
            expected = f"{report_dir.name}/{report_file.relative_to(report_dir)}"
            if not names or corrupt:
                raise RuntimeError(f"ZIP verification failed: empty={not names}; corrupt={corrupt}")
            if expected not in names or zf.getinfo(expected).file_size <= 0:
                raise RuntimeError("ZIP verification failed: report is missing or empty")
        temp_archive.replace(archive)
    finally:
        temp_archive.unlink(missing_ok=True)

    return {
        "report_file": str(report_file),
        "report_bytes": report_file.stat().st_size,
        "archive": str(archive),
        "archive_bytes": archive.stat().st_size,
        "file_count": len(names),
        "files": names,
    }


def main():
    # Look at the two possible outputs from the original notebook, where
    # report_dir was mistakenly assigned to the complete_report.md file.
    namespace = globals()
    candidate = namespace.get("report_path") or namespace.get("report_dir")
    try:
        report_file = find_report_file(candidate)
    except FileNotFoundError:
        # If a stale global path points to something unavailable, retry using
        # only the standard report root. This still never starts the analysis.
        report_file = find_report_file()

    result = package_report(report_file)
    print(f"REPORT: {result['report_file']}")
    print(f"REPORT_BYTES: {result['report_bytes']}")
    print(f"ZIP_OK: {result['file_count']} files; {result['archive_bytes']:,} bytes")
    for name in result["files"]:
        print(f"  - {name}")

    try:
        from google.colab import files
    except ImportError:
        print(f"ZIP saved at: {result['archive']}")
        return result
    print("Downloading ZIP now. No Gemini/SSI/model calls were made.")
    files.download(result["archive"])
    return result


if __name__ == "__main__":
    main()
