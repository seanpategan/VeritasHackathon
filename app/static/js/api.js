/* FieldWise — fetch helpers for the Flask JSON API. */
(function () {
  "use strict";

  class ApiError extends Error {
    constructor(code, message, status, details) {
      super(message);
      this.code = code;
      this.status = status;
      this.details = details;
    }
  }

  async function request(url, options) {
    let resp;
    try {
      resp = await fetch(url, options);
    } catch (err) {
      if (err && err.name === "AbortError") throw err;
      throw new ApiError("network_error", "Could not reach the FieldWise server. Check your connection.", 0);
    }
    let body = null;
    try {
      body = await resp.json();
    } catch (_) {
      /* non-JSON */
    }
    if (!resp.ok) {
      const e = (body && body.error) || {};
      throw new ApiError(e.code || "http_" + resp.status, e.message || "Request failed (" + resp.status + ").", resp.status, e.details);
    }
    return body;
  }

  window.FW = window.FW || {};
  window.FW.ApiError = ApiError;
  window.FW.api = {
    get(url, signal) {
      return request(url, { method: "GET", signal, headers: { Accept: "application/json" } });
    },
    post(url, data, signal) {
      return request(url, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(data),
      });
    },
  };
})();
