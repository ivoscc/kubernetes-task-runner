# -*- coding: utf-8 -*-
import logging
from enum import Enum
from datetime import datetime

from celery import Celery

from kubernetes_task_runner.models import BatchJob, BatchJobStatus
from kubernetes_task_runner.batch_jobs import (launch_cleaner_job,
                                               cleanup_job_dependencies)
from kubernetes_task_runner.extensions import (get_cluster_manager_instance,
                                               get_gcloud_client)


celery = Celery('__name__')


class Action(Enum):
    CLEAN = 1
    DELETE = 2
    SUCCEED = 3


def synchronize_cleanup_job(local_job, cleanup_job):
    """
    Synchronizes local job status if cleanup_job succeeded or failed.

    | local status | cleanup job status | action                          |
    |--------------+--------------------+---------------------------------|
    | cleaning     | Succeeded          | delete cleaner;status=succeeded |
    | cleaning     | Failed             | delete cleaner;status=failed    |
    """
    local_status = BatchJobStatus(local_job.status)
    status = None
    action = None
    if (local_status != BatchJobStatus.CLEANING
            or cleanup_job.status.active):
        return status, action
    if cleanup_job.status.failed:
        logging.info(f'Cleanup job failed. Considering job as failed.')
        status = BatchJobStatus.FAILED.value
        action = Action.DELETE
    elif cleanup_job.status.succeeded:
        logging.info(f'Cleanup job succeeded. Considering job a success.')
        status = BatchJobStatus.SUCCEEDED.value
        action = Action.SUCCEED
    return status, action


def apply_changes(local_job, new_status, action, cluster_manager,
                  cleanup_jobs=None, is_cleanup=False):
    """
    Apply changes to `local_job` based on the `action` we want to perform.
    """
    cleanup_jobs = cleanup_jobs or {}

    # apply status change if there's a new status
    if new_status is not None and new_status != local_job.status:
        local_job.update(set__status=new_status)

    if action == Action.CLEAN:
        has_clean_job = local_job.name in cleanup_jobs
        if not has_clean_job:
            launch_cleaner_job(local_job)

    elif action == Action.DELETE:
        if is_cleanup:
            cluster_manager.delete_job(local_job.cleanup_job_name)
        else:
            cluster_manager.delete_job(local_job.name)
            cleanup_job_dependencies(cluster_manager, local_job)

    elif action == Action.SUCCEED:
        cluster_manager.delete_job(local_job.cleanup_job_name)
        gcs_client = get_gcloud_client()
        output_file_url = gcs_client.get_output_file_url(
            f'{local_job.name}-output.zip',
        )
        local_job.update(output_file_url=output_file_url,
                         stop_time=datetime.utcnow())


def synchronize_job(local_job, cluster_job):
    """
    Compares local_job and cluster_job statuses and attempts to synchronize
    them.

    | local status | cluster status | action                         |
    |--------------+----------------+--------------------------------|
    | running      | Succeeded      | launch cleaner;status=cleaning |
    | running      | Failed         | delete;status=failed           |
    | failed       | *              | delete                         |
    | cleaning     | *              | launch cleaner                 |
    | succeeded    | Succeeded      | delete                         |
    | killed       | *              | delete                         |
    """
    local_status = BatchJobStatus(local_job.status)
    cluster_status = cluster_job.status

    new_status = None
    action = None
    if any([local_status == BatchJobStatus.CLEANING,
            (local_status == BatchJobStatus.RUNNING
                and cluster_status.succeeded)]):
        new_status = BatchJobStatus.CLEANING.value
        action = Action.CLEAN

    elif (local_status == BatchJobStatus.SUCCEEDED
          and cluster_status.succeeded):
        logging.info(f'Both local and cluster jobs succeeded.')
        action = Action.DELETE

    elif local_status == BatchJobStatus.RUNNING and cluster_status.failed:
        logging.info(f'Cluster job failed and local is running.')
        new_status = BatchJobStatus.FAILED.value
        action = Action.DELETE

    elif local_status == BatchJobStatus.FAILED:
        logging.info(f'Local marked as "failed". Deleting cluster\'s job.')
        new_status = BatchJobStatus.FAILED.value
        action = Action.DELETE

    elif local_status == BatchJobStatus.KILLED:
        logging.info(f'Local job\'s status is `killed`. Deleting cluster job')
        action = Action.DELETE

    return new_status, action


@celery.task
def synchronize_batch_jobs():
    """Synchronize Jobs running on the cluster with local state.

    Polls cluster for running jobs and compares their statuses with the
    corresponding local statuses.

    - Sets appropriate local job state based on cluster status.
    - Issues delete commands for finished jobs.
    - Launches cleanup jobs when a regular jobs succeedes.
    """
    logging.info('Starting periodic task `synchronize_batch_jobs`.')

    cluster_manager = get_cluster_manager_instance()
    cluster_jobs = cluster_manager.list_jobs()
    cleanup_job_suffix = BatchJob.cleanup_job_suffix

    logging.info(f'Got {len(cluster_jobs.items)} jobs on the cluster. '
                 'Starting syncrhonization...')

    # Build mapping of regular and cleanup jobs for processing:
    jobs = {}
    cleanup_jobs = {}
    for cluster_job in cluster_jobs.items:
        name = cluster_job.metadata.name
        is_cleanup = False
        if name.endswith(cleanup_job_suffix):
            is_cleanup = True
            name = name[:-len(cleanup_job_suffix)]
        try:
            local_job = BatchJob.objects.get(name=name)
        except BatchJob.DoesNotExist:
            logging.warn(f'Found an unmanaged job \'{name}\'in '
                         'the cluster. Ignoring...')
            continue
        if is_cleanup:
            cleanup_jobs[name] = (local_job, cluster_job)
        else:
            jobs[name] = (local_job, cluster_job)

    # synchronize cleanup jobs
    for job_name, (local_job, cluster_job) in cleanup_jobs.items():
        try:
            new_status, action = synchronize_cleanup_job(local_job,
                                                         cluster_job)
            apply_changes(local_job, new_status, action, cluster_manager,
                          is_cleanup=True)
        except Exception as e:
            logging.error('Failed to synchronize cluster with job '
                          f'{local_job.name} ({local_job.id}):\n{e}')
    logging.info(f'Synchronized {len(cleanup_jobs)} cleanup jobs')

    # synchronize regular jobs
    for job_name, (local_job, cluster_job) in jobs.items():
        try:
            local_job.reload()
            new_status, action = synchronize_job(local_job, cluster_job)
            apply_changes(local_job, new_status, action, cluster_manager,
                          cleanup_jobs=cleanup_jobs)
        except Exception as e:
            logging.error('Failed to synchronize cluster with job '
                          f'{local_job.name} ({local_job.id}):\n{e}')
    logging.info(f'Synchronized {len(jobs)} jobs')
