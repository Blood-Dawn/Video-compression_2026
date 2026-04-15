#db_query
import argparse
import datetime
from src.utils.db import query_by_type

def main():
    parser = argparse.ArgumentParser(description="Query metadata DB")

    parser.add_argument("--camera", type=str, help="Camera ID")
    parser.add_argument("--last-hours", type=int, help="Lookback window")
    parser.add_argument("--type", required=True, help="Object type")

    args = parser.parse_args()

    end_time = datetime.datetime.utcnow()
    start_time = None

    if args.last_hours:
        start_time = end_time - datetime.timedelta(hours=args.last_hours)

    results = query_by_type(
        object_type=args.type,
        camera_id=args.camera,
        start_time=start_time.strftime("%Y%m%dT%H%M%SZ") if start_time else None,
        end_time=end_time.strftime("%Y%m%dT%H%M%SZ"),
        db_path="outputs/metadata.db" 
    )

    for row in results:
        print(row)

if __name__ == "__main__":
    main()