import {
  allowedEndpoint,
  secureEqual,
  serviceKeyFromEnvironment,
} from "./security.ts";

Deno.test(
  "Edge Functions prefer the modern secret map and retain legacy compatibility",
  () => {
    if (
      serviceKeyFromEnvironment(
        '{"default":"sb_secret_private-fixture"}',
        "legacy-fixture",
      ) !== "sb_secret_private-fixture"
    )
      throw new Error("modern key not selected");
    if (
      serviceKeyFromEnvironment(undefined, "legacy-fixture") !==
      "legacy-fixture"
    )
      throw new Error("legacy key not selected");
    if (serviceKeyFromEnvironment(undefined, undefined) !== "")
      throw new Error("missing keys must stay unconfigured");
  },
);

Deno.test(
  "Malformed modern secret maps fail closed without echoing credentials",
  () => {
    for (const secretKeys of [
      "private-malformed-fixture",
      '{"wrong-name":"sb_secret_private-fixture"}',
      '{"default":"sb_publishable_private-fixture"}',
      "null",
      "[]",
    ]) {
      let rejected = false;
      try {
        serviceKeyFromEnvironment(secretKeys, "legacy-fixture");
      } catch (error) {
        rejected = true;
        if (String(error).includes("private-"))
          throw new Error("credential echoed in validation error");
      }
      if (!rejected) throw new Error("malformed modern key map accepted");
    }
  },
);

Deno.test(
  "push providers allow exact HTTPS endpoints and reject SSRF/credentials/lookalikes",
  () => {
    for (const endpoint of [
      "https://fcm.googleapis.com/fcm/send/abc",
      "https://updates.push.services.mozilla.com/wpush/v2/a",
      "https://wns2.notify.windows.com/w/?token=a",
      "https://web.push.apple.com/Q",
    ]) {
      if (!allowedEndpoint(endpoint))
        throw new Error("valid provider rejected");
    }
    for (const endpoint of [
      "http://fcm.googleapis.com/a",
      "https://127.0.0.1/a",
      "https://fcm.googleapis.com.evil.test/a",
      "https://evil.test/a",
      "https://fcm.googleapis.com:8443/a",
      "https://secret@fcm.googleapis.com/a",
    ]) {
      if (allowedEndpoint(endpoint))
        throw new Error("unsafe endpoint accepted");
    }
  },
);

Deno.test(
  "dispatch secret comparison accepts only identical values",
  async () => {
    if (!(await secureEqual("same-test-secret", "same-test-secret")))
      throw new Error("equal rejected");
    if (await secureEqual("same-test-secret", "different-test-secret"))
      throw new Error("unequal accepted");
  },
);
