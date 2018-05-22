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
