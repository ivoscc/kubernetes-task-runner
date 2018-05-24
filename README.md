## Overview

The kubernetes task runner launches one-time
[jobs](https://kubernetes.io/docs/concepts/workloads/controllers/jobs-run-to-completion/)
on a Kubernetes cluster.

A task is a container that does some work and is not longer needed after
completion.

It can receive a zip file with input data. This will be unzipped on a volume
accessible to the container as `/input/`.

Additionally, anything written to the `/output/` directory will be zipped and
uploaded to a GCS bucket as part of the cleanup process.

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

Note that the `KUBERNETES_NAMESPACE` must exist as the application makes no
attempt to create it (only required if not using the `default` namespace).

## Setup

All configuration options can be specified either via CLI or as environment
variables. There a sample env file (`.env.sample`) with some of the defaults.
Copy this as `.env` and customize it to your needs.

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

## Process overview

### Batch Job Life cycle

1. A request is received to create a new batch Job.

2. A secret is created on the cluster if one doesn't already exist.

3. Both output (`job-<job-name>-output`) and input (`job-<job-name>-input`)
   PVCs are created on the cluster. Note the input will only be created if
   there's an input file.

4. If the job has an input file, it's uploaded to the GCS bucket
   (`<job_name>-input.zip`)

5. The job is deployed to the cluster. If the job has an input file, an init
   container is created to download `<job_name>-input.zip` and unzip it on the
   `/input/` directory before starting the job.

6. The `synchronize_batch_jobs` periodic task checks for job status changes.

7. Upon successful completion, a cleanup job is launched to zip and upload the
   contents of the `/output/` directory to the GCS bucket
   (`<job_name>-output.zip`)

8. Upon cleanup job completion or failure, the following resources are deleted:
    - Regular job
    - Cleanup job
    - Input PVC `job-<job-name>-input` (if it exists)
    - Output PVC `job-<job-name>-output`

## Possible job statuses

At any point a job may have one of the following statuses:

  - `created`: The job was just created and is currently being deployed.
  - `running`: The job has been deployed and is running on Kubernetes.
  - `failed`: The job couldn't be deployed or failed mid-execution.
  - `killed`: The job was killed by the user before finishing.
  - `cleaning`: The job has finished successfully and being cleaned up.
  - `succeeded`: Both the job and cleanup process have finished successfully.


## API Endpoints

### Get list of running Batch Jobs

List all running batch tasks as well as their status.

- Endpoint: `/batch/[?status=running]`
- Method: `GET`
- Parameters:
  - [status] Either 'created', 'running', 'failed', 'killed', 'cleaning',
    'succeeded' (default is 'running').
- Sample Response Body (HTTP 200)
  ```
  {
    "data": [
      {
        "created": 1527121792553,
        "id": "1e0e788e-58b0-4a06-a7a8-4c6307ed37cd",
        "job_parameters": {
          "docker_image": "python"
        },
        "name": "python-1527121792553",
        "output_file_url": "https://storage.googleapis.com/...",
        "start_time": 1527121793000,
        "status": "succeeded",
        "stop_time": 1527121886591
      },
      {
        "created": 1527122339156,
        "id": "54723389-05d1-40c8-add2-bd18f2395ebf",
        "job_parameters": {
          "docker_image": "alpine"
        },
        "name": "alpine-1527122339156",
        "output_file_url": "https://storage.googleapis.com/...",
        "start_time": 1527122340000,
        "status": "succeeded",
        "stop_time": 1527122405670
      }
    ],
    "error": "",
    "msg": "",
    "result": true
  }
  ```

### Get a specific running Batch Job

List a specific running batch job as well as their status.

- Endpoint: `/batch/[batch_job_id]`
- Method: `GET`
- Sample Response Body (HTTP 200)
  ```
  {
    "data": {
      "created": 1527121792553,
      "id": "1e0e788e-58b0-4a06-a7a8-4c6307ed37cd",
      "job_parameters": {
        "docker_image": "python"
      },
      "name": "python-1527121792553",
      "output_file_url": "https://storage.googleapis.com/...",
      "start_time": 1527121793000,
      "status": "succeeded",
      "stop_time": 1527121886591
    },
    "error": "",
    "msg": "",
    "result": true
  }
  ```

### Create a new Batch Job

Initializes a new batch job.

Note that if you want to send the input file you need to encode it as a Base64
string.

- Endpoint: `/batch/[batch_job_id]`
- Method: `POST`
- Parameters:
  - account_id: The ID of the account this job should use.
  - job_parameters: A collection of key/value parameters used by the Job.
    - docker_image: Name of the docker image to use.
    - [environment_variables]: A collection of key/value pairs with the desired
      environment variables to set on the container.
    - [resources]: CPU and memory requests and limits for the job's pod:
      ```
      {
        'limits':   {'cpu': '500m', 'memory': '128Mi'},
        'requests': {'cpu': '500m', 'memory': '128Mi'}
      }
      ```
  - [name]: Name of the job. Used as the Job name in the Kubernetes cluster. (If
    blank, will be derived from docker_image and creation timestamp). Should be unique.
- Sample Request Body:
  ```
  {
    "account_id": "5c7626fe-90fe-4248-8c4d-f1f2a6b61307",
    "status": "created",
    "job_parameters": {
      "some_key": "some_value",
      "another_key": { "another": "value" },
      "input_zip": 'aGVsbG8=\n',
    }
  }
  ```
- Sample Response Body (HTTP 200)
  ```
  {
    "data": {
      "created": 1527122339156,
      "id": "54723389-05d1-40c8-add2-bd18f2395ebf",
      "job_parameters": {
        "docker_image": "alpine"
      },
      "name": "alpine-1527122339156",
      "start_time": 1527122340000,
      "status": "cleaning"
    },
    "error": "",
    "msg": "Job 54723389-05d1-40c8-add2-bd18f2395ebf finished instantly",
    "result": true
  }
  ```
- Sample Error Response Body (HTTP 400):
  If there's an issue with the supplied parameters.
  ```
  {
    "data": {
      "job_parameters": {
        "docker_image": "Field is required"
      }
    },
    "error": "InvalidParameters",
    "msg": "",
    "result": false
  }
  ```
- Sample Error Response Body (HTTP 500)
  If there's an error while executing the command on the cluster:
  ```
  {
    "data": {
      "last_pod_response": { /* Full Kubernetes API response */}
    },
    "error": "ClusterError",
    "msg": "Got unexpected response while waiting for job to start",
    "result": false
  }
  ```

### Stop a running Batch Job

Stop a running Batch Job. If the Job doesn't have a status of either `running`
or `cleaning` and error will be returned.

- Endpoint: `/batch/[batch_job_id]`
- Method: `DELETE`
- Sample Response Body (HTTP 200)
  ```
  {
    "data": {
      "created": 1527122576106,
      "id": "bb34f086-5ff0-4ad3-a612-fcdf8048a917",
      "job_parameters": {
        "docker_image": "alpine"
      },
      "name": "alpine-1527122576106",
      "start_time": 1527122577000,
      "status": "killed"
    },
    "error": "",
    "msg": "Instance bb34f086-5ff0-4ad3-a612-fcdf8048a917 was successfully deleted from the cluster.",
    "result": true
  }
  ```
- Sample Error Response (HTTP 400)
  If the Job can't be killed be killed because it's already `stopped` or `failed`
  ```
  {
    "data": "",
    "error": "InvalidParameters",
    "msg": "Can't stop batch job 24da8ada-ab0a-4b8a-a82e-2603a88f0909. Status is: killed.",
    "result": false
  }
  ```
- Sample Error Response (HTTP 500):
  If there's an error while executing the command on the cluster:
  ```
  {
    "data": {
      "cluster_response": {
        "apiVersion": "v1",
        "code": 404,
        "details": {
          "group": "batch",
          "kind": "jobs",
          "name": "python-1526341086030"
        },
        "kind": "Status",
        "message": "jobs.batch \"python-1526341086030\" not found",
        "metadata": null,
        "reason": "NotFound",
        "status": "Failure"
      }
    },
    "error": "ClusterError",
    "msg": "API request failed when deleting job python-1526341086030",
    "result": false
  }
  ```
