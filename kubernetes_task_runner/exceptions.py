# -*- coding: utf-8 -*-


class InvalidStateError(Exception):
    """
    Raised in case the internal ClusterState reaches an invalid state.
    """
    pass


class NotReadyError(Exception):
    """
    Raised if the processing pipeline is not ready.
    """
    pass


class ClusterError(Exception):
    """
    Generic cluster management error.
    """

    def __init__(self, message='', context=None):
        super().__init__(message)
        self.context = context or {}


class JobStartException(ClusterError):
    """
    Thrown when failing to start a new Job or it's inner Pod.
    """
    pass


class JobStopException(ClusterError):
    """
    Thrown when failing to stop/delete a job on the cluster.
    """
    pass


class StorageException(Exception):
    """
    Thrown when an GCSCloud operation fails.
    """
    pass
