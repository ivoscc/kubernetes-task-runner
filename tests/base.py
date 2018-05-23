# -*- coding: utf-8 -*-
import unittest
from uuid import uuid4

from kubernetes_task_runner.app import create_app
from kubernetes_task_runner.models import BatchJob, db

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


class BaseTestCase(unittest.TestCase):

    def setUp(self):
        self.app = create_app(TEST_CONFIG)
        self.client = self.app.test_client()
        self.accounts_url = '/accounts/'
        self.batch_jobs_url = '/batch/'

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
