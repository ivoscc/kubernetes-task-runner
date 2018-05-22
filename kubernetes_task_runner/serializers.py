# -*- coding: utf-8 -*-
"""
Classes for simplifying serialization of Mongoengine model instances to
JSON-encodable Python primitives.
"""
from datetime import datetime, timezone

from marshmallow import fields
from marshmallow_mongoengine import ModelSchema

from kubernetes_task_runner.models import BatchJob


def serialize_datetime(field_name):
    """ Serialize datetime as timestamp in milliseconds. """

    def serializer(obj):
        timestamp = getattr(obj, field_name, None)
        if isinstance(timestamp, datetime):
            timestamp = timestamp.replace(tzinfo=timezone.utc).timestamp()
            return int(timestamp * 1000)

    return serializer


class BaseModelSchema(ModelSchema):
    created = fields.Function(serialize_datetime('created'))


class BatchJobSchema(BaseModelSchema):
    """ Serialize BatchJob model objects. """
    start_time = fields.Function(serialize_datetime('start_time'))
    stop_time = fields.Function(serialize_datetime('stop_time'))

    class Meta:
        model = BatchJob
