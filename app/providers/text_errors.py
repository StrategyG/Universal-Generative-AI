class TextGenerationProviderError(RuntimeError):
    """Sanitized provider failure with retry metadata.

    Never attach request headers, API keys, raw upstream bodies, or prompt contents
    to this exception because its message may be returned to an API caller.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_error",
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
