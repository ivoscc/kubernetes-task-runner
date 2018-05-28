# -*- coding: utf-8 -*-
import logging
from functools import wraps

import click
from flask import current_app

from kubernetes_task_runner.cluster import ClusterManager
from kubernetes_task_runner.gcloud import GCSClient


def get_cluster_manager_instance(**kubernetes_settings):
    if not kubernetes_settings:
        kubernetes_settings = current_app.config['KUBERNETES_SETTINGS']
    return ClusterManager(**kubernetes_settings)


def get_gcloud_client(**google_cloud_settings):
    if not google_cloud_settings:
        google_cloud_settings = current_app.config['GOOGLE_CLOUD_SETTINGS']
    return GCSClient(**google_cloud_settings)


def app_config_reader(func):
    """
    Parses common app config parameters, groups them and passes them as a
    `app_config` kwargs to the underlying function.
    """
    @wraps(func)
    @click.argument('MONGODB_HOST', envvar='MONGODB_HOST', default='localhost')
    @click.argument('MONGODB_PORT', envvar='MONGODB_PORT',
                    type=click.IntRange(min=1, max=65535),
                    default='27017')
    @click.argument('MONGODB_DATABASE', envvar='MONGODB_DATABASE',
                    default='kubernetes_task_runner')
    @click.argument('CELERY_BROKER_URL', envvar='CELERY_BROKER_URL')
    @click.argument('KUBERNETES_API_URL', envvar='KUBERNETES_API_URL')
    @click.argument('KUBERNETES_NAMESPACE', envvar='KUBERNETES_NAMESPACE',
                    default='default')
    @click.argument('LOG_LEVEL', envvar='LOG_LEVEL', default='WARNING',
                    type=click.Choice(logging._levelToName.values()))
    @click.argument('GC_BUCKET_NAME', envvar='GC_BUCKET_NAME')
    @click.argument('GC_CREDENTIALS_FILE_PATH',
                    envvar='GC_CREDENTIALS_FILE_PATH',
                    type=click.Path(exists=True, dir_okay=False))
    @click.argument('JOB_SYNCHRONIZATION_INTERVAL',
                    envvar='JOB_SYNCHRONIZATION_INTERVAL',
                    type=click.INT, default=30)
    @click.option('--kubernetes-api-key', envvar='KUBERNETES_API_KEY')
    def wrapper(*args, **kwargs):
        app_config = {
            'LOG_LEVEL': kwargs.pop('log_level'),
            'JOB_SYNCHRONIZATION_INTERVAL': kwargs.pop(
                'job_synchronization_interval',
            ),
            'CELERY_BROKER_URL': kwargs.pop('celery_broker_url'),
            'MONGODB_SETTINGS': {
                'db': kwargs.pop('mongodb_database'),
                'host': kwargs.pop('mongodb_host'),
                'port': kwargs.pop('mongodb_port')
            },
            'KUBERNETES_SETTINGS': {
                'api_key': kwargs.pop('kubernetes_api_key'),
                'host': kwargs.pop('kubernetes_api_url'),
                'namespace': kwargs.pop('kubernetes_namespace'),
            },
            'GOOGLE_CLOUD_SETTINGS': {
                'bucket_name': kwargs.pop('gc_bucket_name'),
                'credentials_file_path': kwargs.pop(
                    'gc_credentials_file_path'
                ),
            }
        }
        kwargs['app_config'] = app_config
        return func(*args, **kwargs)
    return wrapper
