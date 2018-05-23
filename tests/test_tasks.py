# -*- coding: utf-8 -*-
from unittest.mock import Mock, patch

from kubernetes_task_runner.models import BatchJobStatus
from kubernetes_task_runner.tasks import Action, apply_changes

from .base import BaseTestCase
from .utilities import create_cluster_manager_mock


GCLOUD_PATCH_PATH = 'kubernetes_task_runner.tasks.get_gcloud_client'
CLEANER_JOB_PATCH_PATH = 'kubernetes_task_runner.tasks.launch_cleaner_job'
CLEANUP_DEPENDENCIES_PATCH_PATH = ('kubernetes_task_runner.tasks.'
                                   'cleanup_job_dependencies')


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

        with patch(CLEANER_JOB_PATCH_PATH, launch_cleaner_job):
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

        with patch(CLEANER_JOB_PATCH_PATH, launch_cleaner_job):
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

        with patch(CLEANUP_DEPENDENCIES_PATCH_PATH, cleanup_job_dependencies):
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

        with patch(CLEANUP_DEPENDENCIES_PATCH_PATH, cleanup_job_dependencies):
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

        with patch(GCLOUD_PATCH_PATH, return_value=gcs_client):
            apply_changes(batch_job, new_status, action, cluster_manager,
                          is_cleanup=True)

        batch_job.reload()
        self.assertEqual(batch_job.output_file_url, expected_url)
        cluster_manager.delete_job.assert_called_once_with(
            batch_job.cleanup_job_name,
        )
        self.assertEqual(cleanup_job_dependencies.call_count, 0)
