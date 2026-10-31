class ModelRegistryConflictError(ValueError):
    """Raised when an immutable model revision is already registered."""


class ModelApprovalRequiredError(ValueError):
    """Raised when execution references a model revision without approval."""
