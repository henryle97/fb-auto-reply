create table if not exists processed_comments (
  comment_id    text primary key,
  post_id       text,
  from_id       text,
  from_name     text,
  message       text,
  source        text,
  public_reply  text,
  private_reply text,
  status        text,
  error         text,
  created_at    timestamptz default now()
);
create index if not exists processed_comments_created_at on processed_comments (created_at desc);
alter table processed_comments enable row level security;  -- only the service_role key can access it
