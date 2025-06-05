-- Table: public.error_logs

-- DROP TABLE IF EXISTS public.error_logs;

CREATE TABLE IF NOT EXISTS public.error_logs
(
    id integer NOT NULL DEFAULT nextval('error_logs_id_seq'::regclass),
    ts timestamp with time zone DEFAULT now(),
    function_name text COLLATE pg_catalog."default",
    chat_id bigint,
    error_message text COLLATE pg_catalog."default",
    CONSTRAINT error_logs_pkey PRIMARY KEY (id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.error_logs
    OWNER to bot_user;

-- Table: public.intervals

-- DROP TABLE IF EXISTS public.intervals;

CREATE TABLE IF NOT EXISTS public.intervals
(
    chat_id bigint NOT NULL,
    interval_minutes integer NOT NULL,
    enabled boolean NOT NULL,
    CONSTRAINT intervals_pkey PRIMARY KEY (chat_id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.intervals
    OWNER to bot_user;

-- Table: public.schedules

-- DROP TABLE IF EXISTS public.schedules;

CREATE TABLE IF NOT EXISTS public.schedules
(
    chat_id bigint NOT NULL,
    notify_time time without time zone NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    CONSTRAINT schedules_pkey PRIMARY KEY (chat_id),
    CONSTRAINT schedules_chat_id_fkey FOREIGN KEY (chat_id)
        REFERENCES public.users (chat_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.schedules
    OWNER to bot_user;

-- Table: public.subscriptions

-- DROP TABLE IF EXISTS public.subscriptions;

CREATE TABLE IF NOT EXISTS public.subscriptions
(
    chat_id bigint NOT NULL,
    symbol character varying(10) COLLATE pg_catalog."default" NOT NULL,
    CONSTRAINT subscriptions_pkey PRIMARY KEY (chat_id, symbol),
    CONSTRAINT subscriptions_chat_id_fkey FOREIGN KEY (chat_id)
        REFERENCES public.users (chat_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.subscriptions
    OWNER to bot_user;

-- Table: public.users

-- DROP TABLE IF EXISTS public.users;

CREATE TABLE IF NOT EXISTS public.users
(
    chat_id bigint NOT NULL,
    chat_name text COLLATE pg_catalog."default",
    CONSTRAINT users_pkey PRIMARY KEY (chat_id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.users
    OWNER to bot_user;

