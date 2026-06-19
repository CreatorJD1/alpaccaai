-- Unit Supply & Rations Tracker — schema, invite-only access, and per-section RLS.
--
-- Run this once against your Supabase project (SQL editor, or `supabase db push`).
-- Then run supabase/seed.sql to create your unit (C/2-218th FA) and its sections.
--
-- DESIGN INTENT:
--   * PRIVATE / INVITE-ONLY. There is no public sign-up path in the app, and the
--     database refuses to leak: every table has RLS ON and there is NO anonymous
--     policy anywhere. A row is only visible to an authenticated user whose
--     profile is scoped to the same unit. A leaked build with the anon key still
--     reads nothing without an invited, unit-scoped account.
--   * MINIMAL PII. soldiers holds last_name / first_initial / rank / section /
--     duty_status only. There is deliberately no SSN, no DoD ID, no contact field.
--   * Accounts are created by a supply_clerk / supply_sergeant (admin) who inserts
--     a profile row for an invited auth user. Self-service registration is off.

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

create table if not exists units (
  id         uuid primary key default gen_random_uuid(),
  battalion  text not null,                     -- e.g. '2-218th FA'
  name       text not null,                     -- e.g. 'C Battery'
  uic        text,
  created_at timestamptz not null default now()
);

create table if not exists sections (
  id         uuid primary key default gen_random_uuid(),
  unit_id    uuid not null references units(id) on delete cascade,
  name       text not null,                     -- GUN 1/2/3, AMMO, FDC, HEADQUARTERS
  sort_order int  not null default 0
);

-- App roles. section_id is set only for section_chief (the one section they own).
create table if not exists profiles (
  id         uuid primary key references auth.users(id) on delete cascade,
  unit_id    uuid not null references units(id) on delete cascade,
  role       text not null check (role in
               ('supply_clerk','supply_sergeant','section_chief','viewer')),
  section_id uuid references sections(id) on delete set null,
  full_name  text,
  created_at timestamptz not null default now()
);

create table if not exists soldiers (
  id            uuid primary key default gen_random_uuid(),
  unit_id       uuid not null references units(id) on delete cascade,
  section_id    uuid not null references sections(id) on delete cascade,
  rank          text not null,
  last_name     text not null,
  first_initial text not null,
  duty_status   text not null default 'present' check (duty_status in
                  ('present','leave','tdy','sick','appointment','details','awol')),
  notes         text,
  updated_at    timestamptz not null default now(),
  updated_by    uuid references auth.users(id)
);

create table if not exists ration_inventory (
  id                  uuid primary key default gen_random_uuid(),
  unit_id             uuid not null references units(id) on delete cascade,
  item                text not null default 'MRE' check (item in ('MRE','A_RATION','UGR')),
  on_hand_cases       int  not null default 0,
  meals_per_case      int  not null default 12,   -- MRE case = 12 meals
  loose_meals         int  not null default 0,
  reorder_point_meals int  not null default 0,
  updated_at          timestamptz not null default now(),
  updated_by          uuid references auth.users(id),
  unique (unit_id, item)
);

create table if not exists ration_counts (
  id            uuid primary key default gen_random_uuid(),
  unit_id       uuid not null references units(id) on delete cascade,
  section_id    uuid not null references sections(id) on delete cascade,
  meal_date     date not null default current_date,
  meal          text not null check (meal in ('B','L','D','Midnight')),
  headcount_fed int  not null default 0,
  source        text not null default 'MRE' check (source in ('MRE','hot')),
  entered_by    uuid references auth.users(id),
  created_at    timestamptz not null default now()
);

create table if not exists headcount_log (
  id          uuid primary key default gen_random_uuid(),
  unit_id     uuid not null references units(id) on delete cascade,
  section_id  uuid not null references sections(id) on delete cascade,
  as_of       timestamptz not null default now(),
  present     int not null default 0,
  assigned    int not null default 0,
  entered_by  uuid references auth.users(id)
);

