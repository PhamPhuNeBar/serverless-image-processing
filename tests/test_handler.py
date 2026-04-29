"""
Test Suite - Serverless Image Processing System
Mon: Dien Toan Dam May

Bao gom:
  - Unit tests: kiem tra tung ham rieng le
  - Integration tests: kiem tra toan bo luong voi LocalStack
"""

import boto3
import io
import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image

# Them duong dan src vao Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import handler



# Helper: tao anh gia de test

def create_test_image(width=1200, height=900, fmt="JPEG", color=(100, 149, 237)) -> bytes:
    """Tao anh test trong bo nho."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf.read()


def create_png_with_alpha(width=800, height=600) -> bytes:
    """Tao anh PNG co kenh alpha (RGBA)."""
    img = Image.new("RGBA", (width, height), color=(255, 100, 100, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()



# UNIT TESTS

class TestDetectFormat(unittest.TestCase):
    """Kiem tra ham detect_format."""

    def test_jpg_extension(self):
        self.assertEqual(handler.detect_format("photo.jpg"), "JPEG")

    def test_jpeg_extension(self):
        self.assertEqual(handler.detect_format("photo.jpeg"), "JPEG")

    def test_png_extension(self):
        self.assertEqual(handler.detect_format("image.PNG"), "PNG")

    def test_webp_extension(self):
        self.assertEqual(handler.detect_format("image.webp"), "WEBP")

    def test_unknown_defaults_to_jpeg(self):
        self.assertEqual(handler.detect_format("file.bmp"), "JPEG")

    def test_no_extension(self):
        self.assertEqual(handler.detect_format("noextension"), "JPEG")


class TestResponseHelper(unittest.TestCase):
    """Kiem tra ham _response."""

    def test_status_200(self):
        resp = handler._response(200, {"message": "ok"})
        self.assertEqual(resp["statusCode"], 200)

    def test_cors_headers_present(self):
        resp = handler._response(200, {})
        self.assertIn("Access-Control-Allow-Origin", resp["headers"])
        self.assertEqual(resp["headers"]["Access-Control-Allow-Origin"], "*")

    def test_body_is_json_string(self):
        resp = handler._response(200, {"key": "value"})
        body = json.loads(resp["body"])
        self.assertEqual(body["key"], "value")

    def test_status_500(self):
        resp = handler._response(500, {"error": "fail"})
        self.assertEqual(resp["statusCode"], 500)


class TestProcessImageLogic(unittest.TestCase):
    """Kiem tra logic resize anh (dung S3 mock)."""

    def _make_mock_s3(self, image_bytes):
        """Tao S3 mock tra ve anh gia."""
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: image_bytes)
        }
        mock_s3.put_object.return_value = {}
        return mock_s3

    def test_large_image_gets_resized(self):
        """Anh 1200x900 phai duoc resize ve <= 800x600."""
        img_bytes = create_test_image(1200, 900)
        mock_s3 = self._make_mock_s3(img_bytes)

        with patch.object(handler, "OUTPUT_BUCKET", "images-output"):
            handler.process_image(mock_s3, "images-input", "test.jpg")

        # Kiem tra put_object da duoc goi
        self.assertTrue(mock_s3.put_object.called)
        call_kwargs = mock_s3.put_object.call_args[1]

        # Kiem tra anh dau ra nho hon 800x800
        output_img = Image.open(io.BytesIO(call_kwargs["Body"].getvalue()))
        self.assertLessEqual(output_img.width, 800)
        self.assertLessEqual(output_img.height, 800)

    def test_small_image_not_enlarged(self):
        """Anh nho (400x300) khong duoc phong to."""
        img_bytes = create_test_image(400, 300)
        mock_s3 = self._make_mock_s3(img_bytes)

        with patch.object(handler, "OUTPUT_BUCKET", "images-output"):
            handler.process_image(mock_s3, "images-input", "small.jpg")

        call_kwargs = mock_s3.put_object.call_args[1]
        output_img = Image.open(io.BytesIO(call_kwargs["Body"].getvalue()))
        self.assertEqual(output_img.width, 400)
        self.assertEqual(output_img.height, 300)

    def test_aspect_ratio_preserved(self):
        """Ty le khung hinh phai duoc giu nguyen sau resize."""
        img_bytes = create_test_image(1600, 400)  # Anh rong, ngang
        mock_s3 = self._make_mock_s3(img_bytes)

        with patch.object(handler, "OUTPUT_BUCKET", "images-output"):
            handler.process_image(mock_s3, "images-input", "wide.jpg")

        call_kwargs = mock_s3.put_object.call_args[1]
        output_img = Image.open(io.BytesIO(call_kwargs["Body"].getvalue()))

        original_ratio = 1600 / 400
        output_ratio = output_img.width / output_img.height
        self.assertAlmostEqual(original_ratio, output_ratio, delta=0.05)

    def test_png_rgba_converted_to_rgb_for_jpeg(self):
        """PNG co alpha duoc xu ly dung cach (khong loi khi luu JPEG)."""
        # JPEG khong ho tro alpha, can chuyen RGB truoc
        img_bytes = create_png_with_alpha()
        mock_s3 = self._make_mock_s3(img_bytes)

        with patch.object(handler, "OUTPUT_BUCKET", "images-output"):
            # Dat output key la .jpg de trigger chuyen doi
            try:
                handler.process_image(mock_s3, "images-input", "photo.png")
            except Exception as e:
                self.fail(f"process_image nem loi bat ngo: {e}")

    def test_output_key_has_resized_prefix(self):
        """Output key phai bat dau bang 'resized/'."""
        img_bytes = create_test_image(500, 500)
        mock_s3 = self._make_mock_s3(img_bytes)

        with patch.object(handler, "OUTPUT_BUCKET", "images-output"):
            output_key = handler.process_image(mock_s3, "images-input", "myphoto.jpg")

        self.assertTrue(output_key.startswith("resized/"))

    def test_unsupported_format_raises(self):
        """Dinh dang khong ho tro phai nem ValueError."""
        # Tao anh BMP (khong hop le)
        img = Image.new("RGB", (100, 100))
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        buf.seek(0)

        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": MagicMock(read=buf.read)}

        with patch.object(handler, "OUTPUT_BUCKET", "images-output"):
            with self.assertRaises(ValueError):
                handler.process_image(mock_s3, "images-input", "file.bmp")


class TestLambdaHandlerRouting(unittest.TestCase):
    """Kiem tra routing cua lambda_handler."""

    def test_unknown_event_returns_400(self):
        """Event khong ro rang phai tra ve 400."""
        result = handler.lambda_handler({"unknown": "event"}, None)
        self.assertEqual(result["statusCode"], 400)

    def test_s3_event_routes_correctly(self):
        """S3 event duoc phan tich dung."""
        event = {
            "Records": [{
                "eventSource": "aws:s3",
                "s3": {
                    "bucket": {"name": "images-input"},
                    "object": {"key": "test.jpg"},
                }
            }]
        }
        with patch.object(handler, "handle_s3_event") as mock_fn:
            mock_fn.return_value = {"message": "ok"}
            result = handler.lambda_handler(event, None)

        mock_fn.assert_called_once_with(event)
        self.assertEqual(result["statusCode"], 200)



# INTEGRATION TESTS (can LocalStack dang chay)

LOCALSTACK_URL = "http://localhost:4566"

def localstack_is_running() -> bool:
    """Kiem tra LocalStack co dang chay khong."""
    try:
        import urllib.request
        urllib.request.urlopen(f"{LOCALSTACK_URL}/_localstack/health", timeout=2)
        return True
    except Exception:
        return False


@unittest.skipUnless(localstack_is_running(), "LocalStack khong chay - bo qua integration tests")
class TestIntegrationWithLocalStack(unittest.TestCase):
    """Kiem tra tich hop day du voi LocalStack."""

    INPUT_BUCKET  = "images-input-test"
    OUTPUT_BUCKET = "images-output-test"

    @classmethod
    def setUpClass(cls):
        """Tao bucket test truoc khi chay."""
        cls.s3 = boto3.client(
            "s3",
            endpoint_url=LOCALSTACK_URL,
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        for bucket in [cls.INPUT_BUCKET, cls.OUTPUT_BUCKET]:
            try:
                cls.s3.create_bucket(Bucket=bucket)
            except cls.s3.exceptions.BucketAlreadyExists:
                pass

    @classmethod
    def tearDownClass(cls):
        """Xoa het object sau khi test xong."""
        for bucket in [cls.INPUT_BUCKET, cls.OUTPUT_BUCKET]:
            try:
                objects = cls.s3.list_objects_v2(Bucket=bucket).get("Contents", [])
                for obj in objects:
                    cls.s3.delete_object(Bucket=bucket, Key=obj["Key"])
            except Exception:
                pass

    def test_full_pipeline_jpeg(self):
        """Kiem tra toan bo luong: upload JPEG → resize → output."""
        img_bytes = create_test_image(1920, 1080)
        key = "integration-test.jpg"

        # Upload vao input bucket
        self.s3.put_object(Bucket=self.INPUT_BUCKET, Key=key, Body=img_bytes)

        # Chay xu ly
        with patch.object(handler, "OUTPUT_BUCKET", self.OUTPUT_BUCKET):
            output_key = handler.process_image(self.s3, self.INPUT_BUCKET, key)

        # Kiem tra file output ton tai
        output_obj = self.s3.get_object(Bucket=self.OUTPUT_BUCKET, Key=output_key)
        output_bytes = output_obj["Body"].read()

        # Kiem tra kich thuoc da giam
        self.assertLess(len(output_bytes), len(img_bytes))

        # Kiem tra anh dung kich thuoc
        output_img = Image.open(io.BytesIO(output_bytes))
        self.assertLessEqual(output_img.width, 800)
        self.assertLessEqual(output_img.height, 800)
        print(f"\n[PASS] JPEG: {1920}x{1080} -> {output_img.width}x{output_img.height}")

    def test_full_pipeline_png(self):
        """Kiem tra toan bo luong: upload PNG → resize → output."""
        img_bytes = create_test_image(1024, 768, fmt="PNG")
        key = "integration-test.png"

        self.s3.put_object(Bucket=self.INPUT_BUCKET, Key=key, Body=img_bytes)

        with patch.object(handler, "OUTPUT_BUCKET", self.OUTPUT_BUCKET):
            output_key = handler.process_image(self.s3, self.INPUT_BUCKET, key)

        output_obj = self.s3.get_object(Bucket=self.OUTPUT_BUCKET, Key=output_key)
        output_img = Image.open(io.BytesIO(output_obj["Body"].read()))

        self.assertLessEqual(output_img.width, 800)
        self.assertLessEqual(output_img.height, 800)
        print(f"\n[PASS] PNG: 1024x768 -> {output_img.width}x{output_img.height}")

    def test_performance_benchmark(self):
        """Do toc do xu ly 5 anh lien tiep."""
        results = []
        for i in range(5):
            img_bytes = create_test_image(1920, 1080)
            key = f"bench-{i}.jpg"
            self.s3.put_object(Bucket=self.INPUT_BUCKET, Key=key, Body=img_bytes)

            start = time.time()
            with patch.object(handler, "OUTPUT_BUCKET", self.OUTPUT_BUCKET):
                handler.process_image(self.s3, self.INPUT_BUCKET, key)
            elapsed_ms = round((time.time() - start) * 1000, 1)
            results.append(elapsed_ms)

        avg_ms = round(sum(results) / len(results), 1)
        print(f"\n[BENCH] Thoi gian xu ly trung binh: {avg_ms}ms")
        print(f"[BENCH] Chi tiet: {results}")

        # Phai xu ly xong trong 5 giay
        self.assertLess(avg_ms, 5000)

    CORS_HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,x-filename,x-operation,x-quality,x-format,x-maxdim",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
    }

    def lambda_handler(event, context):
        # Xử lý preflight OPTIONS
        if event.get("httpMethod") == "OPTIONS":
            return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

        # ... xử lý ảnh ...

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(result)
        }

# Chay test

if __name__ == "__main__":
    print("=" * 60)
    print("Serverless Image Processing - Test Suite")
    print("=" * 60)
    if not localstack_is_running():
        print("[WARN] LocalStack khong chay - chi chay unit tests\n")
    else:
        print("[INFO] LocalStack dang chay - chay ca integration tests\n")
    unittest.main(verbosity=2)
