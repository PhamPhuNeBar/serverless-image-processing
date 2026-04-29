"""
Serverless Image Processing System
Lambda Function - Image Handler
Mon: Dien Toan Dam May

Chuc nang:
- Nhan event tu S3 (khi co anh moi upload vao bucket input)
- Hoac nhan request tu API Gateway (upload qua HTTP)
- Resize anh ve toi da 800x800px, giu nguyen ty le
- Ho tro JPEG, PNG, WEBP, GIF
- Luu anh da xu ly vao bucket output
- Log ket qua len CloudWatch
"""

import boto3
import io
import os
import json
import logging
import time
from PIL import Image

# Cau hinh logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# -------------------------------------------------------------------
# Cau hinh ket noi: tu dong phat hien LocalStack hay AWS that
# -------------------------------------------------------------------
LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
IS_LOCAL = os.environ.get("AWS_EXECUTION_ENV") is None  # True khi chay local

def get_s3_client():
    """Tao S3 client - tu dong chon LocalStack hoac AWS that."""
    if IS_LOCAL:
        return boto3.client(
            "s3",
            endpoint_url=LOCALSTACK_ENDPOINT,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
    return boto3.client("s3")  # AWS that: dung IAM role tu dong


# Cau hinh xu ly anh
MAX_SIZE = (800, 800)           # Kich thuoc toi da sau resize
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "images-output")
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
OUTPUT_PREFIX = "resized/"


# -------------------------------------------------------------------
# Ham chinh: Lambda handler
# -------------------------------------------------------------------
def lambda_handler(event, context):
    """
    Entry point cua Lambda function.
    Ho tro 2 loai trigger:
      1. S3 Event   - khi co file moi upload vao bucket
      2. API Gateway - khi co HTTP POST /upload
    """
    logger.info("Event nhan duoc: %s", json.dumps(event))
    start_time = time.time()

        # --- OPTIONS preflight ---
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {"message": "ok"})

    try:
        # --- Xac dinh loai trigger ---
        if "Records" in event and event["Records"][0].get("eventSource") == "aws:s3":
            # Trigger tu S3
            result = handle_s3_event(event)
        elif "body" in event:
            # Trigger tu API Gateway
            result = handle_api_event(event)
        else:
            return _response(400, {"error": "Khong nhan biet loai event"})

        duration_ms = round((time.time() - start_time) * 1000, 2)
        logger.info("Xu ly hoan thanh trong %.2f ms", duration_ms)
        result["duration_ms"] = duration_ms
        return _response(200, result)

    except Exception as e:
        logger.error("Loi xu ly: %s", str(e), exc_info=True)
        return _response(500, {"error": str(e)})


# -------------------------------------------------------------------
# Xu ly S3 Event
# -------------------------------------------------------------------
def handle_s3_event(event):
    """Xu ly khi Lambda duoc trigger tu S3."""
    record = event["Records"][0]["s3"]
    source_bucket = record["bucket"]["name"]
    source_key = record["object"]["key"]

    logger.info("S3 trigger: s3://%s/%s", source_bucket, source_key)

    s3 = get_s3_client()
    output_key = process_image(s3, source_bucket, source_key)

    return {
        "message": "Xu ly anh thanh cong",
        "source": f"s3://{source_bucket}/{source_key}",
        "output": f"s3://{OUTPUT_BUCKET}/{output_key}",
    }


