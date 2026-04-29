#!/usr/bin/env python3
"""
Script trien khai tu dong - Serverless Image Processing
Mon: Dien Toan Dam May

Chay script nay de:
  1. Kiem tra LocalStack dang chay
  2. Tao S3 buckets
  3. Deploy Lambda function
  4. Gan S3 trigger
  5. Kiem tra end-to-end

Cach dung:
  python scripts/deploy.py            # Trien khai day du
  python scripts/deploy.py --test     # Trien khai + chay test
  python scripts/deploy.py --destroy  # Xoa toan bo tai nguyen
"""

import argparse
import io
import json
import os
import subprocess
import sys
import time
import zipfile

import boto3

LOCALSTACK_URL  = "http://127.0.0.1:4566"
REGION          = "us-east-1"
INPUT_BUCKET    = "images-input"
OUTPUT_BUCKET   = "images-output"
FUNCTION_NAME   = "image-processor"
ROLE_ARN        = "arn:aws:iam::000000000000:role/lambda-role"

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))



# Helpers

def _client(service):
    return boto3.client(service,
        endpoint_url=LOCALSTACK_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

def step(msg): print(f"\n\033[94m>> {msg}\033[0m")
def ok(msg):   print(f"   \033[92m[OK]\033[0m  {msg}")
def fail(msg): print(f"   \033[91m[FAIL]\033[0m {msg}"); sys.exit(1)
def info(msg): print(f"   \033[93m[.]\033[0m   {msg}")



# Kiem tra LocalStack

def check_localstack():
    step("Kiem tra LocalStack")
    import urllib.request
    for attempt in range(10):
        try:
            with urllib.request.urlopen(f"{LOCALSTACK_URL}/_localstack/health", timeout=3) as r:
                data = json.loads(r.read())
            s3_ok = data.get("services", {}).get("s3") == "running"
            lm_ok = data.get("services", {}).get("lambda") in ("running", "available")
            if s3_ok and lm_ok:
                ok("LocalStack dang chay (S3 + Lambda ready)")
                return
        except Exception:
            pass
        info(f"Dang cho LocalStack khoi dong... ({attempt+1}/10)")
        time.sleep(3)
    fail("LocalStack khong phan hoi. Chay: localstack start -d")



# Tao S3 Buckets

def create_buckets():
    step("Tao S3 Buckets")
    s3 = _client("s3")
    for bucket in [INPUT_BUCKET, OUTPUT_BUCKET]:
        try:
            s3.create_bucket(Bucket=bucket)
            ok(f"Tao bucket: s3://{bucket}")
        except s3.exceptions.BucketAlreadyExists:
            ok(f"Bucket da ton tai: s3://{bucket}")
        except Exception as e:
            fail(f"Loi tao bucket {bucket}: {e}")



# Tao IAM Role

def create_iam_role():
    step("Tao IAM Role cho Lambda")
    iam = _client("iam")
    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    })
    try:
        iam.create_role(RoleName="lambda-role", AssumeRolePolicyDocument=policy)
        ok("Tao IAM role: lambda-role")
    except iam.exceptions.EntityAlreadyExistsException:
        ok("IAM role da ton tai: lambda-role")



# Dong goi va deploy Lambda

def deploy_lambda():
    step("Deploy Lambda Function")

    src_dir = os.path.join(ROOT_DIR, "src")
    zip_path = os.path.join(ROOT_DIR, "function.zip")

    # Tao file zip
    info("Dang dong goi code...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in ["handler.py"]:
            fpath = os.path.join(src_dir, fname)
            if os.path.exists(fpath):
                zf.write(fpath, fname)
                info(f"  Da them: {fname}")

    with open(zip_path, "rb") as f:
        zip_bytes = f.read()

    lm = _client("lambda")

    # Xoa function cu neu co
    try:
        lm.delete_function(FunctionName=FUNCTION_NAME)
        info("Da xoa function cu")
        time.sleep(1)
    except lm.exceptions.ResourceNotFoundException:
        pass

    # Tao function moi
    try:
        lm.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.11",
            Role=ROLE_ARN,
            Handler="handler.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Timeout=30,
            MemorySize=256,
            Environment={
                "Variables": {
                    "OUTPUT_BUCKET": OUTPUT_BUCKET,
                    "INPUT_BUCKET": INPUT_BUCKET,
                    "LOCALSTACK_ENDPOINT": LOCALSTACK_URL,
                }
            },
            Description="Serverless Image Processing - Mon Dien Toan Dam May",
        )
        ok(f"Deploy thanh cong: {FUNCTION_NAME}")
    except Exception as e:
        fail(f"Loi deploy Lambda: {e}")



