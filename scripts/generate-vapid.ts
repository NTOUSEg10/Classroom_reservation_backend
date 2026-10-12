import {
  generateVapidKeys,
  exportVapidKeys,
  exportApplicationServerKey,
} from "jsr:@negrel/webpush@0.5.0";

const path = Deno.args[0];
if (!path)
  throw new Error(
    "Usage: deno run --allow-write scripts/generate-vapid.ts <private-output.json>",
  );
const keys = await generateVapidKeys({ extractable: true });
await Deno.writeTextFile(path, JSON.stringify(await exportVapidKeys(keys)));
console.log("VAPID_PUBLIC_KEY=" + (await exportApplicationServerKey(keys)));
console.log(
  "Private JWK written to the selected file. Set VAPID_KEYS_JSON only in Edge Function secrets.",
);
