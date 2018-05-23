# -*- coding: utf-8 -*-
from mongoengine import Document
from mongoengine.errors import ValidationError

from kubernetes_task_runner.fields import KubernetesResourceField

from .base import BaseTestCase


class TestKubernetesResourceField(BaseTestCase):

    def setUp(self):
        super().setUp()

        class TestDoc(Document):
            resources = KubernetesResourceField(default={})

        self.TestDoc = TestDoc

    def test_happy_path(self):
        """ Saves the resource as a dict. """
        input_resources = {
            'limits': {'cpu': '500m', 'memory': '128Mi'},
            'requests': {'cpu': '500m', 'memory': '128Mi'},
        }
        document_instance = self.TestDoc(resources=input_resources).save()
        self.assertEqual(document_instance.resources, input_resources)

    def test_blank_case(self):
        """ Doesn't break default case. """
        input_resources = {}
        document_instance = self.TestDoc(resources=input_resources).save()
        self.assertEqual(document_instance.resources, input_resources)

    def test_incomplete(self):
        """ Allows incomplete resource. """
        input_resources = {
            'limits': {'cpu': '500m'},
        }
        document_instance = self.TestDoc(resources=input_resources).save()
        self.assertEqual(document_instance.resources, input_resources)

    def test_extra_field(self):
        """ Raises an exception when an extra field is specified. """
        input_resources = {
            'limits': {'cpu': '500m'},
            'some_extra_field': {},
        }
        with self.assertRaisesRegex(ValidationError, 'some_extra_field'):
            self.TestDoc(resources=input_resources).save()

    def test_extra_resource_field(self):
        """
        Raises an exception when an extra field is specified in a resource.
        """
        input_resources = {
            'limits': {'cpu': '500m', 'extra_resource': '1m'},
        }
        with self.assertRaisesRegex(ValidationError, 'extra_resource'):
            self.TestDoc(resources=input_resources).save()
