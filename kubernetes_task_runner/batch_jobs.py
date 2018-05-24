# -*- coding: utf-8 -*-
import os
import json
import logging
from datetime import datetime
from enum import Enum
import time

from flask import current_app
from kubernetes.client.rest import ApiException
from jinja2 import Template
import yaml

from kubernetes_task_runner.exceptions import JobStartException, ClusterError
from kubernetes_task_runner.extensions import (get_cluster_manager_instance,
                                               get_gcloud_client)


class PodPhase(Enum):
    Pending = 'Pending'
    Running = 'Running'
    Succeeded = 'Succeeded'
    Failed = 'Failed'
    Unknown = 'Unknown'


class ClusterJobStatus(Enum):
    Failed = 'failed'
    Active = 'active'
    Succeeded = 'succeeded'


def build_config_from_template(template_name, context):
    """
    Create a configuration JSON for the Kubernetes object at `template_name`.

    TODO: make use of Jinja loaders.
    """
    current_directory = os.path.dirname(os.path.realpath(__file__))
    template_path = os.path.join(
        current_directory, f'templates/{template_name}',
    )
    template = Template(open(template_path, 'r').read())
    return yaml.load(template.render(**context))


def parse_cluster_exception(exception):
    try:
        return json.loads(exception.body)
    except (json.JSONDecodeError, TypeError):
        return exception.body


def poll_job_until_start(cluster_manager, job_name, n_retries=3,
                         retry_wait=10):
    """
    Poll the cluster until the job is ready.
    """
    countdown = n_retries
    while countdown:

        job = cluster_manager.get_job(job_name)

        # job has started
        if job.status.active:
            return ClusterJobStatus.Active, job

        # job has finished successfully
        if job.status.succeeded:
            return ClusterJobStatus.Succeeded, job

        # job has failed to start
        if job.status.failed:
            raise JobStartException('Job failed to start', context={
                'last_job_response': job,
            })

        time.sleep(retry_wait)
        countdown -= 1

    raise JobStartException(
        f'Job failed to start after {n_retries * retry_wait} seconds.',
        context={'last_job_response': job.to_dict()}
    )


def poll_pod_until_start(cluster_manager, job_name, n_retries=7,
                         retry_wait=10):
    """
    Poll the cluster until the pod related to `job_name` is ready.
    """
    started_phases = (PodPhase.Running.value, PodPhase.Succeeded.value)
    countdown = n_retries
    while countdown:
        pods = cluster_manager.list_pods(label_selector=f'job-name={job_name}')
        if len(pods.items) == 1:
            pod = pods.items[0]
            if pod.status.phase in started_phases:
                return PodPhase[pod.status.phase], pod

        if len(pods.items) > 1:
            raise JobStartException(f'Expected one pod for job {job_name}, '
                                    f'instead found {len(pods.items)}.',
                                    context={'last_pod_response': pods})

        time.sleep(retry_wait)
        countdown -= 1

    raise JobStartException(
        f'Pod failed to start after {n_retries * retry_wait} seconds.',
        context={'last_pod_response': pods.to_dict()}
    )


def setup_job_dependencies(batch_job, cluster_manager, gcloud_settings):
    """ Create batch job's dependencies in the cluster. """
    # create secret with gcloud credentials
    cluster_manager.create_secrets_file(
        name='gcs-api-key',
        filename='gcs-api-key.json',
        file_path=gcloud_settings['credentials_file_path'],
        # wont raise an exception if it already exists
        ignore_existing=True,
    )
    # create input PVC
    if batch_job.has_input_file:
        # TODO: create PVC with required size only
        cluster_manager.create_pvc(
            build_config_from_template('pvc.yaml.j2', {
                'name': batch_job.input_pvc_claim_name,
                'storage_size': '100Gi',
            })
        )
    # create output PVC
    cluster_manager.create_pvc(
        build_config_from_template('pvc.yaml.j2', {
            'name': batch_job.output_pvc_claim_name,
            'storage_size': '100Gi'
        })
    )


