-- cf-mail Supabase 存储表
-- 在 Supabase Dashboard → SQL Editor 中运行此脚本

-- 1. 创建表
create table if not exists cf_mail_store (
  key        text primary key,
  value      text not null,
  expires_at timestamptz not null default (now() + interval '5 minutes')
);

-- 2. 按过期时间索引（加速查询时过滤）
create index if not exists idx_cf_mail_expires on cf_mail_store (expires_at);

-- 3. 启用 RLS（行级安全）
alter table cf_mail_store enable row level security;

-- 4. 允许 anon 角色读写（Worker 使用 anon key）
create policy "Allow anon insert" on cf_mail_store
  for insert to anon with check (true);

create policy "Allow anon select" on cf_mail_store
  for select to anon using (true);

-- 5. 允许 upsert（重复 key 时更新）
-- Supabase REST API 使用 Prefer: resolution=merge-duplicates 头实现

-- 6. 自动清理过期数据（可选）
-- 方法 A：使用 pg_cron 扩展（Supabase 免费版支持）
-- 在 Supabase Dashboard → Database → Extensions 中启用 pg_cron，然后运行：

-- select cron.schedule(
--   'cleanup-cf-mail',
--   '*/5 * * * *',  -- 每 5 分钟运行一次
--   $$delete from cf_mail_store where expires_at < now()$$
-- );

-- 方法 B：不清理，查询时通过 expires_at 过滤（Worker 已实现）
-- 数据会累积但不影响功能，定期手动清理即可