# Gan S3 trigger

def attach_s3_trigger():
    step("Gan S3 Trigger vao Lambda")
    s3 = _client("s3")
    lm = _client("lambda")

    # Lay ARN cua function
    try:
        fn_arn = lm.get_function(FunctionName=FUNCTION_NAME)["Configuration"]["FunctionArn"]
    except Exception as e:
        fail(f"Khong lay duoc ARN cua Lambda: {e}")
        return

    notification_config = {
        "LambdaFunctionConfigurations": [{
            "LambdaFunctionArn": fn_arn,
            "Events": ["s3:ObjectCreated:*"],
        }]
    }

    try:
        s3.put_bucket_notification_configuration(
            Bucket=INPUT_BUCKET,
            NotificationConfiguration=notification_config,
        )
        ok(f"Da gan S3 trigger: {INPUT_BUCKET} -> {FUNCTION_NAME}")
    except Exception as e:
        info(f"Canh bao khi gan trigger (co the bo qua): {e}")



# Test end-to-end

def run_e2e_test():
    step("Kiem tra End-to-End")
    from PIL import Image

    s3 = _client("s3")

    # Tao anh test
    img = Image.new("RGB", (1920, 1080), color=(70, 130, 180))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    img_bytes = buf.getvalue()

    test_key = "e2e-test.jpg"
    info(f"Upload anh test: {len(img_bytes)//1024} KB, 1920x1080px")

    # Upload vao input bucket
    s3.put_object(Bucket=INPUT_BUCKET, Key=test_key, Body=img_bytes)
    ok(f"Da upload: s3://{INPUT_BUCKET}/{test_key}")

    # Goi Lambda thu cong (vi trigger co the mat thoi gian)
    lm = _client("lambda")
    event = {
        "Records": [{
            "eventSource": "aws:s3",
            "s3": {
                "bucket": {"name": INPUT_BUCKET},
                "object": {"key": test_key},
            }
        }]
    }

    info("Goi Lambda function...")
    start = time.time()
    resp = lm.invoke(
        FunctionName=FUNCTION_NAME,
        Payload=json.dumps(event).encode(),
    )
    elapsed_ms = round((time.time() - start) * 1000)

    payload = json.loads(resp["Payload"].read())
    status = payload.get("statusCode", 500)

    if status == 200:
        ok(f"Lambda tra ve 200 OK trong {elapsed_ms}ms")
        body = json.loads(payload.get("body", "{}"))
        info(f"Output: {body.get('output', '?')}")

        # Kiem tra file co trong output bucket
        output_key = f"resized/{test_key}"
        try:
            output_obj = s3.get_object(Bucket=OUTPUT_BUCKET, Key=output_key)
            output_img = Image.open(io.BytesIO(output_obj["Body"].read()))
            ok(f"Anh output: {output_img.width}x{output_img.height}px (goc: 1920x1080)")
            ok("Test End-to-End: THANH CONG")
        except Exception as e:
            info(f"Khong tim thay anh output (co the dung S3 trigger): {e}")
    else:
        body = json.loads(payload.get("body", "{}"))
        fail(f"Lambda tra ve {status}: {body.get('error', '?')}")



# Xoa tai nguyen

def destroy():
    step("Xoa toan bo tai nguyen")
    s3 = _client("s3")
    lm = _client("lambda")

    for bucket in [INPUT_BUCKET, OUTPUT_BUCKET]:
        try:
            objects = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
            for obj in objects:
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
            s3.delete_bucket(Bucket=bucket)
            ok(f"Da xoa bucket: {bucket}")
        except Exception as e:
            info(f"Khong xoa duoc {bucket}: {e}")

    try:
        lm.delete_function(FunctionName=FUNCTION_NAME)
        ok(f"Da xoa Lambda: {FUNCTION_NAME}")
    except Exception as e:
        info(f"Khong xoa duoc Lambda: {e}")



# Main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy Serverless Image Processing")
    parser.add_argument("--test",    action="store_true", help="Chay e2e test sau khi deploy")
    parser.add_argument("--destroy", action="store_true", help="Xoa toan bo tai nguyen")
    args = parser.parse_args()

    print("\n" + "=" * 55)
    print("  Serverless Image Processing - Deploy Script")
    print("=" * 55)

    if args.destroy:
        check_localstack()
        destroy()
    else:
        check_localstack()
        create_buckets()
        create_iam_role()
        deploy_lambda()
        attach_s3_trigger()
        if args.test:
            run_e2e_test()

    print(f"\n{'='*55}")
    print("  Hoan thanh!")
    print(f"{'='*55}\n")
