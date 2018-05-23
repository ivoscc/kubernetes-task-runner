# -*- coding: utf-8 -*-
from unittest.mock import Mock, patch
from uuid import uuid4
import json

from kubernetes_task_runner.models import BatchJob, BatchJobStatus
from kubernetes_task_runner.serializers import BatchJobSchema

from .base import BaseTestCase


BatchJobSerializer = BatchJobSchema()


CREATE_BATCH_JOB_PATCH_PATH = ('kubernetes_task_runner.views.'
                               'cluster_create_batch_job')
STOP_BATCH_JOB_PATCH_PATH = ('kubernetes_task_runner.views.'
                             'cluster_stop_batch_job')


class APITestCase(BaseTestCase):
    """
    Test Case for API controllers.
    """
    def _json_response(self, *args, method='get', **kwargs):
        if 'content_type' not in kwargs:
            kwargs['content_type'] = 'application/json'
        response = getattr(self.client, method)(*args, **kwargs)
        response.json = json.loads(response.data)
        return response

    def test_get_single_batch_job_happy_path(self):
        """ Should return a properly formatted batch job. """
        batch_job = self.create_batch_job(
            status=BatchJobStatus.RUNNING.value,
        )
        url = f'{self.batch_jobs_url}{batch_job.id}'
        response = self._json_response(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['data'],
                         BatchJobSerializer.dump(batch_job).data)

    def test_get_single_batch_job_404(self):
        """ Should return a 404 when requesting a non existent batch job. """
        response = self._json_response(f'{self.batch_jobs_url}{uuid4().hex}')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json['error'], 'DoesNotExist')

    def test_get_batch_jobs_happy_path(self):
        """ Should return multiple properly formatted batch jobs. """
        batch_job_0 = self.create_batch_job(
            status=BatchJobStatus.RUNNING.value,
        )
        # create an unstarted batch_job that should not appear in results
        self.create_batch_job(status=BatchJobStatus.CREATED.value)
        batch_job_2 = self.create_batch_job(
            status=BatchJobStatus.RUNNING.value,
        )
        response = self._json_response(self.batch_jobs_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['data']), 2)
        self.assertEqual(response.json['data'][0],
                         BatchJobSerializer.dump(batch_job_0).data)
        self.assertEqual(response.json['data'][1],
                         BatchJobSerializer.dump(batch_job_2).data)

    def test_create_batch_job_happy_path(self):
        """
        Should allow the creation of new batch jobs and call the cluster to
        start them.
        """
        batch_job_data = self.create_batch_job(save=False)

        mock_cluster_create_job = Mock(return_value=(None, None))
        with patch(CREATE_BATCH_JOB_PATCH_PATH, mock_cluster_create_job):
            response = self._json_response(self.batch_jobs_url, method='post',
                                           data=json.dumps(batch_job_data))

        # a new batch job should be created
        self.assertEqual(BatchJob.objects.count(), 1)
        new_job = BatchJob.objects.all()[0]
        self.assertEqual(response.json['data'],
                         BatchJobSerializer.dump(new_job).data)

        self.assertEqual(response.status_code, 200)
        # the task processing function should've been called
        mock_cluster_create_job.assert_called_once_with(new_job)

    def test_create_batch_job_invalid_parameters(self):
        """
        Should return an error when attempting to create an instance with
        invalid parameters.
        """
        batch_job_data = self.create_batch_job(save=False)
        batch_job_data['status'] = 'not a real status'
        response = self._json_response(self.batch_jobs_url, method='post',
                                       data=json.dumps(batch_job_data))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['error'], 'InvalidParameters')

    def test_stop_batch_job(self):
        """ Should call the cluster for stopping a batch job."""
        batch_job = self.create_batch_job(status=BatchJobStatus.RUNNING.value)

        mock_cluster_stop_job = Mock()
        url = f'{self.batch_jobs_url}{batch_job.id}'
        with patch(STOP_BATCH_JOB_PATCH_PATH, mock_cluster_stop_job):
            response = self._json_response(url, method='delete')

        self.assertEqual(response.status_code, 200)

        # batch job wasn't actually completely deleted from the DB
        self.assertEqual(BatchJob.objects.count(), 1)
        updated_batch_job = BatchJob.objects.all()[0]
        # TODO: self.assertEqual(updated_batch_job.status,
        #                        BatchJobStatus.KILLED.value)
        self.assertEqual(response.json['data'],
                         BatchJobSerializer.dump(updated_batch_job).data)
        mock_cluster_stop_job.assert_called_once_with(batch_job)
