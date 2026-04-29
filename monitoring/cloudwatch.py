"""
Monitoring & Logging Setup - CloudWatch (LocalStack)
Mon: Dien Toan Dam May

Chuc nang:
- Xem logs Lambda tu CloudWatch
- Do hieu nang: cold start, execution time
- Xuat bao cao benchmark ra console
"""

import boto3
import json
import time
import os
import statistics

LOCALSTACK_URL = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
FUNCTION_NAME  = "image-processor"
LOG_GROUP      = f"/aws/lambda/{FUNCTION_NAME}"


def get_clients():
    config = dict(
        endpoint_url=LOCALSTACK_URL,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    return boto3.client("logs", **config), boto3.client("lambda", **config)


# -------------------------------------------------------------------
# Xem logs Lambda
# -------------------------------------------------------------------
def get_recent_logs(limit=20):
    """Lay log gan nhat cua Lambda function."""
    logs_client, _ = get_clients()
    print(f"\n{'='*55}")
    print(f"  Lambda Logs: {FUNCTION_NAME}")
    print(f"{'='*55}")

    try:
        streams = logs_client.describe_log_streams(
            logGroupName=LOG_GROUP,
            orderBy="LastEventTime",
            descending=True,
            limit=3,
        )["logStreams"]

        if not streams:
            print("  (Chua co log nao)")
            return

        for stream in streams:
            events = logs_client.get_log_events(
                logGroupName=LOG_GROUP,
                logStreamName=stream["logStreamName"],
                limit=limit,
            )["events"]

            for ev in events:
                ts = time.strftime("%H:%M:%S", time.localtime(ev["timestamp"] / 1000))
                msg = ev["message"].strip()
                if "ERROR" in msg:
                    print(f"  \033[91m[{ts}] {msg}\033[0m")
                elif "hoan thanh" in msg.lower() or "success" in msg.lower():
                    print(f"  \033[92m[{ts}] {msg}\033[0m")
                else:
                    print(f"  [{ts}] {msg}")

    except Exception as e:
        print(f"  Loi doc log: {e}")
        print("  (Kiem tra LocalStack co dang chay khong?)")


# -------------------------------------------------------------------
# Benchmark: do hieu nang xu ly
# -------------------------------------------------------------------
def run_benchmark(num_images=5):
    """
    Do toc do xu ly anh.
    Tao anh gia, goi Lambda truc tiep, do thoi gian.
    """
    import io, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

    try:
        from PIL import Image
        import handler
        from unittest.mock import patch, MagicMock
    except ImportError as e:
        print(f"Chua cai du thu vien: {e}")
        return

    print(f"\n{'='*55}")
    print(f"  Benchmark: xu ly {num_images} anh")
    print(f"{'='*55}")

    _, lambda_client = get_clients()
    s3 = boto3.client("s3",
        endpoint_url=LOCALSTACK_URL,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    sizes = [(640, 480), (1280, 720), (1920, 1080), (2560, 1440), (800, 600)]
    durations = []

    for i in range(num_images):
        w, h = sizes[i % len(sizes)]
        img = Image.new("RGB", (w, h), color=(i * 40 % 255, 100, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        img_bytes = buf.getvalue()

        key = f"bench-{i+1}.jpg"

        # Upload anh gia vao S3
        try:
            s3.put_object(Bucket="images-input", Key=key, Body=img_bytes)
        except Exception:
            pass

        # Do thoi gian xu ly truc tiep qua ham
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda b=img_bytes: b)}
        mock_s3.put_object.return_value = {}

        start = time.time()
        with patch.object(handler, "OUTPUT_BUCKET", "images-output"):
            try:
                handler.process_image(mock_s3, "images-input", key)
                elapsed_ms = round((time.time() - start) * 1000, 1)
                durations.append(elapsed_ms)
                status = "\033[92mOK\033[0m"
            except Exception as e:
                elapsed_ms = -1
                status = f"\033[91mLOI: {e}\033[0m"

        size_mb = len(img_bytes) / 1024 / 1024
        print(f"  [{i+1}] {w}x{h}  |  {size_mb:.1f} MB  |  {elapsed_ms} ms  |  {status}")

    if durations:
        print(f"\n  {'─'*45}")
        print(f"  So anh xu ly thanh cong : {len(durations)}/{num_images}")
        print(f"  Thoi gian trung binh     : {statistics.mean(durations):.1f} ms")
        print(f"  Thoi gian nhanh nhat     : {min(durations):.1f} ms")
        print(f"  Thoi gian cham nhat      : {max(durations):.1f} ms")
        if len(durations) > 1:
            print(f"  Do lech chuan            : {statistics.stdev(durations):.1f} ms")

        print(f"\n  Chi phi uoc tinh (AWS that):")
        cost_per_1m = 0.20  # USD per 1M requests
        cost_per_gb_s = 0.0000166667  # USD per GB-second
        memory_gb = 256 / 1024
        avg_duration_s = statistics.mean(durations) / 1000
        monthly_requests = 10000
        total_cost = (monthly_requests / 1_000_000 * cost_per_1m) + \
                     (monthly_requests * memory_gb * avg_duration_s * cost_per_gb_s)
        print(f"  Voi {monthly_requests:,} request/thang: ${total_cost:.4f} USD")
        print(f"  (AWS Lambda Free Tier: 1,000,000 request mien phi/thang)")


# -------------------------------------------------------------------
# Kiem tra trang thai he thong
# -------------------------------------------------------------------
def check_system_status():
    """Kiem tra trang thai cac dich vu LocalStack."""
    import urllib.request

    print(f"\n{'='*55}")
    print("  Trang thai He thong")
    print(f"{'='*55}")

    try:
        with urllib.request.urlopen(f"{LOCALSTACK_URL}/_localstack/health", timeout=3) as r:
            data = json.loads(r.read())
        services = data.get("services", {})
        for svc in ["s3", "lambda", "apigateway", "iam", "logs"]:
            status = services.get(svc, "unknown")
            icon = "\033[92m[OK]\033[0m" if status == "running" else "\033[91m[--]\033[0m"
            print(f"  {icon}  {svc:<15} {status}")
    except Exception as e:
        print(f"  \033[91m[FAIL]\033[0m  Khong ket noi duoc LocalStack: {e}")
        print(f"  Chay lenh: localstack start -d")


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
if __name__ == "__main__":
    check_system_status()
    get_recent_logs()
    run_benchmark(num_images=5)
