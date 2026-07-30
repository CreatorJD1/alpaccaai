const LOCAL_HOST_NAMES = new Set(["localhost", "0.0.0.0", "::1"]);

export const APPROVED_ALPECCA_RUNTIME_ASSET_BASE =
  "https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/6ad8d6db82b4e438ae0208eb4203a8e03837d500/runtime-assets";

function isPrivateIpv4(hostname: string) {
  const parts = hostname.split(".").map((part) => Number(part));
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false;
  return (
    parts[0] === 10 ||
    parts[0] === 127 ||
    (parts[0] === 169 && parts[1] === 254) ||
    (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
    (parts[0] === 192 && parts[1] === 168)
  );
}

/**
 * Local/LAN House servers carry the bundled art tree. Public continuity URLs
 * deliberately keep that heavyweight payload on Hugging Face instead.
 */
export function houseHostCarriesBundledArt(hostname: string) {
  const normalized = hostname.trim().toLowerCase().replace(/^\[|\]$/g, "");
  return LOCAL_HOST_NAMES.has(normalized) || normalized.endsWith(".localhost") || normalized.endsWith(".local") || isPrivateIpv4(normalized);
}

export function defaultAlpeccaArtBaseForHost(hostname: string, remoteBase: string) {
  return houseHostCarriesBundledArt(hostname) ? "" : remoteBase.replace(/\/$/, "");
}

/**
 * Query/local-storage overrides are accepted only when they identify the exact
 * reviewed Hugging Face revision. This keeps a shared House link from silently
 * replacing Alpecca's assets with an arbitrary tracking or impersonation host.
 */
export function normalizeApprovedAlpeccaArtBase(value: string) {
  if (!value.trim()) return "";
  try {
    const url = new URL(value.trim());
    url.search = "";
    url.hash = "";
    const normalized = url.toString().replace(/\/$/, "");
    return normalized === APPROVED_ALPECCA_RUNTIME_ASSET_BASE ? normalized : "";
  } catch {
    return "";
  }
}
