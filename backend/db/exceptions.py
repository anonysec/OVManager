"""Domain exceptions for the database/CRUD layer.

These are raised by CRUD operations and translated to HTTP responses by the
router layer. This keeps the CRUD layer independent of HTTP concepts.
"""


class NotFoundError(Exception):
    """Raised when a requested entity is not found in the database."""

    def __init__(self, entity: str, identifier: str = ""):
        self.entity = entity
        self.identifier = identifier
        super().__init__(f"{entity} not found" + (f": {identifier}" if identifier else ""))


class ConflictError(Exception):
    """Raised when an operation would violate a uniqueness constraint."""

    def __init__(self, entity: str, field: str = "", value: str = ""):
        self.entity = entity
        self.field = field
        self.value = value
        detail = f"{entity} already exists"
        if field and value:
            detail += f" ({field}={value})"
        super().__init__(detail)
