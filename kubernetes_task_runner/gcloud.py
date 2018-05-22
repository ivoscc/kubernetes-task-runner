# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import GoogleAuthError
from google.cloud.storage import Client

from kubernetes_task_runner.exceptions import StorageException


URL_DURATION_SECONDS = 3600 * 24 * 30  # 30 days


class GCSClient:
    """ Google Cloud Storage interface. """

    def __init__(self, credentials_file_path, bucket_name):
        self._credentials_file_path = credentials_file_path
        self._bucket_name = bucket_name
        try:
            self._client = Client.from_service_account_json(
                self._credentials_file_path,
            )
            self._bucket = self._client.get_bucket(self._bucket_name)
        except (GoogleAuthError, GoogleAPICallError) as e:
            raise StorageException(f'Failed to initialize GCSClient: {e}')

    def upload_input_file(self, input_file, filename):
        blob = self._bucket.blob(filename)
        try:
            blob.upload_from_file(input_file)
        except GoogleAPICallError as e:
            raise StorageException(f'Failed to upload file {filename}: {e}')

    def get_output_file_url(self, blob_name):
        try:
            blob = self._bucket.get_blob(blob_name)
            if blob is None:
                raise OSError(
                    f'No file {blob_name} in bucket {self._bucket_name}'
                )
        except (GoogleAPICallError, OSError) as e:
            raise StorageException(f'Failed to retrieve file {blob_name}: {e}')
        # NOTE: GCS' signed URLs *require* an expiration time
        return blob.generate_signed_url(
            datetime.utcnow() + timedelta(seconds=URL_DURATION_SECONDS)
        )
