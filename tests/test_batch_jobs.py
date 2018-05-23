# -*- coding: utf-8 -*-
from datetime import datetime
from unittest.mock import Mock, patch

from kubernetes.client.rest import ApiException

from kubernetes_task_runner.batch_jobs import (cluster_create_batch_job,
                                               cluster_stop_batch_job)
from kubernetes_task_runner.exceptions import ClusterError
from kubernetes_task_runner.models import BatchJobStatus

from .base import BaseTestCase
from .utilities import create_cluster_manager_mock, mock_job, mock_pod_list

CLUSTER_PATCH_PATH = ('kubernetes_task_runner.batch_jobs.'
                      'get_cluster_manager_instance')
GCLOUD_PATCH_PATH = 'kubernetes_task_runner.batch_jobs.get_gcloud_client'


class BatchJobsTestCase(BaseTestCase):
    """
    Test cases for batch job creation/deletion functionality.
    """

    def _create(self, batch_job, cluster_manager):
        with patch(GCLOUD_PATCH_PATH):
            with patch(CLUSTER_PATCH_PATH, return_value=cluster_manager):
                with self.app.app_context():
                    with patch('time.sleep'):
                        return cluster_create_batch_job(batch_job)

    def _stop(self, batch_job, cluster_manager):
        with patch(CLUSTER_PATCH_PATH, return_value=cluster_manager):
            with self.app.app_context():
                return cluster_stop_batch_job(batch_job)

    def test_creation_happy_path(self):
        """
        If both job and pod get started, mark the batch_job as started and
        return last retrieved job version.
        """
        batch_job = self.create_batch_job()
        # overwrite microsecond because we lose precision when saving/loading
        # from mongo
        expected_start_time = datetime.utcnow().replace(microsecond=0)
        api_returned_job = mock_job(name=batch_job.name, active=1,
                                    start_time=expected_start_time)

        cluster_manager = create_cluster_manager_mock(
            create_job=mock_job(name=batch_job.name),
            get_job=api_returned_job,
            list_pods=mock_pod_list(['Running']),
        )

        response, _ = self._create(batch_job, cluster_manager)

        batch_job.reload()
        self.assertEqual(batch_job.status, BatchJobStatus.RUNNING.value)
        self.assertEqual(batch_job.start_time.isoformat(),
                         expected_start_time.isoformat())
        self.assertEqual(response, api_returned_job)

    def test_job_fails_to_start(self):
        """
        If job fails to start, set its status to failed in the DB and throw an
        exception.
        """
        batch_job = self.create_batch_job()
        cluster_manager = create_cluster_manager_mock(
            create_job=mock_job(name=batch_job.name),
            get_job=mock_job(name=batch_job.name, failed=1),
        )
        with self.assertRaises(ClusterError):
            self._create(batch_job, cluster_manager)

        batch_job.reload()
        self.assertEqual(batch_job.status, BatchJobStatus.FAILED.value)

    def test_job_starts_but_pod_fails(self):
        """
        If job starts but the associated pod fails to start, set the job status
        to failed and throw an exception.
        """
        batch_job = self.create_batch_job()
        cluster_manager = create_cluster_manager_mock(
            create_job=mock_job(name=batch_job.name),
            get_job=mock_job(name=batch_job.name, active=1),
            list_pods=mock_pod_list(['Failed']),
        )
        with self.assertRaises(ClusterError):
            self._create(batch_job, cluster_manager)

        batch_job.reload()
        self.assertEqual(batch_job.status, BatchJobStatus.FAILED.value)

    def test_stop_happy_path(self):
        """
        Should delete job from the cluster and set its status to killed in the
        DB.
        """
        batch_job = self.create_batch_job(status=BatchJobStatus.RUNNING.value)
        cluster_manager = create_cluster_manager_mock()

        self._stop(batch_job, cluster_manager)

        batch_job.reload()
        self.assertEqual(batch_job.status, BatchJobStatus.KILLED.value)
        cluster_manager.delete_job.assert_called_once_with(batch_job.name)

    def test_stop_fail(self):
        """
        When failing to delete a job on the cluster, throw the appropriate
        exception.
        """
        batch_job = self.create_batch_job(status=BatchJobStatus.RUNNING.value)
        cluster_manager = create_cluster_manager_mock()
        exception = ApiException('something went wrong')
        cluster_manager.delete_job = Mock(side_effect=exception)

        with self.assertRaises(ClusterError):
            self._stop(batch_job, cluster_manager)

        batch_job.reload()
        self.assertEqual(batch_job.status, BatchJobStatus.KILLED.value)
