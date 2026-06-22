"""CLI entry point: python -m kestrel run --slot morning|afternoon"""
from __future__ import annotations
import argparse
import logging
import os
import sys
from pathlib import Path


def _setup_logging(run_date: str, slot: str, log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"kestrel_{slot}_{run_date}.log"
    # Reconfigure stdout to UTF-8 so Windows cp1252 never crashes on non-ASCII log messages
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fmt = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Suppress per-request HTTP noise — every source makes many requests at INFO
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Tenacity retry logs go to DEBUG only
    logging.getLogger("tenacity").setLevel(logging.DEBUG)


def main() -> None:
    # Load .env if present (never commit real .env)
    _load_dotenv()

    parser = argparse.ArgumentParser(
        prog="kestrel",
        description="Kestrel — Australian Defence brief generator",
    )
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="Generate a brief for the given slot")
    run_p.add_argument(
        "--slot", choices=["morning", "afternoon"], required=True,
        help="Which brief to generate"
    )
    run_p.add_argument(
        "--project-root", default=None,
        help="Path to project root (default: parent of src/)"
    )

    audit_p = sub.add_parser("audit", help="Discover working collection method for every source")
    audit_p.add_argument("--workers", type=int, default=20)
    audit_p.add_argument("--timeout", type=int, default=20)
    audit_p.add_argument("--hours", type=int, default=48)
    audit_p.add_argument("--dry-run", action="store_true")
    audit_p.add_argument("--project-root", default=None)

    args = parser.parse_args()

    if args.command == "audit":
        root = Path(args.project_root).resolve() if args.project_root else \
               Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(root))  # make scripts/ importable
        from scripts.audit_sources import run_audit
        run_audit(root, args.workers, args.timeout, args.hours, args.dry_run)
        sys.exit(0)

    if args.command != "run":
        parser.print_help()
        sys.exit(0)

    # Resolve project root
    if args.project_root:
        root = Path(args.project_root).resolve()
    else:
        # When run as `python -m kestrel`, __file__ is src/kestrel/__main__.py
        root = Path(__file__).resolve().parent.parent.parent

    from datetime import datetime, timezone
    import zoneinfo

    # Bootstrap enough to get the run date for log setup
    run_date = datetime.now(tz=zoneinfo.ZoneInfo("Australia/Sydney")).strftime("%Y-%m-%d")
    out_dir = root / "output" / run_date
    _setup_logging(run_date, args.slot, out_dir)

    log = logging.getLogger("kestrel")

    try:
        from kestrel.config import load_config
        from kestrel.store.db import KestrelDB
        from kestrel.pipeline import run

        log.info("Loading config from %s", root)
        cfg = load_config(root)

        db_path = cfg.paths.data_dir / "kestrel.db"
        db = KestrelDB(db_path)

        log.info("Starting %s run", args.slot)
        result = run(slot=args.slot, cfg=cfg, db=db)
        db.close()

        sys.exit(0)

    except FileNotFoundError as exc:
        print(f"\nERROR: {exc}")
        print("Check that all master files are present. See SPEC.md §4.")
        sys.exit(1)
    except ValueError as exc:
        print(f"\nCONFIG ERROR: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as exc:
        logging.exception("Unexpected error: %s", exc)
        sys.exit(1)


def _load_dotenv() -> None:
    """Load .env file if present — never logs the key value."""
    env_path = Path(".env")
    if not env_path.exists():
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = val.strip().strip('"').strip("'")
    except Exception:
        pass


if __name__ == "__main__":
    main()
