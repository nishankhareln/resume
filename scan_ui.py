"""
scan_ui
=======

A "resume scanner" visual that mimics the HootBot-style UI:
  - Left column: PDF page-1 preview
  - Right column: animated checklist of analysis steps that flip
    pending → active → done as each step completes
  - Bottom-of-left: status message + sliding progress bar

Usage:

    from scan_ui import render_scan_steps

    bucket = {}  # closure-friendly mutable state

    steps = [
        {
            "label": "PDF Parse & Compatibility",
            "desc":  "Extracting text from your resume.",
            "fn":    lambda: bucket.update({"text": extract_text_from_pdf(uploaded)}),
        },
        {
            "label": "Resume Structuring (AI)",
            "desc":  "Identifying skills, experience and contact info.",
            "fn":    lambda: bucket.update({"info": parse_resume(bucket["text"], llm)}),
        },
        # ... more steps ...
    ]

    render_scan_steps(uploaded, steps, brand="HootBot AI")
    # After return, bucket has all the intermediate results.

Implementation note: Streamlit's `st.empty()` returns a placeholder whose
contents can be replaced in-place without triggering a full script rerun,
which is what lets each step animate smoothly.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, List, TypedDict

import streamlit as st

logger = logging.getLogger(__name__)


class ScanStep(TypedDict):
    label: str
    desc: str
    fn: Callable[[], None]


SCAN_CSS = """
<style>
.scan-wrap {
    border: 1px solid #e8e8ef;
    border-radius: 14px;
    padding: 18px 22px;
    background: linear-gradient(180deg, #ffffff 0%, #fdfbff 100%);
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.scan-header {
    font-weight: 600;
    font-size: 1.05em;
    margin-bottom: 14px;
    color: #1f2937;
}
.scan-step {
    display: flex;
    gap: 14px;
    padding: 12px 4px;
    border-bottom: 1px solid #f0f0f5;
    align-items: flex-start;
    transition: opacity 0.25s ease;
}
.scan-step:last-child { border-bottom: none; }
.scan-step .dot {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 3px;
    border: 2px solid #d1d5db;
    background: #ffffff;
}
.scan-step.pending  .dot { border-color: #d1d5db; background: #ffffff; }
.scan-step.active   .dot { border-color: #3b82f6; background: #3b82f6;
    box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.18);
    animation: scan-pulse 1.1s ease-in-out infinite;
}
.scan-step.done     .dot { border-color: #10b981; background: #10b981; }
.scan-step.error    .dot { border-color: #ef4444; background: #ef4444; }
.scan-step.pending  { opacity: 0.55; }
.scan-step .label   {
    font-weight: 600;
    color: #111827;
    font-size: 0.98em;
}
.scan-step.done .label::after {
    content: "  ✓";
    color: #10b981;
}
.scan-step .desc    {
    color: #6b7280;
    font-size: 0.85em;
    margin-top: 2px;
}
@keyframes scan-pulse {
    0%   { box-shadow: 0 0 0 0   rgba(59, 130, 246, 0.45); }
    70%  { box-shadow: 0 0 0 8px rgba(59, 130, 246, 0); }
    100% { box-shadow: 0 0 0 0   rgba(59, 130, 246, 0); }
}

.scan-wait {
    text-align: center;
    color: #374151;
    margin-top: 12px;
    font-size: 0.95em;
}
.scan-wait .brand {
    font-weight: 700;
    color: #3b82f6;
}

.scan-preview {
    border: 1px solid #e8e8ef;
    border-radius: 14px;
    padding: 8px;
    background: #ffffff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    position: relative;
    overflow: hidden;
}
.scan-preview::after {
    content: "";
    position: absolute;
    left: 0; right: 0;
    height: 50px;
    background: linear-gradient(180deg,
                rgba(59,130,246,0) 0%,
                rgba(59,130,246,0.35) 50%,
                rgba(59,130,246,0) 100%);
    animation: scan-laser 2.4s linear infinite;
    pointer-events: none;
}
.scan-preview.done::after { display: none; }
@keyframes scan-laser {
    0%   { top: -50px; }
    100% { top: 110%;  }
}
</style>
"""


def _pdf_first_page_image(uploaded_file) -> bytes | None:
    """Render page 1 of the uploaded PDF to PNG bytes using PyMuPDF.
    Returns None on failure (caller falls back to a placeholder)."""
    try:
        import fitz  # PyMuPDF
        uploaded_file.seek(0)
        data = uploaded_file.read()
        uploaded_file.seek(0)  # reset for downstream readers
        doc = fitz.open(stream=data, filetype="pdf")
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4))
        out = pix.tobytes("png")
        doc.close()
        return out
    except Exception as e:
        logger.warning(f"PDF preview render failed: {e}")
        return None


def _step_html(step: ScanStep, status: str) -> str:
    """Render one step as a stand-alone div. status: pending|active|done|error."""
    return (
        f'<div class="scan-step {status}">'
        f'<div class="dot"></div>'
        f'<div>'
        f'<div class="label">{step["label"]}</div>'
        f'<div class="desc">{step["desc"]}</div>'
        f'</div>'
        f'</div>'
    )


def render_scan_steps(
    uploaded_file,
    steps: List[ScanStep],
    brand: str = "AI Resume Scanner",
    min_step_seconds: float = 0.35,
) -> None:
    """Render the scanner UI and execute each step's callable in order.

    Args:
        uploaded_file: Streamlit UploadedFile (a PDF).
        steps: list of {label, desc, fn}. fn is a parameterless callable —
            results should flow back via closures / session_state.
        brand: brand name shown in the wait message.
        min_step_seconds: artificial floor so very fast steps remain visible.
    """
    st.markdown(SCAN_CSS, unsafe_allow_html=True)

    col_pdf, col_steps = st.columns([1, 1.3])

    with col_pdf:
        img_bytes = _pdf_first_page_image(uploaded_file)
        preview_html_holder = st.empty()
        if img_bytes:
            import base64
            b64 = base64.b64encode(img_bytes).decode("ascii")
            preview_html_holder.markdown(
                f'<div class="scan-preview" id="scan-preview">'
                f'<img src="data:image/png;base64,{b64}" style="width:100%;border-radius:8px;" />'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            preview_html_holder.info("Could not render PDF preview, but analysis will continue.")
        wait_msg = st.empty()

    with col_steps:
        st.markdown(
            f'<div class="scan-header">⚡ {brand} is scanning your resume</div>',
            unsafe_allow_html=True,
        )
        # One Streamlit placeholder per step → each can be re-rendered in place
        step_phs = [st.empty() for _ in steps]
        # Render all as pending first
        for ph, step in zip(step_phs, steps):
            ph.markdown(_step_html(step, "pending"), unsafe_allow_html=True)
        progress = st.progress(0)

    total = max(1, len(steps))
    wait_msg.markdown(
        f'<div class="scan-wait">Please wait for a while<br/>'
        f'<span class="brand">{brand}</span> is scanning your CV</div>',
        unsafe_allow_html=True,
    )

    failures: List[str] = []
    for i, (ph, step) in enumerate(zip(step_phs, steps)):
        ph.markdown(_step_html(step, "active"), unsafe_allow_html=True)
        t0 = time.time()
        try:
            step["fn"]()
            status = "done"
        except Exception as e:
            logger.exception(f"Scan step '{step['label']}' failed.")
            status = "error"
            failures.append(f"{step['label']}: {e}")
        # Enforce minimum visible duration so animation feels even
        elapsed = time.time() - t0
        if elapsed < min_step_seconds:
            time.sleep(min_step_seconds - elapsed)
        ph.markdown(_step_html(step, status), unsafe_allow_html=True)
        progress.progress((i + 1) / total)

    # Final state: stop the laser by toggling the class
    if img_bytes:
        import base64
        b64 = base64.b64encode(img_bytes).decode("ascii")
        preview_html_holder.markdown(
            f'<div class="scan-preview done">'
            f'<img src="data:image/png;base64,{b64}" style="width:100%;border-radius:8px;" />'
            f'</div>',
            unsafe_allow_html=True,
        )

    if failures:
        wait_msg.markdown(
            f'<div class="scan-wait" style="color:#ef4444;">'
            f'Some steps failed:<br/><span style="font-size:0.85em;">{"<br/>".join(failures)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        wait_msg.markdown(
            f'<div class="scan-wait" style="color:#10b981;">'
            f'✨ Analysis complete!<br/><span style="color:#6b7280;font-size:0.85em;">'
            f'Open any tab above to explore your career report.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
