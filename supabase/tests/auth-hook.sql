-- Run after auth-hook.sql on the isolated test database; all assertions roll back.
BEGIN;
DO $$
DECLARE
  sample jsonb := '{"user":{"email":"student@email.ntou.edu.tw","is_anonymous":false,"app_metadata":{"provider":"google"}}}';
  invalid_email text;
  identity jsonb;
BEGIN
  ASSERT public.ntou_google_signup_gate(sample) = '{}'::jsonb, 'Valid Google signup must pass';
  ASSERT public.ntou_google_signup_gate(jsonb_set(sample,'{user,email}','"STUDENT@EMAIL.NTOU.EDU.TW"')) = '{}'::jsonb, 'Email casing is normalized';
  FOREACH invalid_email IN ARRAY ARRAY['student@gmail.com','student@mail.ntou.edu.tw','student@ntou.edu.tw',
    'student@email.ntou.edu.tw.evil.example','student@sub.email.ntou.edu.tw','@email.ntou.edu.tw',
    'two@@email.ntou.edu.tw',' student@email.ntou.edu.tw'] LOOP
    identity := jsonb_set(sample,'{user,email}',to_jsonb(invalid_email));
    ASSERT public.ntou_google_signup_gate(identity)->'error'->>'http_code' = '403', 'Domain bypass accepted';
  END LOOP;
  ASSERT public.ntou_google_signup_gate(jsonb_set(sample,'{user,app_metadata,provider}','"email"'))->'error'->>'http_code' = '403', 'Password signup accepted';
  ASSERT public.ntou_google_signup_gate(jsonb_set(sample,'{user,is_anonymous}','true'))->'error'->>'http_code' = '403', 'Anonymous signup accepted';
  ASSERT public.ntou_google_signup_gate('{"user":{"email":"student@email.ntou.edu.tw","user_metadata":{"provider":"google"}}}')->'error'->>'http_code' = '403', 'Mutable metadata accepted';
  ASSERT public.ntou_google_signup_gate('{}')->'error'->>'http_code' = '403', 'Missing metadata accepted';
  ASSERT NOT (SELECT prosecdef FROM pg_proc WHERE oid='public.ntou_google_signup_gate(jsonb)'::regprocedure), 'Hook must use invoker privileges';
  ASSERT NOT has_function_privilege('ntou_backend','public.ntou_google_signup_gate(jsonb)','EXECUTE'), 'Business role must not invoke hook';
  ASSERT NOT EXISTS (SELECT FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
    WHERE p.oid='public.ntou_google_signup_gate(jsonb)'::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE'), 'PUBLIC execution leaked';
  IF EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
    ASSERT NOT has_function_privilege('anon','public.ntou_google_signup_gate(jsonb)','EXECUTE'), 'Anonymous execution leaked';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
    ASSERT NOT has_function_privilege('authenticated','public.ntou_google_signup_gate(jsonb)','EXECUTE'), 'Authenticated execution leaked';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname='supabase_auth_admin') THEN
    ASSERT has_function_privilege('supabase_auth_admin','public.ntou_google_signup_gate(jsonb)','EXECUTE'), 'Auth role cannot invoke hook';
  END IF;
END $$;
ROLLBACK;
