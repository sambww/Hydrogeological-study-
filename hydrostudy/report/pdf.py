"""DOCX -> PDF with LibreOffice Writer (review copy; the DOCX is the deliverable).

Requires the Writer component (Debian/Ubuntu: `apt-get install libreoffice-writer`). A one-time probe conversion
decides availability so a core-only install does not produce silent failures."""

from __future__ import annotations

import functools
import shutil
import subprocess
import tempfile
from pathlib import Path


def _exe():
    return shutil.which("soffice") or shutil.which("libreoffice")


def _convert(src: Path, out_dir: Path, timeout_s: int) -> Path | None:
    exe = _exe()
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as profile:
        cmd = [exe, "--headless", "--norestore", f"-env:UserInstallation=file://{profile}", "--convert-to", "pdf",
               "--outdir", str(out_dir), str(src)]
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return None
    pdf = out_dir / (src.stem + ".pdf")
    return pdf if pdf.exists() and pdf.stat().st_size > 0 else None


@functools.lru_cache(maxsize=1)
def soffice_available() -> bool:
    """True only if LibreOffice can actually convert a trivial DOCX (Writer filters installed)."""
    if not _exe():
        return False
    try:
        from docx import Document
    except ImportError:
        return False
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "probe.docx"
        doc = Document()
        doc.add_paragraph("probe")
        doc.save(str(src))
        return _convert(src, Path(d), 120) is not None


def convert_to_pdf(docx_path: Path, timeout_s: int = 180) -> Path | None:
    if not soffice_available():
        return None
    docx_path = Path(docx_path)
    return _convert(docx_path, docx_path.parent, timeout_s)


def pdf_status_message() -> str:
    if not _exe():
        return "PDF not produced: LibreOffice is not installed (install libreoffice-writer to enable PDF export)."
    if not soffice_available():
        return "PDF not produced: LibreOffice is installed without the Writer component (apt-get install libreoffice-writer)."
    return ""
