"""Render a Brief to self-contained HTML with base64-embedded images."""
from __future__ import annotations
import base64
import logging
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from kestrel.models import Brief

log = logging.getLogger(__name__)

# Brand palette — sourced from kestrel_brand_pack_v1 execution instructions.
# All email colours are driven by this dict so they stay consistent across themes.
_PALETTE: dict[str, dict[str, str]] = {
    "light": dict(
        outer_bg="#FFFFFF",     # White page background
        container="#FFFFFF",    # White card
        stripe="#EDECEF",       # Background mist — date bar, footer, quote boxes
        body="#2F364A",         # Navy deep — primary text
        muted="#6B7280",        # Mid grey — secondary/footer text
        violet="#8A6BCD",       # Violet — section headings, watchpoints, quote accents
        blue="#2568D0",         # Royal blue — priority headings, links
        border="#CDD0DF",       # Ice — dividers and rule lines
        tag_bg="#8A6BCD",       # Violet chip background
        tag_text="#FFFFFF",     # White chip text
        quote_bg="#EDECEF",     # Quote block background (mist grey)
        angle_bg="#F0EBF8",     # KPMG angle sidebar background (light violet tint)
        angle_bdr="#8A6BCD",    # KPMG angle sidebar border
        hdr_bg="#2F364A",       # Fallback header background
        hdr_sub="#8A6BCD",      # Fallback header sub-label colour
        late_bg="#6451B3",      # Indigo — late-run banner
        footer_bg="#EDECEF",    # Footer background (mist grey)
    ),
    "dark": dict(
        outer_bg="#2F364A",     # Navy deep
        container="#3A4152",    # Navy mid — card background
        stripe="#2F364A",       # Navy deep — stripe rows
        body="#EDECEF",         # Background mist — primary text on dark
        muted="#9CA3AF",        # Cool grey — secondary text on dark
        violet="#8A6BCD",       # Violet — same both modes
        blue="#5B8FF9",         # Lighter royal blue for dark mode legibility
        border="#4A5268",       # Visible divider against navy mid
        tag_bg="#6451B3",       # Indigo chip background
        tag_text="#FFFFFF",     # White chip text
        quote_bg="#3A4152",     # Quote block background
        angle_bg="#3A4152",     # KPMG angle sidebar background
        angle_bdr="#6451B3",    # Indigo angle border
        hdr_bg="#2F364A",       # Fallback header background
        hdr_sub="#8A6BCD",      # Fallback header sub-label colour
        late_bg="#6451B3",      # Indigo late-run banner
        footer_bg="#2F364A",    # Footer background
    ),
}


def _b64_image(path: Path) -> str:
    if path.exists():
        return base64.b64encode(path.read_bytes()).decode()
    log.warning("Image not found: %s", path)
    return ""


def render_html(brief: Brief, assets_dir: Path, theme: str, project_root: Path) -> str:
    templates_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=True,  # always escape — template uses |safe where HTML is intentional
    )
    template = env.get_template("email.html.j2")

    brand_dir = assets_dir / "brand" / "kestrel_brand_rebuild_pack"

    # Outlook 600×200 is the recommended default per brand rebuild guide README
    header_path = brand_dir / "marketing" / "email" / f"outlook_header_600x200_{theme}.png"
    # 128 px symbol for footer — transparent on light bg, dark tile on dark bg
    icon_variant = "transparent" if theme == "light" else "dark_tile"
    icon_path = brand_dir / "icons" / f"kestrel_symbol_128_{icon_variant}.png"

    try:
        run_date_obj = date.fromisoformat(brief.run_date)
        run_date_display = run_date_obj.strftime("%A %d-%b-%y")  # e.g. Thursday 19-Jun-26
    except (ValueError, AttributeError):
        run_date_display = brief.run_date

    context = {
        "brief": brief,
        "run_date_display": run_date_display,
        "header_b64": _b64_image(header_path),
        "icon_b64": _b64_image(icon_path),
        "theme": theme,
        "c": _PALETTE.get(theme, _PALETTE["light"]),
    }
    return template.render(**context)