# -------------------------------------------------------------------
# Xu ly API Gateway Event
# -------------------------------------------------------------------
def handle_api_event(event):
    """Xu ly khi Lambda duoc goi tu API Gateway."""
    import base64

    body = event.get("body", "")
    is_base64 = event.get("isBase64Encoded", False)

    if is_base64:
        image_data = base64.b64decode(body)
    else:
        image_data = body.encode() if isinstance(body, str) else body

    # Lay ten file tu header hoac dat mac dinh
    headers = event.get("headers") or {}
    filename = headers.get("x-filename", "upload.jpg")

    s3 = get_s3_client()

    # Upload anh goc vao input bucket truoc
    input_bucket = os.environ.get("INPUT_BUCKET", "images-input")
    s3.put_object(Bucket=input_bucket, Key=filename, Body=image_data)
    logger.info("Da upload anh goc: s3://%s/%s", input_bucket, filename)

    # Xu ly anh
    output_key = process_image(s3, input_bucket, filename)

    # Tao presigned URL de download anh da xu ly
    output_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": OUTPUT_BUCKET, "Key": output_key},
        ExpiresIn=3600,
    )

    return {
        "message": "Xu ly anh thanh cong",
        "filename": filename,
        "outputKey": output_key,
        "outputUrl": output_url,
    }


# -------------------------------------------------------------------
# Ham xu ly anh chinh
# -------------------------------------------------------------------
def process_image(s3_client, source_bucket: str, source_key: str) -> str:
    """
    Tai anh tu S3, resize, va upload len bucket output.
    Tra ve output key.
    """
    # 1. Tai anh goc tu S3
    logger.info("Dang tai anh: s3://%s/%s", source_bucket, source_key)
    response = s3_client.get_object(Bucket=source_bucket, Key=source_key)
    image_data = response["Body"].read()
    original_size = len(image_data)
    logger.info("Kich thuoc anh goc: %d bytes", original_size)

    # 2. Mo va xu ly anh bang Pillow
    img = Image.open(io.BytesIO(image_data))
    original_dimensions = img.size
    img_format = img.format or detect_format(source_key)

    if img_format not in SUPPORTED_FORMATS:
        raise ValueError(f"Dinh dang '{img_format}' khong duoc ho tro. Chap nhan: {SUPPORTED_FORMATS}")

    # Chuyen sang RGB neu can (WEBP/PNG co the co kenh alpha)
    if img_format == "JPEG" and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # 3. Resize anh (giu ty le, khong phong to)
    img.thumbnail(MAX_SIZE, Image.LANCZOS)
    new_dimensions = img.size
    logger.info("Resize: %s -> %s", original_dimensions, new_dimensions)

    # 4. Luu vao buffer
    buffer = io.BytesIO()
    save_kwargs = {"format": img_format}
    if img_format == "JPEG":
        save_kwargs["quality"] = 85
        save_kwargs["optimize"] = True
    img.save(buffer, **save_kwargs)
    buffer.seek(0)
    compressed_size = buffer.getbuffer().nbytes
    logger.info("Kich thuoc sau xu ly: %d bytes (giam %.1f%%)",
                compressed_size, (1 - compressed_size / original_size) * 100)

    # 5. Upload len S3 output
    output_key = OUTPUT_PREFIX + source_key
    content_type_map = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "GIF": "image/gif",
    }
    s3_client.put_object(
        Bucket=OUTPUT_BUCKET,
        Key=output_key,
        Body=buffer,
        ContentType=content_type_map.get(img_format, "image/jpeg"),
        Metadata={
            "original-size": str(original_size),
            "original-dimensions": f"{original_dimensions[0]}x{original_dimensions[1]}",
            "new-dimensions": f"{new_dimensions[0]}x{new_dimensions[1]}",
        },
    )
    logger.info("Da luu anh xu ly: s3://%s/%s", OUTPUT_BUCKET, output_key)
    return output_key


def detect_format(filename: str) -> str:
    """Phat hien dinh dang anh tu extension file."""
    ext = filename.rsplit(".", 1)[-1].upper()
    return {"JPG": "JPEG", "JPEG": "JPEG", "PNG": "PNG",
            "WEBP": "WEBP", "GIF": "GIF"}.get(ext, "JPEG")


def _response(status_code: int, body: dict) -> dict:
    """Tao HTTP response chuan cho API Gateway."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, x-filename, x-operation, x-quality, x-format, x-maxdim",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