def cluster_create_batch_job(batch_job, backoff_limit=0):
    """
    - Create a new job with the configuration of `batch_job`.
    - Polls the cluster until the job and its underlying pod have started.
    - If successful returns the last job status.
    - Otherwise returns the reason for failure.
    """
    job_name = batch_job.name
    logging.info(f'Creating new job {job_name}')
    cluster_manager = get_cluster_manager_instance()
    context = {'cluster_response': None,
               'last_job_response': None,
               'last_pod_response': None}

    gcloud_settings = current_app.config['GOOGLE_CLOUD_SETTINGS']

    # Deploy dependencies (PVCs, input file) and Job
    try:
        # make sure the required secrets and PVCs exist on the cluster
        setup_job_dependencies(batch_job, cluster_manager, gcloud_settings)
        # upload input file
        if batch_job.has_input_file:
            gcs_client = get_gcloud_client()
            gcs_client.upload_input_file(batch_job.input_file,
                                         f'{batch_job.name}-input.zip')
        # actually launch job
        context['last_job_response'] = cluster_manager.create_job(
            build_config_from_template('job.yaml.j2', {
                'backoff_limit': backoff_limit,
                'bucket_name': gcloud_settings['bucket_name'],
                'job': batch_job,
            })
        )
    except ApiException as e:
        error_message = f'API request failed while creating job {job_name}'
        logging.error(f'{error_message}: {e.body}')
        batch_job.set_failed()
        raise ClusterError(error_message, context={
            'cluster_response': parse_cluster_exception(e),
        })

    # Poll Job until it's started and then poll Pod until it's started.
    # We need to do both because a Job may be active even if their underlying
    # Pods fail to start, e.g. when specifying an invalid Docker image.
    try:
        logging.debug(f'Waiting for job {job_name} to start.')
        job_status, job_response = poll_job_until_start(cluster_manager,
                                                        job_name)
        context['last_job_response'] = job_response.to_dict()
        if job_status == ClusterJobStatus.Succeeded:
            # job finished successfully earlier than we could look
            logging.info(f'Job {job_name} completed successfully')
            batch_job.update(start_time=job_response.status.start_time)
            batch_job.set_cleaning()
            return job_response, f'Job {batch_job.id} finished instantly'
        logging.debug(f'Waiting for job {job_name}\'s pod to start.')
        pod_status, pod_response = poll_pod_until_start(cluster_manager,
                                                        job_name)
        context['last_pod_response'] = pod_response.to_dict()
    except ApiException as e:
        batch_job.set_failed()
        logging.error(
            f'API request failed while waiting for job to start: {e.body}'
        )
        raise ClusterError(
            str(e),
            context={'cluster_response': parse_cluster_exception(e)},
        )
    except JobStartException as e:
        batch_job.set_failed()
        error_message = ('Got unexpected response while waiting for job '
                         f'to start: {e}')
        logging.error(error_message)
        raise ClusterError(error_message, context=e.context)

    if pod_status == PodPhase.Succeeded:
        batch_job.update(start_time=job_response.status.start_time)
        batch_job.set_cleaning()
        return job_response, f'Job {batch_job.id} finished instantly'

    batch_job.set_running()
    batch_job.update(set__start_time=job_response.status.start_time)
    logging.info(f'Job {job_name} started successfully')
    return (
        job_response,
        f'New batch_job {batch_job.id} successfully started on the cluster.',
    )


def cluster_stop_batch_job(batch_job):
    """ Prematurely stop a running Job. """
    cluster_manager = get_cluster_manager_instance()
    batch_job.set_killed()
    try:
        response = cluster_manager.delete_job(batch_job.name)
        cleanup_job_dependencies(cluster_manager, batch_job)
    except ApiException as e:
        error_message = ('API request failed when deleting job '
                         f'{batch_job.name}')
        logging.error(f'{error_message}: {e.body}')
        raise ClusterError(
            error_message,
            context={'cluster_response': parse_cluster_exception(e)},
        )
    batch_job.update(set__stop_time=datetime.utcnow())
    return response


def launch_cleaner_job(batch_job, backoff_limit=0):
    """ Deploy cleaning job for `batch_job`. """
    gcloud_settings = current_app.config['GOOGLE_CLOUD_SETTINGS']
    cluster_manager = get_cluster_manager_instance()
    cleanup_job_config = build_config_from_template('cleanup_job.yaml.j2', {
        'job': batch_job,
        'bucket_name': gcloud_settings['bucket_name'],
        'backoff_limit': backoff_limit,
    })
    cluster_manager.create_job(cleanup_job_config)


def cleanup_job_dependencies(cluster_manager, job):
    """ Delete """
    cluster_manager.delete_pvc(job.output_pvc_claim_name,
                               ignore_404=True)
    if job.has_input_file:
        cluster_manager.delete_pvc(job.input_pvc_claim_name,
                                   ignore_404=True)
