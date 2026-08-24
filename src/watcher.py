"""Event-driven intake (loop-engineering Loop 3, demo scale).

Watches data/inbox/ for new arrivals — .json packets or .txt faxes — and runs
each through the pipeline the moment it lands. The proposal appears in the
review app's queue; the source file moves to data/processed/.

Run alongside the app:
    python -m src.watcher
then drop a file:
    cp data/faxes/FAX-0001.txt data/inbox/

ponytail: 2-second polling loop — production would subscribe to the intake
queue (webhook/message bus) instead of polling a directory.
"""
import json
import shutil
import time
from pathlib import Path

from . import audit, extract, pipeline

ROOT = Path(__file__).parent.parent
INBOX = ROOT / "data" / "inbox"
PROCESSED = ROOT / "data" / "processed"


def ingest(path: Path) -> str:
    if path.suffix == ".txt":
        packet = extract.extract_from_text(path.read_text())
    else:
        packet = json.loads(path.read_text())

    # register the packet so the review app (and duplicate detection) sees it
    (pipeline.PACKETS_DIR / f"{packet['case_id']}.json").write_text(
        json.dumps(packet, indent=2))
    audit.log(packet["case_id"], "ingested", actor="watcher",
              details={"file": path.name,
                       "extraction": packet.get("extraction_source")})

    result = pipeline.process(packet)
    pipeline.store_proposal(result)

    PROCESSED.mkdir(exist_ok=True)
    shutil.move(str(path), PROCESSED / path.name)
    return (f"{packet['case_id']}: {len(result['findings'])} finding(s) "
            f"-> {result['route']['queue']}")


def main() -> None:
    INBOX.mkdir(exist_ok=True)
    print(f"Watching {INBOX} — drop .json packets or .txt faxes there. Ctrl-C to stop.")
    while True:
        for path in sorted(INBOX.glob("*")):
            if path.suffix in (".json", ".txt"):
                try:
                    print(f"[watcher] {path.name} arrived -> {ingest(path)}")
                except Exception as e:
                    print(f"[watcher] FAILED on {path.name}: {type(e).__name__}: {e}")
                    shutil.move(str(path), PROCESSED / f"FAILED-{path.name}")
        time.sleep(2)


if __name__ == "__main__":
    main()
