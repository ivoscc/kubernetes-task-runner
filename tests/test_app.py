# -*- coding: utf-8 -*-
from datetime import datetime
from unittest.mock import Mock, patch
from uuid import uuid4
import json
import unittest

from dotmap import DotMap
from kubernetes.client.rest import ApiException

from kubernetes_task_runner.app import create_app
from kubernetes_task_runner.models import (db, BatchJob, BatchJobStatus)
from kubernetes_task_runner.serializers import BatchJobSchema
from kubernetes_task_runner.tasks import (Action, apply_changes,
                                          synchronize_job,
                                          synchronize_cleanup_job)
from kubernetes_task_runner.batch_jobs import (cluster_create_batch_job,
                                               cluster_stop_batch_job)
from kubernetes_task_runner.exceptions import ClusterError


BatchJobSerializer = BatchJobSchema()

APP_NAME = 'kubernetes_task_runner'

CREATE_BATCH_JOB_PATCH_PATH = f'{APP_NAME}.views.cluster_create_batch_job'
STOP_BATCH_JOB_PATH_PATH = f'{APP_NAME}.views.cluster_stop_batch_job'
GCLOUD_PATCH_PATH = f'{APP_NAME}.batch_jobs.get_gcloud_client'
GCLOUD_TASKS_PATCH_PATH = f'{APP_NAME}.tasks.get_gcloud_client'
CLUSTER_PATCH_PATH = f'{APP_NAME}.batch_jobs.get_cluster_manager_instance'
CLEANER_JOB_PATCH_PATH = f'{APP_NAME}.tasks.launch_cleaner_job'
CLEANUP_JOB_DEPENDENCIES_PATCH_PATH = f'{APP_NAME}.tasks.cleanup_job_dependencies'


TEST_CONFIG = {
    'MONGODB_SETTINGS': {
        'db': 'test',
        'host': 'mongomock://localhost'
    },
    'KUBERNETES_SETTINGS': {
        'api_key': '',
        'host': 'localhost',
        'namespace': 'default',
        'statefulset_name': 'test_sts',
    },
    'GOOGLE_CLOUD_SETTINGS': {
        'bucket_name': 'bucket_name',
        'credentials_file_path': '/tmp/',
    },
}


def create_cluster_manager_mock(**config):
    methods = {
        'set_number_of_replicas': None,
        'get_number_of_replicas': None,
        'restart_pod': None,
        'get_statefulset': DotMap({
            'status': {'ready_replicas': 0},
            'spec': {'replicas': 0}
        }),
        'get_pod': {},
        'list_jobs': DotMap({'items': []}),
        'delete_job': None,
        'create_job': None,
        'get_job': {},
        'list_pods': DotMap({'items': []}),
    }
    cluster_manager = Mock()
    for method_name, default_value in methods.items():
        setattr(cluster_manager, method_name,
                Mock(return_value=config.get(method_name, default_value)))
    return cluster_manager


class BaseTestCase(unittest.TestCase):

    def setUp(self):
        self.app = create_app(TEST_CONFIG)
        self.client = self.app.test_client()
        self.accounts_url = '/accounts/'
        self.batch_jobs_url = '/batch/'
        self.create_batch_job_patch_path = CREATE_BATCH_JOB_PATCH_PATH
        self.stop_batch_job_patch_path = STOP_BATCH_JOB_PATH_PATH
        self.gcloud_patch_path = GCLOUD_PATCH_PATH
        self.gcloud_tasks_patch_path = GCLOUD_TASKS_PATCH_PATH
        self.cluster_patch_path = CLUSTER_PATCH_PATH
        self.cleaner_job_patch_path = CLEANER_JOB_PATCH_PATH
        self.cleanup_job_dependencies_patch_path = CLEANUP_JOB_DEPENDENCIES_PATCH_PATH

    def tearDown(self):
        """ Drop database after each test so we can start fresh. """
        with self.app.app_context():
            db.connection.drop_database(TEST_CONFIG['MONGODB_SETTINGS']['db'])

    def create_batch_job(self, save=True, **kwargs):
        batch_job_data = {
            'status': kwargs.get('status', None),
            'job_parameters': kwargs.get('job_parameters', {
                'docker_image': str(uuid4()),
            })
        }
        if not save:
            return batch_job_data
        with self.app.app_context():
            return BatchJob(**batch_job_data).save()


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
        with patch(self.create_batch_job_patch_path, mock_cluster_create_job):
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
        with patch(self.stop_batch_job_patch_path, mock_cluster_stop_job):
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


def mock_job(name=None, active=None, failed=None, succeeded=None,
             start_time=None):
    """
    Helper function to create a Kubernetes API Job response mock.
    """
    job = DotMap({
        'metadata': {'name': name or str(uuid4())},
        'status': {
            'active': active,
            'failed': failed,
            'succeeded': succeeded,
        },
        'to_dict': {},
    })
    job.status.start_time = start_time if start_time else datetime.utcnow()
    job.to_dict = lambda: job
    return job


def mock_pod_list(phases=None):
    """ Helper function to create a Kubernetes API pod list response mock. """
    class PodList:
        pass
    pod_list = PodList()
    pod_list.items = [
        DotMap({'status': {'phase': phase}, 'to_dict': lambda: {}})
        for phase in phases
    ]
    setattr(pod_list, 'to_dict', lambda: {})
    return pod_list


