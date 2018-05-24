# -*- coding: utf-8 -*-
from flask import Blueprint, request
from kubernetes_task_runner.batch_jobs import (cluster_create_batch_job,
                                               cluster_stop_batch_job)
from kubernetes_task_runner.exceptions import ClusterError
from kubernetes_task_runner.models import BatchJob, BatchJobStatus
from kubernetes_task_runner.serializers import BatchJobSchema
from kubernetes_task_runner.util import decode_zip_file, response_helper
from mongoengine.errors import (FieldDoesNotExist, NotUniqueError,
                                ValidationError)

BatchJobSerializer = BatchJobSchema()


api_views = Blueprint('api_views', __name__)


@api_views.route('/batch/', methods=['GET'], defaults={'job_id': None})
@api_views.route('/batch/<job_id>', methods=['GET'])
def get_batch_job(job_id):
    """ Retrieve one or all running batch jobs. """
    filters = {
        'status': request.args.get('status', BatchJobStatus.RUNNING.value),
    }
    if not job_id:
        serialized = BatchJobSerializer.dump(
            BatchJob.objects.filter(**filters),
            many=True,
        )
        return response_helper(True, code=200, data=serialized.data)
    try:
        instance = BatchJob.objects.get(id=job_id)
    except (BatchJob.DoesNotExist, ValueError):
        return response_helper(False, code=404, error='DoesNotExist',
                               msg=f'Batch job {job_id} not found.')
    return response_helper(True, code=200,
                           data=BatchJobSerializer.dump(instance).data)


@api_views.route('/batch/', methods=['POST'])
def create_batch_job():
    """
    Create a new batch job and schedule an asynchronous task to start running
    it on the cluster.
    """
    body = request.json or {}
    body.pop('status', None)

    try:
        job_parameters = body.get('job_parameters', None)
        input_zip = None
        if isinstance(job_parameters, dict):
            input_zip = job_parameters.pop('input_zip', None)
        batch_job = BatchJob(**body)
        if input_zip:
            batch_job.job_parameters.input_zip.put(decode_zip_file(input_zip))
        saved_batch_job = batch_job.save()
    except (FieldDoesNotExist, ValueError) as err:
        return response_helper(False, code=400, error='InvalidParameters',
                               msg=str(err))
    except NotUniqueError:
        # mongoengine doesn't give us the field that raises the exception
        unique_fields = ''.join([field_name for field_name, field
                                 in BatchJob._fields.items() if field.unique])
        error_message = f'Fields must be unique: {unique_fields}.'
        return response_helper(False, code=400, error='InvalidParameters',
                               msg=error_message)
    except ValidationError as err:
        return response_helper(False, code=400, error='InvalidParameters',
                               msg='One or more fields had invalid values',
                               data=err.to_dict())

    try:
        _, message = cluster_create_batch_job(saved_batch_job)
    except ClusterError as e:
        return response_helper(False, code=500, error='ClusterError',
                               msg=str(e), data=e.context)

    return response_helper(True, code=200, msg=message,
                           data=BatchJobSerializer.dump(saved_batch_job).data)


@api_views.route('/batch/<job_id>', methods=['DELETE'])
def stop_batch_job(job_id):
    """ Terminate the batch_job that corresponds to the service_id """
    try:
        batch_job = BatchJob.objects.get(id=job_id)
    except (BatchJob.DoesNotExist, ValueError):
        return response_helper(False, code=404, error='DoesNotExist',
                               msg=f'Batch job {job_id} not found.')
    running_status_list = (BatchJobStatus.RUNNING.value,
                           BatchJobStatus.CLEANING.value)
    if batch_job.status not in running_status_list:
        message = (f'Can\'t stop batch job {job_id}. Status is: '
                   f'{batch_job.status}.')
        return response_helper(False, code=400, error='InvalidParameters',
                               msg=message)

    try:
        cluster_stop_batch_job(batch_job)
    except ClusterError as e:
        return response_helper(False, code=500, error='ClusterError',
                               msg=str(e), data=e.context)

    message = f'Instance {job_id} was successfully deleted from the cluster.'
    return response_helper(True, code=200, msg=message,
                           data=BatchJobSerializer.dump(batch_job).data)
