const exactHosts = new Set([
  "fcm.googleapis.com",
  "updates.push.services.mozilla.com",
  "web.push.apple.com",
]);

export function serviceKeyFromEnvironment(
  secretKeys: string | undefined,
  legacyKey: string | undefined,
): string {
  if (!secretKeys) return legacyKey ?? "";
  try {
    const keys: unknown = JSON.parse(secretKeys);
    if (
      typeof keys === "object" &&
      keys !== null &&
      !Array.isArray(keys) &&
      "default" in keys &&
      typeof keys.default === "string" &&
      keys.default.startsWith("sb_secret_")
    ) {
      return keys.default;
    }
  } catch {
    // Never include the malformed key map in startup errors.
  }
  throw new Error("SUPABASE_SECRET_KEYS requires a default secret key");
}

export function allowedEndpoint(endpoint: string): boolean {
  try {
    const url = new URL(endpoint);
    return (
      url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      (!url.port || url.port === "443") &&
      !url.hash &&
      (exactHosts.has(url.hostname) ||
        url.hostname.endsWith(".push.apple.com") ||
        url.hostname.endsWith(".notify.windows.com"))
    );
  } catch {
    return false;
  }
}

export async function secureEqual(
  received: string,
  expected: string,
): Promise<boolean> {
  const encoder = new TextEncoder();
  const [left, right] = await Promise.all(
    [received, expected].map((value) =>
      crypto.subtle.digest("SHA-256", encoder.encode(value)),
    ),
  );
  const a = new Uint8Array(left),
    b = new Uint8Array(right);
  let difference = 0;
  for (let index = 0; index < a.length; index++)
    difference |= a[index] ^ b[index];
  return difference === 0;
}