-- ---------------------------------------------------------------------------
-- Helper functions (SECURITY DEFINER so policies can read the caller's profile
-- without recursive RLS on the profiles table itself).
-- ---------------------------------------------------------------------------

create or replace function app_unit_id() returns uuid
  language sql stable security definer set search_path = public as $$
  select unit_id from profiles where id = auth.uid()
$$;

create or replace function app_role() returns text
  language sql stable security definer set search_path = public as $$
  select role from profiles where id = auth.uid()
$$;

create or replace function app_section_id() returns uuid
  language sql stable security definer set search_path = public as $$
  select section_id from profiles where id = auth.uid()
$$;

create or replace function app_is_admin() returns boolean
  language sql stable security definer set search_path = public as $$
  select coalesce(app_role() in ('supply_clerk','supply_sergeant'), false)
$$;

-- ---------------------------------------------------------------------------
-- Row-Level Security. RLS ON everywhere; no anon access anywhere.
-- ---------------------------------------------------------------------------

alter table units            enable row level security;
alter table sections         enable row level security;
alter table profiles         enable row level security;
alter table soldiers         enable row level security;
alter table ration_inventory enable row level security;
alter table ration_counts    enable row level security;
alter table headcount_log    enable row level security;

-- Everyone in a unit can READ that unit, its sections, and its roster.
create policy unit_read   on units    for select using (id = app_unit_id());
create policy sect_read   on sections for select using (unit_id = app_unit_id());
create policy sol_read    on soldiers for select using (unit_id = app_unit_id());
create policy inv_read    on ration_inventory for select using (unit_id = app_unit_id());
create policy rc_read     on ration_counts    for select using (unit_id = app_unit_id());
create policy hc_read     on headcount_log    for select using (unit_id = app_unit_id());

-- You can see your own profile; admins manage everyone's profile in their unit
-- (this is the invite mechanism — admins insert a profile for an invited user).
create policy prof_self_read on profiles for select
  using (id = auth.uid() or (unit_id = app_unit_id() and app_is_admin()));
create policy prof_admin_write on profiles for all
  using (app_is_admin() and unit_id = app_unit_id())
  with check (app_is_admin() and unit_id = app_unit_id());

-- Roster + inventory: only admins (clerk / supply sergeant) write.
create policy sol_admin_write on soldiers for all
  using (app_is_admin() and unit_id = app_unit_id())
  with check (app_is_admin() and unit_id = app_unit_id());
create policy inv_admin_write on ration_inventory for all
  using (app_is_admin() and unit_id = app_unit_id())
  with check (app_is_admin() and unit_id = app_unit_id());

-- Headcount + ration counts: admins write anywhere in the unit; a section_chief
-- writes ONLY their own section. (This is the per-section lockdown.)
create policy hc_write on headcount_log for all
  using (
    unit_id = app_unit_id()
    and (app_is_admin() or section_id = app_section_id())
  )
  with check (
    unit_id = app_unit_id()
    and (app_is_admin() or section_id = app_section_id())
  );

create policy rc_write on ration_counts for all
  using (
    unit_id = app_unit_id()
    and (app_is_admin() or section_id = app_section_id())
  )
  with check (
    unit_id = app_unit_id()
    and (app_is_admin() or section_id = app_section_id())
  );

-- Units/sections are administered by admins only.
create policy unit_admin_write on units for all
  using (id = app_unit_id() and app_is_admin())
  with check (id = app_unit_id() and app_is_admin());
create policy sect_admin_write on sections for all
  using (unit_id = app_unit_id() and app_is_admin())
  with check (unit_id = app_unit_id() and app_is_admin());

-- NOTE: To fully disable self sign-up, also turn OFF "Enable email signups" in
-- Supabase Auth settings and create users via the admin invite flow. With signups
-- off, only an admin (service role / dashboard) can mint an auth user; the app
-- then attaches their profile row above. That is the invite-only guarantee.
