## Overview

The kubernetes task runner launches one time jobs on a Kubernetes cluster.

## Configuration

```
API_HOST: The host that the API server will bind to (default 0.0.0.0)
API_PORT: The port the API server should listen to (default 4898)
MONGODB_HOST: The MongoDB host to connect to.
MONGODB_PORT: The MongoDB port to connect to.
MONGODB_DATABASE: The MongoDB database name to connect to.
CELERY_BROKER_URL: The connection URI celery should connect with.
KUBERNETES_API_URL: URL used to connect to the Kubernetes cluster.
KUBERNETES_API_KEY: API Key used to connect to the Kuberbetes cluster.
KUBERNETES_NAMESPACE: Kubernetes namespace to use for operations (default is 'default')
LOG_LEVEL: The applications loglevel (default is 'WARNING')
GC_BUCKET_NAME: The name of the GCS bucket to use for batch job's file I/O.
GC_CREDENTIALS_FILE_PATH: Path to GCS credentials JSON file.
JOB_SYNCHRONIZATION_INTERVAL: Time between executions of synchronization task (default 30 seconds)
```

## Setup

All configuration options can be specified either via CLI or as environment variables.
There a sample env file (`.env.sample`) with some of the defaults. Copy this as
`.env` and customize it to your needs.

## Usage

### With Docker compose:

0. Copy `.env.sample` to `.env` and customize it.

1. Run the following on the root directory
   ```
   docker-compose up
   ```

### Without Docker

0. Copy `.env.sample` to `.env` customize it and activate it:
   ```
   source .env
   ```
   (For now you need to add `export` at the beginning of each line for `source` to
   work.)

1. Create a virtualenv:
   ```
   virtualenv env
   ```

2. Activate it:
   ```
   source ./env/bin/activate
   ```

3. Install requirements:
   ```
   pip install -r requirements.txt
   ```

4. Run the API server:
   ```
   python main.py
   ```

5. On a different terminal, run the worker process:
   ```
   python worker.py
   ```
