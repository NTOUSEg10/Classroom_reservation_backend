-- Apply after schema.sql, as the migration owner, then enable this Auth hook.
-- Existing roster records are kept; the runtime no longer has access to them.
BEGIN;
CREATE OR REPLACE FUNCTION public.ntou_google_signup_gate(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $$
BEGIN
  IF event->'user'->'app_metadata'->>'provider' = 'google'
     AND lower(event->'user'->>'email') ~ '^[^@[:space:]]+@email[.]ntou[.]edu[.]tw$'
     AND COALESCE((event->'user'->>'is_anonymous') = 'false', false)
  THEN
    RETURN '{}'::jsonb;
  END IF;
  RETURN jsonb_build_object('error', jsonb_build_object(
    'http_code', 403, 'message', '請使用學校 Google 帳號註冊'
  ));
END;
$$;

REVOKE ALL ON FUNCTION public.ntou_google_signup_gate(jsonb) FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','ntou_backend'] LOOP
    IF EXISTS (SELECT FROM pg_roles WHERE rolname=role_name) THEN
      EXECUTE format('REVOKE ALL ON FUNCTION public.ntou_google_signup_gate(jsonb) FROM %I', role_name);
    END IF;
  END LOOP;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname='supabase_auth_admin') THEN
    GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
    GRANT EXECUTE ON FUNCTION public.ntou_google_signup_gate(jsonb) TO supabase_auth_admin;
  END IF;
END $$;
REVOKE ALL ON public.institutional_roster FROM ntou_backend;
COMMIT;
