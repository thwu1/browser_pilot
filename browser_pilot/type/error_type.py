from enum import Enum

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ErrorCategory(Enum):
    WORKER = "worker"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class ErrorCode(Enum):
    UNKNOWN_ERROR = "unknown_error"
    TASK_ERROR = "task_error"
    ENVIRONMENT_ALREADY_EXISTS = "environment_already_exists"
    ENVIRONMENT_NOT_FOUND = "environment_not_found"
    ENVIRONMENT_INIT_ERROR = "environment_init_error"


class ErrorInfo(BaseModel):
    category: ErrorCategory
    code: ErrorCode
    message: Optional[str] = Field(default=None)
    traceback: Optional[str] = Field(default=None)
    retry_suggestion: Optional[bool] = Field(default=None)

    def to_dict(self):
        return self.model_dump(mode="json")


class BrowserPilotError(Exception):
    """Base exception class for browser pilot errors with category support.

    This exception class integrates with the ErrorInfo model to provide
    structured error information including category, code, and optional details.
    """

    def __init__(
        self,
        category: ErrorCategory,
        code: ErrorCode,
        message: str,
        traceback: Optional[str] = None,
        retry_suggestion: Optional[bool] = None,
    ):
        self.error_info = ErrorInfo(
            category=category,
            code=code,
            message=message,
            traceback=traceback,
            retry_suggestion=retry_suggestion,
        )
        super().__init__(message)

    @property
    def category(self) -> ErrorCategory:
        return self.error_info.category

    @property
    def code(self) -> ErrorCode:
        return self.error_info.code

    @property
    def message(self) -> Optional[str]:
        return self.error_info.message

    @classmethod
    def from_error_info(cls, error_info: ErrorInfo) -> "BrowserPilotError":
        """Create a BrowserPilotError from an ErrorInfo object."""
        return cls(
            category=error_info.category,
            code=error_info.code,
            message=error_info.message or "",
            traceback=error_info.traceback,
            retry_suggestion=error_info.retry_suggestion,
        )

    def to_error_info(self) -> ErrorInfo:
        """Convert this exception to an ErrorInfo object."""
        return self.error_info


class WorkerError(BrowserPilotError):
    """Error raised for worker-side issues."""

    def __init__(
        self,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        message: str = "Worker error",
        traceback: Optional[str] = None,
        retry_suggestion: Optional[bool] = None,
    ):
        super().__init__(
            category=ErrorCategory.WORKER,
            code=code,
            message=message,
            traceback=traceback,
            retry_suggestion=retry_suggestion,
        )


class ExternalError(BrowserPilotError):
    """Error raised for external service issues."""

    def __init__(
        self,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        message: str = "External service error",
        traceback: Optional[str] = None,
        retry_suggestion: Optional[bool] = None,
    ):
        super().__init__(
            category=ErrorCategory.EXTERNAL,
            code=code,
            message=message,
            traceback=traceback,
            retry_suggestion=retry_suggestion,
        )


class UnknownError(BrowserPilotError):
    """Error raised for unknown issues."""

    def __init__(
        self,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        message: str = "Unknown error",
        traceback: Optional[str] = None,
        retry_suggestion: Optional[bool] = None,
    ):
        super().__init__(
            category=ErrorCategory.UNKNOWN,
            code=code,
            message=message,
            traceback=traceback,
            retry_suggestion=retry_suggestion,
        )


def create_error_from_info(error_info: ErrorInfo) -> BrowserPilotError:
    """Factory function to create the appropriate error type from ErrorInfo."""
    if error_info.category == ErrorCategory.WORKER:
        return WorkerError(
            code=error_info.code,
            message=error_info.message or "Worker error",
            traceback=error_info.traceback,
            retry_suggestion=error_info.retry_suggestion,
        )
    elif error_info.category == ErrorCategory.EXTERNAL:
        return ExternalError(
            code=error_info.code,
            message=error_info.message or "External error",
            traceback=error_info.traceback,
            retry_suggestion=error_info.retry_suggestion,
        )
    else:
        return UnknownError(
            code=error_info.code,
            message=error_info.message or "Unknown error",
            traceback=error_info.traceback,
            retry_suggestion=error_info.retry_suggestion,
        )


if __name__ == "__main__":
    from browser_pilot.utils import Serializer

    serializer = Serializer(serializer="msgpack")
    error_info = ErrorInfo(
        category=ErrorCategory.WORKER,
        code=ErrorCode.UNKNOWN_ERROR,
        message="Worker error",
        traceback="Traceback",
        retry_suggestion=True,
    )
    error_d = error_info.to_dict()
    a = serializer.dumps(error_d)
    b = serializer.loads(a)
    print(b)
