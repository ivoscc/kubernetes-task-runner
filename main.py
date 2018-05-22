# -*- coding: utf-8 -*-
import click
from gevent import pywsgi

from kubernetes_task_runner.app import create_app
from kubernetes_task_runner.extensions import app_config_reader
from kubernetes_task_runner.util import logger_pick


@click.command()
@click.argument('API_HOST', envvar='API_HOST', default='0.0.0.0')
@click.argument('API_PORT', envvar='API_PORT', default=4898)
@app_config_reader
def run_server(api_host, api_port, app_config):
    logger_pick(app_config['LOG_LEVEL'])
    app = create_app(app_config)
    server = pywsgi.WSGIServer((api_host, api_port), app)
    server.serve_forever()


if __name__ == '__main__':
    run_server()
