-- Seed your unit: C Battery, 2-218th FA and its six sections.
-- Run AFTER 0001_init.sql. Safe to re-run (guards on existing unit by name).

do $$
declare
  v_unit uuid;
begin
  select id into v_unit from units where battalion = '2-218th FA' and name = 'C Battery';
  if v_unit is null then
    insert into units (battalion, name) values ('2-218th FA', 'C Battery')
    returning id into v_unit;

    insert into sections (unit_id, name, sort_order) values
      (v_unit, 'GUN 1', 1),
      (v_unit, 'GUN 2', 2),
      (v_unit, 'GUN 3', 3),
      (v_unit, 'AMMO', 4),
      (v_unit, 'FDC', 5),
      (v_unit, 'HEADQUARTERS', 6);

    -- Start a Class I (MRE) inventory row so the rations screen has a home.
    insert into ration_inventory (unit_id, item, on_hand_cases, meals_per_case, reorder_point_meals)
    values (v_unit, 'MRE', 0, 12, 36);
  end if;
end $$;

-- AFTER you create your own login (invite yourself in Supabase Auth), attach an
-- admin profile so the app lets you in. Replace the email below with yours:
--
--   insert into profiles (id, unit_id, role, full_name)
--   select u.id, x.id, 'supply_clerk', 'Your Name'
--   from auth.users u
--   cross join (select id from units where name = 'C Battery' and battalion = '2-218th FA') x
--   where u.email = 'you@example.com';
