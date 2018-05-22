# -*- coding: utf-8 -*-
import click

from kubernetes_task_runner.app import create_app
from kubernetes_task_runner.tasks import celery
from kubernetes_task_runner.util import logger_pick
from kubernetes_task_runner.extensions import app_config_reader


@click.command()
@app_config_reader
def run_worker(app_config):
    logger_pick(app_config['LOG_LEVEL'])
    app = create_app(app_config)

    celery.conf.beat_schedule = {
        'synchronize-jobs-with-cluster': {
            'task': 'kubernetes_task_runner.tasks.synchronize_batch_jobs',
            'schedule': app_config['JOB_SYNCHRONIZATION_INTERVAL'],
        },
    }

    with app.app_context():
        celery.worker_main(['', '-c', '1', '-P', 'solo', '-B', '--loglevel',
                            app_config['LOG_LEVEL']])


if __name__ == '__main__':
    run_worker()
