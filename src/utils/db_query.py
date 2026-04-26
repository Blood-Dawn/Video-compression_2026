#db_query
import argparse
from datetime import datetime, timedelta, UTC
from src.utils.db import query_by_type

def main():
    parser = argparse.ArgumentParser(description="Query metadata DB")

    parser.add_argument("--camera", type=str, help="Camera ID")
    parser.add_argument("--last-hours", type=int, help="Lookback window")
    parser.add_argument("--type", nargs="+", required=True, help="Object types")
    parser.add_argument("--min-roi", type=int, help="Minimum ROI detections")
    parser.add_argument("--start-time", type=str)
    parser.add_argument("--end-time", type=str)

    args = parser.parse_args()

    end_time = datetime.now(UTC)
    start_time = None

    if args.last_hours:
        start_time = end_time - timedelta(hours=args.last_hours)
        args.start_time = start_time.strftime("%Y%m%dT%H%M%SZ")
        args.end_time = end_time.strftime("%Y%m%dT%H%M%SZ")

    results = query_by_type(
        object_type=args.type,
        camera_id=args.camera,
        start_time=args.start_time,
        end_time=args.end_time,
        min_roi_count=args.min_roi,
        db_path="outputs/metadata.db"
    )
    for row in results:
        print(row)

if __name__ == "__main__":
    main()