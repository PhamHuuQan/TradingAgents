"""Package an existing TradingAgents report and download it in Colab.

This helper does NOT call Gemini, SSI, or rerun the analysis. Intended usage in
an already-running Colab notebook that still has its report files.

If notebook variables report_path/report_dir exist, they are reused. Otherwise
the helper searches the usual TradingAgents report directories.
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


def _looks_like_report_dir(path: Path) -> bool:
    return path.is_dir() and (
        (path / "complete_report.md").is_file()
        or any(path.glob("*.md"))
    )


def find_report_file(candidate: str | Path | None = None,
                     roots: tuple[Path, ...] = DEFAULT_REPORT_ROOTS,
                     ticker: str = "FPT") -> Path:
    """Find a report Markdown file from either a file path or a directory."""
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_file():
            if path.name.lower() == "complete_report.md" or path.suffix.lower() == ".md":
                return path.resolve()
            raise FileNotFoundError(f"The given file is not a Markdown report: {path}")
        if _looks_like_report_dir(path):
            preferred = path / "complete_report.md"
            if preferred.is_file():
                return preferred.resolve()
            md_files = sorted(path.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if md_files:
                return md_files[0].resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Report path does not exist: {path}")
        roots = (path, *roots)

    matches: list[Path] = []
    prefix = ticker.upper() + "_"
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
            "The original report may have been lost if its Colab runtime was reset."
        )
    return max(unique, key=lambda p: p.stat().st_mtime)


def package_report(report_file: str | Path,
                   archive: str | Path = DEFAULT_ARCHIVE) -> dict:
    """Package a report and its sibling artifacts; validate before replacing ZIP."""
    report_file = Path(report_file).resolve()
    archive = Path(archive).resolve()
    if not report_file.is_file() or report_file.stat().st_size == 0:
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
            if expected not in names:
                raise RuntimeError("ZIP verification failed: complete report is missing")
            if zf.getinfo(expected).file_size <= 0:
                raise RuntimeError("ZIP verification failed: complete report entry is empty")
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


def main() -> dict:
    namespace = globals()
    candidate = namespace.get("report_path")
    if candidate is None:
        candidate = namespace.get("report_dir")
    try:
        report_file = find_report_file(candidate)
    except FileNotFoundError:
        report_file = find_report_file()

    result = package_report(report_file)
    print(f"Report found: {result['report_file']}")
    print(f"Report size: {result['report_bytes']:,} bytes")
    print(f"ZIP verified: {result['file_count']} files, {result['archive_bytes']:,} bytes")
    print("Files inside ZIP:")
    for name in result["files"]:
        print(f" - {name}")

    try:
        from google.colab import files as colab_files
    except ImportError:
        print(f"Archive created locally at: {result['archive']}")
        return result
    print("Starting browser download. No model/API calls will be made.")
    colab_files.download(result["archive"])
    return result


if __name__ == "__main__":
    main()
