class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused for a different request payload."""
