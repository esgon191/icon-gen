import time

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from ..config import settings


class S3Storage:
    def __init__(self) -> None:
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )
        self.bucket = settings.s3_bucket
        self._ensure_bucket()

    def _ensure_bucket(self, retries: int = 15, delay: float = 1.0) -> None:
        for attempt in range(retries):
            try:
                self.client.head_bucket(Bucket=self.bucket)
                return
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchBucket", "NotFound"):
                    self.client.create_bucket(Bucket=self.bucket)
                    return
                if attempt == retries - 1:
                    raise
            except EndpointConnectionError:
                if attempt == retries - 1:
                    raise
            time.sleep(delay)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def get(self, key: str) -> bytes:
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)
