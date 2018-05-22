import re
import uuid
from datetime import datetime, timezone
from enum import Enum

from flask_mongoengine import MongoEngine
from slugify import slugify

from kubernetes_task_runner.fields import ExtendedStringField


db = MongoEngine()


def list_enum_values(enum):
    return [item.value for item in enum]


class BatchJobStatus(Enum):
    CREATED = 'created'
    RUNNING = 'running'
    FAILED = 'failed'
    KILLED = 'killed'
    CLEANING = 'cleaning'
    SUCCEEDED = 'succeeded'


class BaseModel(db.Document):
    id = db.UUIDField(primary_key=True, default=uuid.uuid4)
    created = db.DateTimeField(default=datetime.utcnow)
    meta = {'abstract': True}


class BatchJobParameters(db.EmbeddedDocument):
    """
    """
    docker_image = db.StringField(required=True)
    environment_variables = db.DictField(default={})
    input_zip = db.FileField(required=False)
    """
    {
     'limits':   {'cpu': '500m', 'memory': '128Mi'},
     'requests': {'cpu': '500m', 'memory': '128Mi'}
    }
    """
    resources = db.DictField(default={})


class BatchJob(BaseModel):
    """
    """
    cleanup_job_suffix = '-cleanup'

    name = ExtendedStringField(
        unique=True,
        required=False,
        # name is used for the cluster's Job name and must have a certain
        # format to be accepted by Kubernetes:
        #
        # > label must consist of lower case alphanumeric characters or '-',
        # > and must start and end with an alphanumeric character (e.g.
        # > 'my-name', or '123-abc', regex used for validation is
        # > '[a-z0-9]([-a-z0-9]*[a-z0-9])?'
        #
        # validate at creation time to avoid issues down the line
        _regex=re.compile('^[a-z0-9]([-a-z0-9]*[a-z0-9])?$')
    )
    status = db.StringField(default=BatchJobStatus.CREATED.value,
                            choices=list_enum_values(BatchJobStatus))
    job_parameters = db.EmbeddedDocumentField(BatchJobParameters,
                                              required=True)
    start_time = db.DateTimeField(required=False, null=True)
    stop_time = db.DateTimeField(required=False, null=True)
    output_file_url = db.StringField(required=False, null=True)

    meta = {'collection': 'batch_jobs'}

    @property
    def has_input_file(self):
        return self.job_parameters.input_zip.grid_id is not None

    @property
    def input_file(self):
        return self.job_parameters.input_zip

    @property
    def cleanup_job_name(self):
        return f'{self.name}{self.cleanup_job_suffix}'

    @property
    def input_pvc_claim_name(self):
        return f'job-{self.name}-input'

    @property
    def output_pvc_claim_name(self):
        return f'job-{self.name}-output'

    def clean(self):
        """ Set a job name based on the job_parameters. """
        if self.name is not None:
            return
        if (self.job_parameters is None or
                self.job_parameters.docker_image is None):
            # if there's not job_parameters, let it fail
            return
        if not isinstance(self.created, datetime):
            return
        timestamp = int(
            self.created.replace(tzinfo=timezone.utc).timestamp() * 1000
        )
        docker_name_slug = slugify(self.job_parameters.docker_image)
        self.name = f'{docker_name_slug}-{timestamp}'

    def set_running(self):
        self.update(status=BatchJobStatus.RUNNING.value)
        self.reload()

    def set_failed(self):
        self.update(set__status=BatchJobStatus.FAILED.value)
        self.reload()

    def set_succeeded(self):
        self.update(set__status=BatchJobStatus.SUCCEEDED.value)
        self.reload()

    def set_killed(self):
        self.update(set__status=BatchJobStatus.KILLED.value)
        self.reload()

    def set_cleaning(self):
        self.update(set__status=BatchJobStatus.CLEANING.value)
        self.reload()
