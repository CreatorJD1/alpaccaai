// Forward inbound OpenClaw messages to Alpacca and surface her reply on the
// same conversation. We only react to message:received; everything else is a
// no-op so the hook can stay registered without spamming Alpacca's endpoint.

const ALPACCA_URL = process.env.ALPACCA_URL || "http://127.0.0.1:8765";
const TIMEOUT_MS = Number(process.env.ALPACCA_TIMEOUT_MS || "15000");

type AnyEvent = {
  type: string;
  action?: string;
  context?: Record<string, any>;
  messages?: string[];
};

const handler = async (event: AnyEvent): Promise<void> => {
  if (event.type !== "message" || event.action !== "received") return;

  const ctx = event.context ?? {};
  const text: string = (ctx.bodyForAgent || ctx.content || "").trim();
  if (!text) return;

  const channel: string = ctx.channelId || ctx.channel || "openclaw";
  const sender: string =
    ctx.metadata?.senderName || ctx.metadata?.senderId || ctx.from || "";

  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${ALPACCA_URL}/channel/inbound`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, channel, sender }),
      signal: ctl.signal,
    });
    if (!res.ok) return;
    const json: any = await res.json();
    const reply: string = (json?.reply || "").trim();
    // Push Alpacca's reply onto the event so OpenClaw delivers it back on the
    // same channel. message:received is a "replyable" surface per the hook
    // spec, so this is the supported delivery path.
    if (reply && Array.isArray(event.messages)) event.messages.push(reply);
  } catch {
    // Alpacca offline / timeout / malformed JSON: stay silent. OpenClaw will
    // fall back to whatever its default agent would have done.
  } finally {
    clearTimeout(timer);
  }
};

export default handler;