class BatchJobsTestCase(BaseTestCase):
    """
    Test cases for batch job creation/deletion functionality.
    """

    def _create(self, batch_job, cluster_manager):
        with patch(self.gcloud_patch_path):
            with patch(self.cluster_patch_path,
                       return_value=cluster_manager):
                with self.app.app_context():
                    with patch('time.sleep'):
                        return cluster_create_batch_job(batch_job)

    def _stop(self, batch_job, cluster_manager):
        with patch(self.cluster_patch_path, return_value=cluster_manager):
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


class SynchronizeBatchJobsTestCase(BaseTestCase):
    """
    Test cases for synchronization tasks and it's utilities.
    """

    def test_apply_changes_change_status(self):
        """ `apply_changes` shouldn't set the new_status job status. """
        cluster_manager = create_cluster_manager_mock()
        batch_job = self.create_batch_job()

        action = None
        new_status = BatchJobStatus.FAILED.value

        apply_changes(batch_job, new_status, action, cluster_manager)

        batch_job.reload()
        # the new status was set
        self.assertEqual(batch_job.status, new_status)

    def test_apply_changes_launch_cleanup_job(self):
        """
        When applying the CLEAN action, `apply_changes` should launch a cleanup
        job.
        """
        cluster_manager = create_cluster_manager_mock()
        launch_cleaner_job = Mock()
        batch_job = self.create_batch_job()

        action = Action.CLEAN
        new_status = batch_job.status

        with patch(self.cleaner_job_patch_path, launch_cleaner_job):
            apply_changes(batch_job, new_status, action, cluster_manager)

        # the cleanup job was launched
        launch_cleaner_job.assert_called_once_with(batch_job)

    def test_apply_changes_launch_cleanup_job_skip_if_running(self):
        """
        When applying the CLEAN action, `apply_changes` should NOT launch a
        cleanup job if one is already running.
        """
        cluster_manager = create_cluster_manager_mock()
        launch_cleaner_job = Mock()
        batch_job = self.create_batch_job()

        action = Action.CLEAN
        new_status = batch_job.status
        # a cleanup job is already running
        # cleanup job is already running
        cleanup_jobs = {batch_job.name: None}

        with patch(self.cleaner_job_patch_path, launch_cleaner_job):
            apply_changes(batch_job, new_status, action, cluster_manager,
                          cleanup_jobs=cleanup_jobs)

        # a second cleanup job wasn't launched
        self.assertEqual(launch_cleaner_job.call_count, 0)

    def test_apply_changes_delete_regular(self):
        """
        When applying a DELETE action, the job and its dependencies should be
        deleted from the cluster.
        """
        cluster_manager = create_cluster_manager_mock()
        batch_job = self.create_batch_job()
        cleanup_job_dependencies = Mock()

        action = Action.DELETE
        new_status = batch_job.status
        # a cleanup job is already running
        # cleanup job is already running

        with patch(self.cleanup_job_dependencies_patch_path, cleanup_job_dependencies):
            apply_changes(batch_job, new_status, action, cluster_manager)

        # job was deleted
        cluster_manager.delete_job.assert_called_once_with(batch_job.name)
        # job's dependencies were deleted
        cleanup_job_dependencies.assert_called_once_with(cluster_manager,
                                                         batch_job)

    def test_apply_changes_delete_cleanup(self):
        """
        When applying a DELETE action to a cleanup job, only the job should be
        deleted from the cluster.
        """
        cluster_manager = create_cluster_manager_mock()
        batch_job = self.create_batch_job()
        cleanup_job_dependencies = Mock()

        action = Action.DELETE
        new_status = batch_job.status

        with patch(self.cleanup_job_dependencies_patch_path,
                   cleanup_job_dependencies):
            apply_changes(batch_job, new_status, action, cluster_manager,
                          is_cleanup=True)

        # cleanup job was deleted
        cluster_manager.delete_job.assert_called_once_with(
            batch_job.cleanup_job_name,
        )
        # job's dependencies were not deleted (cleanup jobs don't have deps)
        self.assertEqual(cleanup_job_dependencies.call_count, 0)

    def test_apply_changes_cleanup_succeed(self):
        """
        Whn applying a SUCCEED action, the cleanup job should be deleted and
        the local job updated with the output zip url.
        """
        cluster_manager = create_cluster_manager_mock()
        batch_job = self.create_batch_job()
        cleanup_job_dependencies = Mock()

        action = Action.SUCCEED
        new_status = batch_job.status
        expected_url = 'URL'

        # a cleanup job is already running
        gcs_client = Mock()
        gcs_client.get_output_file_url = Mock(return_value=expected_url)

        with patch(self.gcloud_tasks_patch_path, return_value=gcs_client):
            apply_changes(batch_job, new_status, action, cluster_manager,
                          is_cleanup=True)

        batch_job.reload()
        self.assertEqual(batch_job.output_file_url, expected_url)
        cluster_manager.delete_job.assert_called_once_with(
            batch_job.cleanup_job_name,
        )
        self.assertEqual(cleanup_job_dependencies.call_count, 0)
