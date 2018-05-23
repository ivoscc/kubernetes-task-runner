# -*- coding: utf-8 -*-
from flask import request, Blueprint
from mongoengine.errors import FieldDoesNotExist, ValidationError

from kubernetes_task_runner.models import (BatchJob, BatchJobStatus)
from kubernetes_task_runner.serializers import BatchJobSchema
from kubernetes_task_runner.util import (response_helper, decode_zip_file)
from kubernetes_task_runner.batch_jobs import (cluster_create_batch_job,
                                               cluster_stop_batch_job)
from kubernetes_task_runner.exceptions import ClusterError


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

    try:
        job_parameters = body.get('job_parameters', None)
        input_zip = None
        if isinstance(job_parameters, dict):
            input_zip = job_parameters.pop('input_zip', None)
        batch_job = BatchJob(**body)
        if input_zip:
            batch_job.job_parameters.input_zip.put(decode_zip_file(input_zip))
        saved_batch_job = batch_job.save()
    except FieldDoesNotExist as err:
        return response_helper(False, code=400, error='InvalidParameters',
                               data=str(err))
    except ValidationError as err:
        return response_helper(False, code=400, error='InvalidParameters',
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
