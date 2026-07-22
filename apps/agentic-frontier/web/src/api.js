const ACTION_CONTRACT_VERSION = "agentic_frontier.action.v1";

export class FrontierApiError extends Error {
  constructor(message, status = 0, detail = null) {
    super(message);
    this.name = "FrontierApiError";
    this.status = status;
    this.detail = detail;
  }
}

export class FrontierApi {
  constructor() {
    this.sessionId = "";
    this.actorId = "Jason";
    this.revision = 0;
    this.perception = null;
    this.actionCounter = 0;
  }

  setSession(sessionId) {
    const clean = String(sessionId || "").trim();
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(clean)) {
      throw new FrontierApiError("Expedition ID must use 1-64 letters, numbers, dashes, or underscores.");
    }
    this.sessionId = clean;
  }

  async health() {
    return this.#request("/healthz", { auth: false });
  }

  async config() {
    return this.#request("/api/config", { auth: false });
  }

  async me() {
    return this.#request("/api/auth/me");
  }

  async register(username, displayName, password) {
    return this.#request("/api/auth/register", {
      method: "POST",
      body: { username, displayName, password },
      auth: false,
    });
  }

  async login(username, password) {
    return this.#request("/api/auth/login", {
      method: "POST",
      body: { username, password },
      auth: false,
    });
  }

  async logout() {
    const result = await this.#request("/api/auth/logout", { method: "POST" });
    this.sessionId = "";
    this.revision = 0;
    this.perception = null;
    return result;
  }

  async avatars() {
    return this.#request("/api/avatars");
  }

  async selectAvatar(avatarId) {
    return this.#request("/api/account/avatar", {
      method: "PUT",
      body: { avatarId },
    });
  }

  async uploadAvatar(file) {
    return this.#request("/api/account/avatar/custom", {
      method: "PUT",
      headers: { "content-type": "model/gltf-binary" },
      rawBody: file,
    });
  }

  async connect(sessionId) {
    this.setSession(sessionId);
    let created = false;
    try {
      await this.#request("/api/sessions", {
        method: "POST",
        body: { session_id: this.sessionId },
      });
      created = true;
    } catch (error) {
      if (!(error instanceof FrontierApiError) || error.status !== 409) {
        throw error;
      }
    }

    const snapshot = created
      ? await this.#request(`/api/sessions/${encodeURIComponent(this.sessionId)}/perception/${this.actorId}`)
      : await this.#request(`/api/sessions/${encodeURIComponent(this.sessionId)}/reconnect/${this.actorId}?after_revision=0`);
    const perception = snapshot.perception || snapshot;
    this.#acceptPerception(perception);
    return { created, perception, receipts: snapshot.receipts || [] };
  }

  async sync(afterRevision = this.revision) {
    this.#requireSession();
    const safeRevision = Math.max(0, Number.isInteger(afterRevision) ? afterRevision : 0);
    const snapshot = await this.#request(
      `/api/sessions/${encodeURIComponent(this.sessionId)}/reconnect/${this.actorId}?after_revision=${safeRevision}`,
    );
    this.#acceptPerception(snapshot.perception);
    return snapshot;
  }

  async act(action, parameters = {}) {
    return this.#submitAction(action, parameters);
  }

  async #submitAction(action, parameters = {}) {
    this.#requireSession();
    const actionId = this.#nextActionId(action);
    const response = await this.#request("/api/actions", {
      method: "POST",
      body: {
        contract_version: ACTION_CONTRACT_VERSION,
        session_id: this.sessionId,
        actor_id: this.actorId,
        action_id: actionId,
        expected_revision: this.revision,
        action,
        parameters,
      },
    });
    this.#acceptPerception(response.perception);
    return response;
  }

  #acceptPerception(perception) {
    if (!perception || typeof perception.revision !== "number") {
      throw new FrontierApiError("Game authority returned an invalid perception snapshot.");
    }
    this.perception = perception;
    this.revision = perception.revision;
  }

  #nextActionId(action) {
    this.actionCounter += 1;
    const entropy = globalThis.crypto?.randomUUID?.().replaceAll("-", "").slice(0, 12)
      || Math.random().toString(36).slice(2, 14);
    return `j_${String(action).slice(0, 8)}_${Date.now().toString(36)}_${this.actionCounter}_${entropy}`.slice(0, 64);
  }

  #requireSession() {
    if (!this.sessionId) {
      throw new FrontierApiError("Connect an expedition first.");
    }
  }

  async #request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body !== undefined) {
      headers.set("content-type", "application/json");
    }

    let response;
    try {
      response = await fetch(path, {
        method: options.method || "GET",
        headers,
        body: options.rawBody !== undefined
          ? options.rawBody
          : options.body === undefined ? undefined : JSON.stringify(options.body),
        cache: "no-store",
        credentials: "same-origin",
      });
    } catch (error) {
      throw new FrontierApiError("Game authority is unreachable.", 0, error);
    }

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json().catch(() => ({}))
      : { detail: await response.text().catch(() => "") };
    if (!response.ok) {
      throw new FrontierApiError(
        typeof payload.detail === "string" && payload.detail ? payload.detail : `Game authority rejected the request (${response.status}).`,
        response.status,
        payload,
      );
    }
    return payload;
  }
}
