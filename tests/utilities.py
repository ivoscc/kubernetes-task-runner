# -*- coding: utf-8 -*-
from datetime import datetime
from unittest.mock import Mock
from uuid import uuid4

from dotmap import DotMap


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
