# -*- coding: utf-8 -*-
from mongoengine import fields


class ExtendedStringField(fields.StringField):
    """
    StringField which shows the regex pattern used to validate the string when
    there's an error.

    Uses `_regex` instead of `regex`.
    """

    def __init__(self, *args, _regex=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._regex = _regex

    def validate(self, value):
        super().validate(value)
        if self._regex is not None and self._regex.match(value) is None:
            self.error(f'String \'{value}\' did not match validation regex '
                       f'\'{self._regex.pattern}\'')


class KubernetesResourceField(fields.DictField):
    """
    DictField which validates the form of a Kubernetes resource:
      {
        'limits':   {'cpu': '500m', 'memory': '128Mi'},
        'requests': {'cpu': '500m', 'memory': '128Mi'}
      }

    Note: for now only the structure is validated, but the actual values are
    not.
    """

    def _validate_single_resource_object(self, value, name):
        single_resource = value[name]
        if not isinstance(single_resource, dict):
            self.error()
        extra_keys = set(single_resource.keys()) - {'cpu', 'memory'}
        if extra_keys:
            self.error(f'A {name} can only specify \'cpu\' or \'memory\'. '
                       f'Found: {extra_keys}')

    def validate(self, value):
        super().validate(value)

        # only `limits` or `requests` keys
        extra_keys = set(value.keys()) - {'limits', 'requests'}
        if extra_keys:
            self.error('Only \'requests\' and \'limits\' keys allowed. Found '
                       f'extra keys: {extra_keys}')
        if 'limits' in value:
            self._validate_single_resource_object(value, 'limits')
        if 'requests' in value:
            self._validate_single_resource_object(value, 'requests')
