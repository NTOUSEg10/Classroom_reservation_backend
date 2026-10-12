-- Direct SQL bootstrap. Execute as the migration owner; not an application login.
-- No CLI migration history is invented. Future migrations must be generated with the CLI.
BEGIN;
CREATE EXTENSION IF NOT EXISTS btree_gist;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ntou_backend') THEN
    CREATE ROLE ntou_backend NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;

CREATE TABLE public.profiles (
  id uuid PRIMARY KEY,
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  email text NOT NULL UNIQUE CHECK (email = lower(email)),
  phone text NOT NULL,
  department text NOT NULL,
  institutional_id text NOT NULL UNIQUE,
  role text NOT NULL DEFAULT 'borrower' CHECK (role IN ('borrower','admin')),
  verified boolean NOT NULL DEFAULT false,
  suspended boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
DO $$ BEGIN
  IF to_regclass('auth.users') IS NOT NULL THEN
    ALTER TABLE public.profiles ADD CONSTRAINT profiles_auth_user_fk
      FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;
  END IF;
END $$;

-- Legacy roster is retained for existing records; Google onboarding never reads it.
CREATE TABLE public.institutional_roster (
  institutional_id text PRIMARY KEY,
  email text NOT NULL UNIQUE CHECK (email = lower(email)),
  enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE public.rooms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  building text NOT NULL,
  floor integer NOT NULL,
  capacity integer NOT NULL CHECK (capacity > 0),
  equipment text[] NOT NULL DEFAULT '{}',
  latitude double precision CHECK (latitude BETWEEN -90 AND 90),
  longitude double precision CHECK (longitude BETWEEN -180 AND 180),
  map_x double precision CHECK (map_x BETWEEN 0 AND 100),
  map_y double precision CHECK (map_y BETWEEN 0 AND 100),
  map_path text,
  location_text text NOT NULL,
  location_verified boolean NOT NULL DEFAULT false,
  active boolean NOT NULL DEFAULT true
);
CREATE TABLE public.reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.profiles(id),
  room_id uuid NOT NULL REFERENCES public.rooms(id),
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  purpose text NOT NULL CHECK (length(purpose) BETWEEN 2 AND 500),
  attendees integer NOT NULL CHECK (attendees > 0),
  mode text NOT NULL CHECK (mode IN ('immediate','scheduled')),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','cancelled','checked_out','completed')),
  decision_reason text,
  reviewed_by uuid REFERENCES public.profiles(id),
  key_handed_at timestamptz,
  key_handed_by uuid REFERENCES public.profiles(id),
  key_returned_at timestamptz,
  key_returned_by uuid REFERENCES public.profiles(id),
  request_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at > starts_at),
  CHECK ((key_handed_at IS NULL) = (key_handed_by IS NULL)),
  CHECK ((key_returned_at IS NULL) = (key_returned_by IS NULL)),
  CHECK (key_returned_at IS NULL OR key_handed_at IS NOT NULL),
  UNIQUE(user_id, request_id),
  CONSTRAINT reservations_no_overlap EXCLUDE USING gist
    (room_id WITH =, tstzrange(starts_at,ends_at,'[)') WITH &&)
    WHERE (status IN ('approved','checked_out'))
);
CREATE INDEX reservations_owner_history ON public.reservations(user_id,created_at DESC);
CREATE INDEX reservations_room_time ON public.reservations(room_id,starts_at);
CREATE INDEX reservations_pending ON public.reservations(created_at) WHERE status='pending';
CREATE TABLE public.violations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.profiles(id),
  reservation_id uuid REFERENCES public.reservations(id),
  points integer NOT NULL CHECK (points BETWEEN 1 AND 3),
  reason text NOT NULL CHECK (length(reason) BETWEEN 2 AND 500),
  resolved boolean NOT NULL DEFAULT false,
  created_by uuid NOT NULL REFERENCES public.profiles(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX violations_active_owner ON public.violations(user_id) WHERE NOT resolved;
CREATE TABLE public.notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.profiles(id),
  reservation_id uuid REFERENCES public.reservations(id),
  title text NOT NULL,
  body text NOT NULL,
  read_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz,
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error text,
  claimed_at timestamptz
);
CREATE INDEX notifications_owner_history ON public.notifications(user_id,created_at DESC);
CREATE INDEX notifications_outbox ON public.notifications(next_attempt_at,created_at) WHERE delivered_at IS NULL;
CREATE TABLE public.push_subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.profiles(id),
  endpoint text NOT NULL UNIQUE,
  p256dh text NOT NULL,
  auth text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX push_subscriptions_owner ON public.push_subscriptions(user_id);
CREATE TABLE public.audit_logs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id uuid NOT NULL REFERENCES public.profiles(id),
  action text NOT NULL,
  reservation_id uuid REFERENCES public.reservations(id),
  target_user_id uuid REFERENCES public.profiles(id),
  old_status text,
  new_status text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.auth_rate_limits (
  key_hash text PRIMARY KEY,
  hits integer NOT NULL,
  expires_at timestamptz NOT NULL
);
CREATE INDEX auth_rate_limits_expiry ON public.auth_rate_limits(expires_at);

-- No client can create a profile, elevate a role, mutate a booking or read the roster.
DO $$ DECLARE tbl text; BEGIN
  FOREACH tbl IN ARRAY ARRAY['profiles','institutional_roster','rooms','reservations','violations','notifications','push_subscriptions','audit_logs','auth_rate_limits'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',tbl);
    EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',tbl);
    EXECUTE format('CREATE POLICY backend_access ON public.%I TO ntou_backend USING (true) WITH CHECK (true)',tbl);
    IF EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
      EXECUTE format('REVOKE ALL ON public.%I FROM anon',tbl);
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
      EXECUTE format('REVOKE ALL ON public.%I FROM authenticated',tbl);
    END IF;
  END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO ntou_backend;
GRANT SELECT ON public.profiles,public.rooms,public.reservations,public.violations,public.notifications,public.push_subscriptions,public.audit_logs TO ntou_backend;
GRANT INSERT ON public.profiles,public.reservations,public.violations,public.notifications,public.push_subscriptions,public.audit_logs TO ntou_backend;
GRANT UPDATE (verified,suspended) ON public.profiles TO ntou_backend;
GRANT UPDATE ON public.reservations,public.violations,public.notifications TO ntou_backend;
GRANT UPDATE(map_path) ON public.rooms TO ntou_backend;
GRANT DELETE ON public.push_subscriptions TO ntou_backend;
GRANT USAGE,SELECT ON SEQUENCE public.audit_logs_id_seq TO ntou_backend;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.auth_rate_limits TO ntou_backend;

DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') AND to_regprocedure('auth.uid()') IS NOT NULL THEN
    GRANT SELECT ON public.profiles,public.notifications TO authenticated;
    CREATE POLICY profile_owner_read ON public.profiles FOR SELECT TO authenticated USING ((SELECT auth.uid()) = id);
    CREATE POLICY notification_owner_read ON public.notifications FOR SELECT TO authenticated USING ((SELECT auth.uid()) = user_id);
  END IF;
  IF EXISTS (SELECT FROM pg_publication WHERE pubname='supabase_realtime') THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.notifications;
  END IF;
  IF to_regclass('storage.buckets') IS NOT NULL THEN
    INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
      VALUES('room-maps','room-maps',false,2097152,ARRAY['image/png','image/webp']) ON CONFLICT(id) DO NOTHING;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname='service_role') THEN
    GRANT SELECT ON public.notifications,public.push_subscriptions TO service_role;
    GRANT DELETE ON public.push_subscriptions TO service_role;
  END IF;
END $$;
COMMIT;
