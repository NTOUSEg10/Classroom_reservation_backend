import { createClient } from "npm:@supabase/supabase-js@2.117.3";
import {
  ApplicationServer,
  importVapidKeys,
  PushMessageError,
  Urgency,
} from "jsr:@negrel/webpush@0.5.0";
import {
  allowedEndpoint,
  secureEqual,
  serviceKeyFromEnvironment,
} from "./security.ts";

const serviceKey = serviceKeyFromEnvironment(
  Deno.env.get("SUPABASE_SECRET_KEYS"),
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY"),
);
const dispatchApiKey = Deno.env.get("DISPATCH_API_KEY") ?? serviceKey;
const secret = Deno.env.get("DISPATCH_SECRET") ?? "";
const db = createClient(Deno.env.get("SUPABASE_URL") ?? "", serviceKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});
let server: Promise<ApplicationServer> | undefined;

function getServer() {
  server ??= (async () =>
    ApplicationServer.new({
      contactInformation: Deno.env.get("VAPID_SUBJECT") ?? "",
      vapidKeys: await importVapidKeys(
        JSON.parse(Deno.env.get("VAPID_KEYS_JSON") ?? "{}"),
      ),
    }))();
  return server;
}

Deno.serve(async (request: Request) => {
  if (request.method !== "POST")
    return new Response("method not allowed", { status: 405 });
  if (
    !serviceKey ||
    !secret ||
    !(await secureEqual(request.headers.get("apikey") ?? "", dispatchApiKey)) ||
    !(await secureEqual(request.headers.get("X-Dispatch-Secret") ?? "", secret))
  ) {
    return new Response("forbidden", { status: 403 });
  }
  let id: string;
  try {
    const body = await request.json();
    id = body.notification_id;
    if (
      typeof id !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
        id,
      )
    ) {
      return new Response("invalid notification id", { status: 422 });
    }
  } catch {
    return new Response("invalid JSON", { status: 422 });
  }
  try {
    const { data: note, error } = await db
      .from("notifications")
      .select("id,user_id,title,body,delivered_at")
      .eq("id", id)
      .single();
    if (error || !note)
      return new Response("notification not found", { status: 404 });
    if (note.delivered_at) return Response.json({ ok: true, accepted: 0 });
    const { data: subscriptions, error: subscriptionError } = await db
      .from("push_subscriptions")
      .select("id,endpoint,p256dh,auth")
      .eq("user_id", note.user_id);
    if (subscriptionError) throw subscriptionError;
    if (!subscriptions?.length) return Response.json({ ok: true, accepted: 0 });
    const appServer = await getServer();
    const payload = JSON.stringify({
      id: note.id,
      title: note.title,
      body: note.body,
      url: "/notifications",
    });
    const outcomes = await Promise.all(
      subscriptions.map(async (subscription) => {
        if (!allowedEndpoint(subscription.endpoint))
          throw new Error("blocked provider");
        try {
          await appServer
            .subscribe({
              endpoint: subscription.endpoint,
              keys: { p256dh: subscription.p256dh, auth: subscription.auth },
            })
            .pushTextMessage(payload, { urgency: Urgency.High, ttl: 3600 });
          return 1;
        } catch (cause) {
          if (
            cause instanceof PushMessageError &&
            [404, 410].includes(cause.response.status)
          ) {
            const { error: deletionError } = await db
              .from("push_subscriptions")
              .delete()
              .eq("id", subscription.id);
            if (deletionError) throw deletionError;
            return 0;
          }
          throw cause;
        }
      }),
    );
    return Response.json({
      ok: true,
      accepted: outcomes.reduce((sum: number, item: number) => sum + item, 0),
    });
  } catch {
    // Do not log provider endpoints, contact data, payloads, or service credentials.
    console.error("dispatch-push failed; retry retained in PostgreSQL outbox");
    return Response.json({ ok: false }, { status: 503 });
  }
});
