"""Tests for config validation — precise error messages on schema drift."""
from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from kestrel.store.excel import read_sources, read_kestrel_config


def _make_workbook(sheets: dict[str, list[list]]):
    """Build a minimal openpyxl workbook from {sheetname: [[row], ...]}."""
    import openpyxl
    wb = openpyxl.Workbook()
    first = True
    for name, rows in sheets.items():
        if first:
            ws = wb.active
            ws.title = name
            first = False
        else:
            ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    return wb


def test_missing_sheet_raises_clear_error(tmp_path: Path):
    import openpyxl
    wb = _make_workbook({"Sources": [
        ["Source Name", "Type", "Active", "URL",
         "Trust Score (1-5)", "Signal Score (1-5)", "Noise Score (1-5)",
         "Priority Tier (1-5)", "Include in Morning Digest", "Include in Afternoon Digest"],
        ["Test", "Media", "Yes", "https://test.com", 4, 4, 2, 2, "Yes", "Yes"],
    ]})
    # Intentionally omit "Scoring" sheet — test using kestrel_config missing Categories_Domain
    path = tmp_path / "test.xlsx"
    wb.save(str(path))

    # Build a partial config workbook missing Categories_Domain
    wb2 = _make_workbook({
        "Categories_KPMG": [["Tag", "Description", "Active"], ["Cyber", "desc", "Yes"]],
        # Categories_Domain MISSING
        "Quotes": [["Quote", "Author", "Active"]],
        "Filters": [["Key", "Value", "Notes"]],
        "Escalation": [["Trigger", "Keywords", "Action", "Active"]],
        "Writing_Style": [["Rule_Group", "Rule", "Active"]],
        "Audience": [["Key", "Value"]],
    })
    path2 = tmp_path / "config.xlsx"
    wb2.save(str(path2))

    with pytest.raises(ValueError, match="Categories_Domain"):
        read_kestrel_config(path2)


def test_missing_column_raises_precise_error(tmp_path: Path):
    wb = _make_workbook({"Sources": [
        ["Source Name", "Type"],  # Missing required columns
        ["Test", "Media"],
    ]})
    path = tmp_path / "sources.xlsx"
    wb.save(str(path))
    with pytest.raises(ValueError, match="Active"):
        read_sources(path)


def test_valid_sources_parsed(tmp_path: Path):
    wb = _make_workbook({"Sources": [
        ["Source Name", "Type", "Active", "URL",
         "Trust Score (1-5)", "Signal Score (1-5)", "Noise Score (1-5)",
         "Priority Tier (1-5)", "Include in Morning Digest", "Include in Afternoon Digest",
         "Primary or Secondary", "Official Status", "Notes", "Sector", "Adjacent Domain",
         "LinkedIn URL", "ASX Ticker"],
        ["DoD AU", "Government", "Yes", "https://defence.gov.au",
         5, 5, 1, 1, "Yes", "Yes", "Primary", "Official", "", "Defence", "", "", ""],
        ["Deactivated", "Media", "No", "https://example.com",
         3, 3, 3, 3, "Yes", "Yes", "Secondary", "Independent", "", "Defence", "", "", ""],
    ]})
    path = tmp_path / "sources.xlsx"
    wb.save(str(path))
    sources = read_sources(path)
    assert len(sources) == 2
    active = [s for s in sources if s["active"]]
    inactive = [s for s in sources if not s["active"]]
    assert len(active) == 1
    assert len(inactive) == 1
    assert active[0]["trust_score"] == 5.0
