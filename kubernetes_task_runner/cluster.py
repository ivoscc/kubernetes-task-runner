# -*- coding: utf-8 -*-
import logging
import os

from kubernetes import client
from kubernetes.client.rest import ApiException
from kubernetes.client import Configuration, ApiClient


class ClusterManager:
    """
    Manage interface to Kubernetes cluster.
    """

    def __init__(self, host, api_key=None, namespace='default'):
        self._config = Configuration()
        self._config.host = host
        if api_key:
            self._config['Authorization'] = api_key
        self._api_client = ApiClient(self._config)

        self.apps_v1_beta2 = client.AppsV1beta2Api(api_client=self._api_client)
        self.core_v1 = client.CoreV1Api(api_client=self._api_client)
        self.batch_v1 = client.BatchV1Api(api_client=self._api_client)
        self.namespace = namespace

    def api_call(self, client, endpoint, ignore_404=False, **kwargs):
        kwargs.update({
            'namespace': kwargs.get('namespace', self.namespace),
            'async': False,
        })
        try:
            return getattr(client, endpoint)(**kwargs)
        except ApiException as e:
            if ignore_404 and e.status == 404:
                return
            logging.error(str(e))
            raise

    def restart_statefulset_pod(self, statefulset_name, pod_index):
        pod_name = f'{statefulset_name}-{pod_index}'
        logging.info(f'Restarting pod {pod_name}')
        return self.api_call(client=self.core_v1,
                             endpoint='delete_namespaced_pod',
                             name=pod_name, body={})

    def get_statefulset(self, statefulset_name):
        return self.api_call(client=self.apps_v1_beta2,
                             endpoint='read_namespaced_stateful_set',
                             name=statefulset_name)

    def get_pod_by_statefulset_index(self, statefulset_name, pod_index):
        pod_name = f'{statefulset_name}-{pod_index}'
        return self.api_call(client=self.core_v1,
                             endpoint='read_namespaced_pod',
                             name=pod_name)

    def create_pod(self, pod_configuration):
        return self.api_call(client=self.core_v1,
                             endpoint='create_namespaced_pod',
                             body=pod_configuration)

    def get_job(self, job_name):
        return self.api_call(client=self.batch_v1,
                             name=job_name,
                             endpoint='read_namespaced_job')

    def create_job(self, job_configuration):
        job_name = job_configuration['metadata']['name']
        logging.info(f'Creating job {job_name} on the cluster.')
        return self.api_call(client=self.batch_v1,
                             endpoint='create_namespaced_job',
                             body=job_configuration)

    def list_pods(self, label_selector=None):
        api_arguments = {
            'client': self.core_v1,
            'endpoint': 'list_namespaced_pod',
        }
        if label_selector is not None:
            api_arguments['label_selector'] = label_selector
        return self.api_call(**api_arguments)

    def list_jobs(self):
        return self.api_call(client=self.batch_v1,
                             endpoint='list_namespaced_job')

    def delete_job(self, job_name):
        delete_options = client.V1DeleteOptions(
            propagation_policy='Background',  # delete associated pods
            grace_period_seconds=0,  # delete right away
            api_version='batch/v1',
            kind='DeleteOptions',
        )
        logging.info(f'Deleting job {job_name} from the cluster.')
        return self.api_call(client=self.batch_v1,
                             endpoint='delete_namespaced_job',
                             name=job_name,
                             body=delete_options)

    def create_pvc(self, pvc_configuration):
        pvc_name = pvc_configuration['metadata']['name']
        logging.info(f'Creating PVC {pvc_name} on the cluster.')
        return self.api_call(
            client=self.core_v1,
            endpoint='create_namespaced_persistent_volume_claim',
            body=pvc_configuration,
        )

    def delete_pvc(self, pvc_name, ignore_404=False):
        delete_options = client.V1DeleteOptions(
            propagation_policy='Background',
            grace_period_seconds=0,  # delete right away
            api_version='v1',
            kind='DeleteOptions',
        )
        logging.info(f'Deleting PVC {pvc_name} on the cluster.')
        return self.api_call(
            client=self.core_v1,
            endpoint='delete_namespaced_persistent_volume_claim',
            body=delete_options,
            name=pvc_name,
            ignore_404=ignore_404
        )

    def create_secrets_file(self, name, file_path, ignore_existing=False,
                            filename=None):
        """
        Read `file_path` and create a secret with `name`.

        If `ignore_existing` is True will try to get a secret with the same
        `name` first and return if it already exists.

        If `filename` is not provided, will use the filename as extracted from
        `file_path`.
        """
        if ignore_existing:
            try:
                existing = self.read_secret(name)
                if existing:
                    return
            except ApiException as e:
                if e.status != 404:
                    raise

        logging.info(f'Creating secret {name} on the cluster.')
        filename = filename or os.path.basename(file_path)
        with open(file_path, 'r') as fh:
            data = fh.read()
        secret_body = client.V1Secret(
            metadata={'name': name},
            kind='Secret',
            string_data={filename: data}
        )
        return self.api_call(client=self.core_v1,
                             endpoint='create_namespaced_secret',
                             body=secret_body)

    def read_secret(self, name):
        return self.api_call(client=self.core_v1,
                             endpoint='read_namespaced_secret',
                             name=name)

    def delete_secret(self, name):
        logging.info(f'Deleting secret {name} from the cluster.')
        delete_options = client.V1DeleteOptions(
            grace_period_seconds=0,
            api_version='core/v1',
            kind='DeleteOptions',
        )
        return self.api_call(client=self.core_v1,
                             endpoint='delete_namespaced_secret',
                             name=name,
                             body=delete_options)
