"""Failures shared by processing services and desktop task adapters."""


class TaskCancelledError(Exception):
    pass


class TranslationError(Exception):
    def __init__(self, message, *, fatal=False):
        super().__init__(message)
        self.fatal = bool(fatal)


class TypesettingError(Exception):
    pass
