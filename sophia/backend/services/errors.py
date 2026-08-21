"""Exception types the service layer raises; each route protocol translates them."""


class ServiceError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


class NotFound(ServiceError):
    def __init__(self, message="not found"):
        super().__init__(message, status=404)
