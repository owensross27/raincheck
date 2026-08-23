"""Recreate the two bus topics to spec C (ticket 10): six partitions, zstd, delete
retention 48 h, no compaction.

IRREVERSIBLE KNOB: partition count is fixed at creation, so getting there from today's
one-partition topics means delete + create - deleting a topic drops every retained
message on it. Bronze is the record (Kafka is a byproduct), so nothing durable is lost,
but this is a manual `make topics`, never run automatically. The archiver's producer
sets allow.auto.create.topics=False, so a topic missing mid-recreate fails loudly there
instead of being silently auto-created at one partition.

Usage: python -m raincheck.topics
"""
import os
import sys
import time

from confluent_kafka.admin import AdminClient, NewTopic

TOPICS = ["raincheck.bus.vp", "raincheck.bus.tu"]
CONFIG = {"compression.type": "zstd", "cleanup.policy": "delete",
          "retention.ms": str(48 * 3600 * 1000)}


def main() -> None:
    admin = AdminClient({"bootstrap.servers": os.environ.get("RAINCHECK_KAFKA") or "localhost:9092"})
    try:
        existing = admin.list_topics(timeout=10).topics
    except Exception as exc:
        sys.exit(f"no broker: {exc}")
    doomed = [t for t in TOPICS if t in existing]
    if doomed:
        for t, f in admin.delete_topics(doomed, operation_timeout=30).items():
            try:
                f.result()
                print(f"deleted {t}")
            except Exception as exc:  # per-topic: one failure must not strand the other
                print(f"delete {t}: {exc}", file=sys.stderr)
    for _ in range(10):  # deletion completes asynchronously; create only what's missing
        missing = [t for t in TOPICS if t not in admin.list_topics(timeout=10).topics]
        if not missing:
            break
        for t, f in admin.create_topics(
            [NewTopic(t, num_partitions=6, replication_factor=1, config=CONFIG) for t in missing],
            operation_timeout=30,
        ).items():
            try:
                f.result()
                print(f"created {t}: 6 partitions, zstd, delete retention 48h")
            except Exception as exc:
                print(f"create {t}: {exc}", file=sys.stderr)
        time.sleep(2)
    # post-condition: the knob either landed everywhere or this run failed loudly
    md = admin.list_topics(timeout=10).topics
    bad = {t: (len(md[t].partitions) if t in md else 0) for t in TOPICS
           if t not in md or len(md[t].partitions) != 6}
    if bad:
        sys.exit(f"topics NOT at spec (partitions by topic: {bad}) - rerun make topics; "
                 f"if it persists, stop the archiver LaunchAgent first "
                 f"(launchctl bootout gui/$(id -u)/com.raincheck.archiver)")


if __name__ == "__main__":
    main()
