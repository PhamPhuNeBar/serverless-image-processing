# Serverless Image Processing System

> Mon: **Dien Toan Dam May** | Kien truc: AWS Lambda + S3 + API Gateway | Moi truong: LocalStack

---

## Tong quan

He thong xu ly anh tu dong theo kien truc **serverless**:

```
Nguoi dung
    |
    | upload anh (.jpg / .png / .webp)
    v
API Gateway  ──────────────────────────────────────────────────────
    |                          hoac                               |
    |  HTTP POST /upload        S3 trigger (tu dong)              |
    v                               v                             |
AWS Lambda (image-processor)        |                             |
    |  - Tai anh tu S3              |                             |
    |  - Resize toi da 800x800      |                             |
    |  - Luu ket qua                |                             |
    v                               v                             |
S3 Output Bucket (images-output)                                  |
    |                                                             |
    | Presigned URL                                               |
    v                                                             |
Nguoi dung tai anh da xu ly <──────────────────────────────────────
```

---

## Yeu cau he thong

| Phan mem    | Phien ban   | Ghi chu                     |
|-------------|-------------|-----------------------------|
| Python      | 3.10+       | Chay code Lambda + scripts  |
| Docker      | 24+         | Chay LocalStack             |
| LocalStack  | 3.0+        | Gia lap AWS local           |

---

## Cai dat nhanh

### Buoc 1: Cai thu vien

```bash
pip install -r requirements.txt
```

### Buoc 2: Khoi dong LocalStack

```bash
localstack start -d

# Kiem tra
curl http://localhost:4566/_localstack/health
# Mong doi: {"services": {"s3": "running", "lambda": "running", ...}}
```

### Buoc 3: Deploy tu dong (1 lenh)

```bash
python scripts/deploy.py --test
```

Script se tu dong:
- Tao 2 S3 bucket (images-input, images-output)
- Deploy Lambda function
- Gan S3 trigger
- Chay kiem tra end-to-end

---

## Su dung thu cong (tung buoc)

### Tao S3 Buckets

```bash
awslocal s3 mb s3://images-input
awslocal s3 mb s3://images-output
awslocal s3 ls
```

### Dong goi va deploy Lambda

```bash
# Dong goi code
zip function.zip src/handler.py

# Tao IAM role
awslocal iam create-role \
  --role-name lambda-role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

# Deploy
awslocal lambda create-function \
  --function-name image-processor \
  --zip-file fileb://function.zip \
  --handler handler.lambda_handler \
  --runtime python3.11 \
  --role arn:aws:iam::000000000000:role/lambda-role \
  --timeout 30 \
  --memory-size 256
```

### Gan S3 Trigger

```bash
awslocal s3api put-bucket-notification-configuration \
  --bucket images-input \
  --notification-configuration file://s3-trigger.json
```

---

## Kiem thu

### Test don gian: upload anh va kiem tra output

```bash
# Upload anh thu
awslocal s3 cp tests/test-image.jpg s3://images-input/

# Kiem tra output
awslocal s3 ls s3://images-output/resized/

# Tai anh da xu ly ve
awslocal s3 cp s3://images-output/resized/test-image.jpg output.jpg
```

### Chay unit tests + integration tests

```bash
python -m pytest tests/test_handler.py -v
```

### Do hieu nang (benchmark)

```bash
python monitoring/cloudwatch.py
```

### Xem logs Lambda

```bash
awslocal logs tail /aws/lambda/image-processor
```

---

## Cau truc thu muc

```
serverless-image-processing/
|-- src/
|   `-- handler.py           # Lambda function chinh (xu ly anh)
|-- frontend/
|   `-- index.html           # Giao dien web upload anh
|-- tests/
|   |-- test_handler.py      # Unit tests + integration tests
|   `-- test-image.jpg       # Anh mau de test
|-- monitoring/
|   `-- cloudwatch.py        # Xem logs, do hieu nang
|-- scripts/
|   `-- deploy.py            # Script trien khai tu dong
|-- template.yaml            # SAM template (Infrastructure as Code)
|-- s3-trigger.json          # Cau hinh S3 notification
|-- requirements.txt         # Thu vien Python
`-- README.md                # File nay
```

---

## API Reference

### POST /upload

Upload anh de xu ly.

**Request:**
```
POST http://localhost:4566/restapis/{api-id}/local/_user_request_/upload
Content-Type: application/octet-stream
x-filename: photo.jpg

<binary image data>
```

**Response thanh cong (200):**
```json
{
  "message": "Xu ly anh thanh cong",
  "filename": "photo.jpg",
  "outputKey": "resized/photo.jpg",
  "outputUrl": "http://localhost:4566/images-output/resized/photo.jpg?...",
  "duration_ms": 245.3
}
```

**Response loi (400/500):**
```json
{
  "error": "Mo ta loi"
}
```

---

## Xu ly loi thuong gap

| Loi | Nguyen nhan | Cach sua |
|-----|-------------|----------|
| `Connection refused` | LocalStack chua chay | `localstack start -d` |
| `ModuleNotFoundError: PIL` | Chua cai Pillow | `pip install Pillow` |
| `NoSuchBucket` | Bucket chua duoc tao | `awslocal s3 mb s3://images-input` |
| `ResourceNotFoundException` | Lambda chua deploy | `python scripts/deploy.py` |
| `Lambda trigger khong hoat dong` | Chua gan notification | Chay lai buoc "Gan S3 Trigger" |

---

## Chi phi uoc tinh (neu deploy len AWS that)

| Dich vu       | Phi                         | Mien phi         |
|---------------|-----------------------------|------------------|
| AWS Lambda    | $0.20 / 1M request          | 1M request/thang |
| AWS Lambda    | $0.0000166667 / GB-giay     | 400,000 GB-s     |
| Amazon S3     | $0.023 / GB luu tru         | 5 GB / 12 thang  |
| API Gateway   | $3.50 / 1M request          | 1M request/thang |

**Uoc tinh:** voi 10,000 anh/thang -> tong chi phi **< $0.05 USD/thang**

---

## Nhom thuc hien

| STT | Ho ten | MSSV | Phan cong |
|-----|--------|------|-----------|
| 1   |        |      |           |
| 2   |        |      |           |
| 3   |        |      |           |
| 4   |        |      |           |
| 5   |        |      |           |

---

*Mon Dien Toan Dam May | Nam hoc 2024 - 2025*
