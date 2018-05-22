""" Utility methods to make our life easier """
import base64
import binascii
import logging

from flask import jsonify
from mongoengine.errors import ValidationError


DEFAULT_LOG_FORMAT = '%(asctime)s %(levelname)-8s %(message)s'


def response_helper(result, msg="", error="", data="", code=200):
    return jsonify(
        {
            "result": result,
            "msg": msg,
            "error": error,
            "data": data,
        }
    ), code


def logger_pick(log_level):
    """ Load the logger for the bot. """
    logging.basicConfig(level=log_level, format=DEFAULT_LOG_FORMAT)


def decode_zip_file(base64_encoded_input_zip):
    try:
        return base64.decodebytes(base64_encoded_input_zip.encode('ascii'))
    except (binascii.Error, TypeError) as e:
        raise ValidationError('', {
            'input_zip': 'must be a base64 encoded zip file.'
        })
