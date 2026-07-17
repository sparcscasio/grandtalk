create table if not exists public.messages (
  message_id text primary key,
  sender_id text not null,
  receiver_id text not null,
  original_text text not null,
  translated_raw text,
  translated_text text not null,
  detected_terms jsonb not null default '[]'::jsonb,
  emotions jsonb not null default '[]'::jsonb,
  intents jsonb not null default '[]'::jsonb,
  warnings jsonb not null default '[]'::jsonb,
  audio_url text,
  is_read boolean not null default false,
  created_at timestamptz not null default now(),
  read_at timestamptz
);

create index if not exists messages_receiver_pending_idx
on public.messages (receiver_id, is_read, created_at);

alter table public.messages enable row level security;
-- service_role 키로만 백엔드에서 접근하므로 공개 정책은 만들지 않음.
