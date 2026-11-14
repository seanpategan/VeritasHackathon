"""Consistent JSON error structure: {"error": {"code": str, "message": str, "details"?: any}}."""
from __future__ import annotations

from flask import jsonify


class APIError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details

    def to_response(self):
        body = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            body["error"]["details"] = self.details
        return jsonify(body), self.status


class UpstreamError(APIError):
    """An external service (USDA, Census, Turnstile, AI provider) failed or timed out."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(code, message, status)


def register_error_handlers(app):
    from flask_limiter.errors import RateLimitExceeded
    from pydantic import ValidationError
    from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

    @app.errorhandler(APIError)
    def _api_error(err: APIError):
        return err.to_response()

    @app.errorhandler(ValidationError)
    def _validation(err: ValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in err.errors()
        ]
        return APIError("invalid_request", "Request validation failed.", 422, details).to_response()

    @app.errorhandler(RateLimitExceeded)
    def _rate_limited(err):
        return APIError(
            "rate_limited",
            "Rate limit reached. Please wait a moment and try again.",
            429,
            {"limit": str(err.description)},
        ).to_response()

    @app.errorhandler(RequestEntityTooLarge)
    def _too_large(_err):
        return APIError("request_too_large", "Request body is too large.", 413).to_response()

    @app.errorhandler(HTTPException)
    def _http(err: HTTPException):
        from flask import request

        if request.path.startswith("/api/"):
            return APIError(err.name.lower().replace(" ", "_"), err.description or err.name, err.code or 500).to_response()
        return err

    @app.errorhandler(Exception)
    def _unhandled(err: Exception):
        app.logger.exception("Unhandled error: %s", type(err).__name__)
        return APIError("internal_error", "An unexpected server error occurred.", 500).to_response()
