# db_query — CLI for querying the segment metadata database
import argparse
from datetime import datetime, timedelta, timezone

from src.utils.db import query_by_type


def main():
    parser = argparse.ArgumentParser(description="Query metadata DB")

    parser.add_argument("--camera", type=str, help="Camera ID")
    parser.add_argument("--last-hours", type=int, help="Lookback window in hours")
    parser.add_argument("--type", nargs="+", required=True,
                        help="Object type(s) to filter — e.g. vehicle person")
    parser.add_argument("--min-roi", type=int, help="Minimum ROI detection count")
    parser.add_argument("--start-time", type=str,
                        help="Start timestamp (YYYYMMDDTHHMMSSz)")
    parser.add_argument("--end-time", type=str,
                        help="End timestamp (YYYYMMDDTHHMMSSz)")

    args = parser.parse_args()

    if args.last_hours:
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(hours=args.last_hours)
        args.start_time = start_dt.strftime("%Y%m%dT%H%M%SZ")
        args.end_time = end_dt.strftime("%Y%m%dT%H%M%SZ")

    results = query_by_type(
        object_type=args.type,
        camera_id=args.camera,
        start_time=args.start_time,
        end_time=args.end_time,
        min_roi_count=args.min_roi,
        db_path="outputs/metadata.db",
    )

    for row in results:
        print(row)


if __name__ == "__main__":
    main()
