-- SEQUENCE: public.md_activarbot_id_seq

-- DROP SEQUENCE IF EXISTS public.md_activarbot_id_seq;

CREATE SEQUENCE IF NOT EXISTS public.md_activarbot_id_seq
    INCREMENT 1
    START 1
    MINVALUE 1
    MAXVALUE 2147483647
    CACHE 1;

-- SEQUENCE: public.md_leadconsolidado_id_seq

-- DROP SEQUENCE IF EXISTS public.md_leadconsolidado_id_seq;

CREATE SEQUENCE IF NOT EXISTS public.md_leadconsolidado_id_seq
    INCREMENT 1
    START 1
    MINVALUE 1
    MAXVALUE 2147483647
    CACHE 1;
	
-- SEQUENCE: public.me_asesor_id_seq

-- DROP SEQUENCE IF EXISTS public.me_asesor_id_seq;

CREATE SEQUENCE IF NOT EXISTS public.me_asesor_id_seq
    INCREMENT 1
    START 1
    MINVALUE 1
    MAXVALUE 2147483647
    CACHE 1;

-- SEQUENCE: public.me_supervisor_id_seq

-- DROP SEQUENCE IF EXISTS public.me_supervisor_id_seq;

CREATE SEQUENCE IF NOT EXISTS public.me_supervisor_id_seq
    INCREMENT 1
    START 1
    MINVALUE 1
    MAXVALUE 2147483647
    CACHE 1;

-- SEQUENCE: public.n8n_chat_histories_id_seq

-- DROP SEQUENCE IF EXISTS public.n8n_chat_histories_id_seq;

CREATE SEQUENCE IF NOT EXISTS public.n8n_chat_histories_id_seq
    INCREMENT 1
    START 1
    MINVALUE 1
    MAXVALUE 2147483647
    CACHE 1;

-- FUNCTION: public.uuid_generate_v1()

-- DROP FUNCTION IF EXISTS public.uuid_generate_v1();

CREATE OR REPLACE FUNCTION public.uuid_generate_v1(
	)
    RETURNS uuid
    LANGUAGE 'c'
    COST 1
    VOLATILE STRICT PARALLEL SAFE 
AS '$libdir/uuid-ossp', 'uuid_generate_v1'
;

ALTER FUNCTION public.uuid_generate_v1()
    OWNER TO postgres;

	
-- Table: public.me_supervisor

-- DROP TABLE IF EXISTS public.me_supervisor;

CREATE TABLE IF NOT EXISTS public.me_supervisor
(
    id integer NOT NULL DEFAULT nextval('me_supervisor_id_seq'::regclass),
    nombre_supervisor text COLLATE pg_catalog."default" NOT NULL,
    correo_supervisor character varying COLLATE pg_catalog."default",
    celular_supervisor character varying COLLATE pg_catalog."default",
    activo boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT me_supervisor_pkey PRIMARY KEY (id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.me_supervisor
    OWNER to postgres;

-- Table: public.me_asesor

-- DROP TABLE IF EXISTS public.me_asesor;

CREATE TABLE IF NOT EXISTS public.me_asesor
(
    id integer NOT NULL DEFAULT nextval('me_asesor_id_seq'::regclass),
    nbrasesor text COLLATE pg_catalog."default",
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    numcelularasesor character varying COLLATE pg_catalog."default",
    asesor_id text COLLATE pg_catalog."default",
    numordenasesor bigint,
    descorreoelectronicoasesor character varying COLLATE pg_catalog."default",
    desrolasesor text COLLATE pg_catalog."default",
    CONSTRAINT me_asesor_pkey PRIMARY KEY (id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.me_asesor
    OWNER to postgres;


-- Table: public.md_activarbot

-- DROP TABLE IF EXISTS public.md_activarbot;

CREATE TABLE IF NOT EXISTS public.md_activarbot
(
    id integer NOT NULL DEFAULT nextval('md_activarbot_id_seq'::regclass),
    nombre_bot text COLLATE pg_catalog."default",
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    created_by character varying COLLATE pg_catalog."default",
    updated_by character varying COLLATE pg_catalog."default",
    nc_order numeric,
    estado_bot text COLLATE pg_catalog."default",
    CONSTRAINT md_activarbot_pkey PRIMARY KEY (id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.md_activarbot
    OWNER to postgres;
	
	
-- Table: public.md_leadasignacion

-- DROP TABLE IF EXISTS public.md_leadasignacion;

CREATE TABLE IF NOT EXISTS public.md_leadasignacion
(
    lead_id text COLLATE pg_catalog."default" NOT NULL,
    proyecto_campania text COLLATE pg_catalog."default",
    plataforma text COLLATE pg_catalog."default",
    fecha_ingreso_lead timestamp with time zone,
    nombre_lead text COLLATE pg_catalog."default",
    celular_lead text COLLATE pg_catalog."default",
    correo_lead text COLLATE pg_catalog."default",
    city_lead text COLLATE pg_catalog."default",
    estado_lead text COLLATE pg_catalog."default",
    es_recontacto_lead text COLLATE pg_catalog."default",
    me_asesor_id integer,
    job_lead text COLLATE pg_catalog."default",
    observaciones text COLLATE pg_catalog."default",
    intentos_contacto_lead bigint DEFAULT 1,
    asesor_id bigint,
    nombre_supervisor text COLLATE pg_catalog."default",
    id bigint,
    supervisor_id integer,
    CONSTRAINT md_leadasignacion_pkey PRIMARY KEY (lead_id),
    CONSTRAINT fk_me_asesor_md_leadasi_a629any7wi FOREIGN KEY (me_asesor_id)
        REFERENCES public.me_asesor (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION,
    CONSTRAINT fk_supervisor FOREIGN KEY (supervisor_id)
        REFERENCES public.me_supervisor (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE SET NULL
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.md_leadasignacion
    OWNER to postgres;


-- Table: public.md_leadconsolidado

-- DROP TABLE IF EXISTS public.md_leadconsolidado;

CREATE TABLE IF NOT EXISTS public.md_leadconsolidado
(
    id bigint NOT NULL DEFAULT nextval('md_leadconsolidado_id_seq'::regclass),
    nombre_lead text COLLATE pg_catalog."default",
    plataforma text COLLATE pg_catalog."default" DEFAULT 'web formulario'::text,
    proyecto_campania text COLLATE pg_catalog."default",
    fecha_ingreso_lead timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    celular_lead character varying COLLATE pg_catalog."default",
    correo_lead character varying COLLATE pg_catalog."default",
    city_lead text COLLATE pg_catalog."default",
    job_lead text COLLATE pg_catalog."default",
    lead_id text COLLATE pg_catalog."default" DEFAULT gen_random_uuid(),
    me_asesor_id integer,
    observaciones text COLLATE pg_catalog."default",
    CONSTRAINT md_leadconsolidado_pkey PRIMARY KEY (id),
    CONSTRAINT fk_me_asesor_md_leadcon_tyhjbavxva FOREIGN KEY (me_asesor_id)
        REFERENCES public.me_asesor (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.md_leadconsolidado
    OWNER to postgres;

-- Table: public.md_leadfacebookinstagram

-- DROP TABLE IF EXISTS public.md_leadfacebookinstagram;

CREATE TABLE IF NOT EXISTS public.md_leadfacebookinstagram
(
    lead_id text COLLATE pg_catalog."default" NOT NULL,
    created_time timestamp with time zone,
    lead_id_form text COLLATE pg_catalog."default",
    lead_ad_name text COLLATE pg_catalog."default",
    lead_adset_name text COLLATE pg_catalog."default",
    created_date text COLLATE pg_catalog."default",
    lead_platform text COLLATE pg_catalog."default",
    lead_campaign_name text COLLATE pg_catalog."default",
    full_name_final text COLLATE pg_catalog."default",
    full_phone_final text COLLATE pg_catalog."default",
    full_city_final text COLLATE pg_catalog."default",
    full_email_final text COLLATE pg_catalog."default",
    full_job_final text COLLATE pg_catalog."default",
    CONSTRAINT md_leadfacebookinstagram_pkey PRIMARY KEY (lead_id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.md_leadfacebookinstagram
    OWNER to postgres;

-- Table: public.md_leadtiktok

-- DROP TABLE IF EXISTS public.md_leadtiktok;

CREATE TABLE IF NOT EXISTS public.md_leadtiktok
(
    lead_id text COLLATE pg_catalog."default" NOT NULL,
    created_time timestamp without time zone,
    ad_id text COLLATE pg_catalog."default",
    ad_name text COLLATE pg_catalog."default",
    adgroup_id text COLLATE pg_catalog."default",
    adgroup_name text COLLATE pg_catalog."default",
    campaign_id text COLLATE pg_catalog."default",
    campaign_name text COLLATE pg_catalog."default",
    form_id text COLLATE pg_catalog."default",
    form_name text COLLATE pg_catalog."default",
    full_email_final text COLLATE pg_catalog."default",
    full_name_final text COLLATE pg_catalog."default",
    full_phone_final text COLLATE pg_catalog."default",
    lead_platform text COLLATE pg_catalog."default",
    full_job_final text COLLATE pg_catalog."default",
    full_city_final text COLLATE pg_catalog."default",
    CONSTRAINT md_leadtiktok_pkey PRIMARY KEY (lead_id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.md_leadtiktok
    OWNER to postgres;



-- Table: public.me_estado

-- DROP TABLE IF EXISTS public.me_estado;

CREATE TABLE IF NOT EXISTS public.me_estado
(
    id uuid NOT NULL DEFAULT uuid_generate_v1(),
    codestado character varying(100) COLLATE pg_catalog."default" DEFAULT NULL::character varying,
    nbrestado character varying(100) COLLATE pg_catalog."default" DEFAULT NULL::character varying,
    debestado text COLLATE pg_catalog."default",
    tipoentidad character varying(50) COLLATE pg_catalog."default" DEFAULT NULL::character varying,
    ordenvisualizacion integer DEFAULT 1,
    esestadoactivo boolean DEFAULT true,
    esestadoinicial boolean DEFAULT false,
    esestadofinal boolean DEFAULT false,
    flgactivoestado boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    created_by uuid,
    CONSTRAINT me_estado_pkey PRIMARY KEY (id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.me_estado
    OWNER to postgres;
	


-- Table: public.n8n_chat_histories

-- DROP TABLE IF EXISTS public.n8n_chat_histories;

CREATE TABLE IF NOT EXISTS public.n8n_chat_histories
(
    id integer NOT NULL DEFAULT nextval('n8n_chat_histories_id_seq'::regclass),
    session_id character varying(255) COLLATE pg_catalog."default" NOT NULL,
    message jsonb NOT NULL
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.n8n_chat_histories
    OWNER to postgres;

-- Table: public.todas_las_citas_asesores

-- DROP TABLE IF EXISTS public.todas_las_citas_asesores;

CREATE TABLE IF NOT EXISTS public.todas_las_citas_asesores
(
    esquema_asesor text COLLATE pg_catalog."default" NOT NULL,
    id bigint NOT NULL,
    tipo_contacto_lead text COLLATE pg_catalog."default",
    seguimiento_lead text COLLATE pg_catalog."default",
    fecha_contacto_lead timestamp without time zone,
    observaciones text COLLATE pg_catalog."default",
    estado_contacto_lead text COLLATE pg_catalog."default",
    fecha_cita_lead timestamp without time zone,
    tipo_cita_lead text COLLATE pg_catalog."default",
    codigo_lead text COLLATE pg_catalog."default",
    fecha_insercion timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    numero_asesor integer
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.todas_las_citas_asesores
    OWNER to postgres;


-- FUNCTION: public.f_union_leads_contactos_asesor_schemas()

-- DROP FUNCTION IF EXISTS public.f_union_leads_contactos_asesor_schemas();

CREATE OR REPLACE FUNCTION public.f_union_leads_contactos_asesor_schemas(
	)
    RETURNS TABLE(schema_name text, asesor_id integer, asesor_nombre text, codigo_lead text, nombre_lead text, celular_lead text, correo_lead text, plataforma text, proyecto_campania text, fecha_ingreso_lead timestamp with time zone, estado_lead text, contacto_id text, fecha_contacto_lead timestamp with time zone, tipo_contacto_lead text, seguimiento_lead text, estado_contacto_lead text, fecha_cita_lead timestamp with time zone, tipo_cita_lead text, observaciones_contacto text) 
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
    ROWS 1000

AS $BODY$
DECLARE
  r_schema   record;
  suf_txt    text;
  suf_int    int;
BEGIN
  /*
    Recorremos todos los esquemas cuyo nombre calce "asesor" + numero
    Ej.: asesor1, asesor5, asesor8, etc.
  */
  FOR r_schema IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname ~ '^asesor[0-9]+$'
    ORDER BY nspname
  LOOP
    -- Extraemos el sufijo numérico: "asesor" (6 letras) -> resto
    suf_txt := substring(r_schema.nspname from 7);   -- a partir del 7° carácter
    suf_int := NULLIF(suf_txt, '')::int;

    /*
      Unimos contra public.me_asesor por me_asesor.asesor_id (texto),
      que es el valor que forma el nombre del schema (asesor{asesor_id}).
      Si tu zona horaria es otra, cámbiala en los AT TIME ZONE.
    */
    RETURN QUERY EXECUTE format($f$
      SELECT
        %L::text                     AS schema_name,
        %s::int                      AS asesor_id,
        mae.nbrasesor::text          AS asesor_nombre,
        l.codigo_lead::text,
        l.nombre_lead::text,
        l.celular_lead::text,
        l.correo_lead::text,
        l.plataforma::text,
        l.proyecto_campania::text,
        (l.fecha_ingreso_lead AT TIME ZONE 'America/Lima')::timestamptz AS fecha_ingreso_lead,
        l.estado_lead::text,
        c.id::text                   AS contacto_id,
        (c.fecha_contacto_lead AT TIME ZONE 'America/Lima')::timestamptz AS fecha_contacto_lead,
        c.tipo_contacto_lead::text,
        c.seguimiento_lead::text,
        c.estado_contacto_lead::text,
        (c.fecha_cita_lead AT TIME ZONE 'America/Lima')::timestamptz AS fecha_cita_lead,
        c.tipo_cita_lead::text,
        c.observaciones::text        AS observaciones_contacto
      FROM %I.md_lead AS l
      LEFT JOIN %I.md_contactolead AS c
             ON c.codigo_lead = l.codigo_lead
      LEFT JOIN public.me_asesor AS mae
             ON mae.asesor_id = %L
    $f$, r_schema.nspname, suf_int, r_schema.nspname, r_schema.nspname, suf_txt);

  END LOOP;
END;
$BODY$;

ALTER FUNCTION public.f_union_leads_contactos_asesor_schemas()
    OWNER TO postgres;

-- View: public.vw_leads_contactos_asesores

-- DROP VIEW public.vw_leads_contactos_asesores;

CREATE OR REPLACE VIEW public.vw_leads_contactos_asesores
 AS
 SELECT schema_name,
    asesor_id,
    asesor_nombre,
    codigo_lead,
    nombre_lead,
    celular_lead,
    correo_lead,
    plataforma,
    proyecto_campania,
    fecha_ingreso_lead,
    estado_lead,
    contacto_id,
    fecha_contacto_lead,
    tipo_contacto_lead,
    seguimiento_lead,
    estado_contacto_lead,
    fecha_cita_lead,
    tipo_cita_lead,
    observaciones_contacto
   FROM f_union_leads_contactos_asesor_schemas() f_union_leads_contactos_asesor_schemas(schema_name, asesor_id, asesor_nombre, codigo_lead, nombre_lead, celular_lead, correo_lead, plataforma, proyecto_campania, fecha_ingreso_lead, estado_lead, contacto_id, fecha_contacto_lead, tipo_contacto_lead, seguimiento_lead, estado_contacto_lead, fecha_cita_lead, tipo_cita_lead, observaciones_contacto)
  ORDER BY schema_name, fecha_ingreso_lead, codigo_lead;

ALTER TABLE public.vw_leads_contactos_asesores
    OWNER TO postgres;



-- FUNCTION: public.asignar_supervisor_equitativo()

-- DROP FUNCTION IF EXISTS public.asignar_supervisor_equitativo();

CREATE OR REPLACE FUNCTION public.asignar_supervisor_equitativo(
	)
    RETURNS integer
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
AS $BODY$
DECLARE
    supervisor_id INTEGER;
BEGIN
    -- Obtener el supervisor con menos leads asignados hoy
    SELECT a.id INTO supervisor_id
    FROM me_asesor a
    WHERE a.desrolasesor = 'Supervisor'
    ORDER BY (
        SELECT COUNT(*) 
        FROM md_leadasignacion l 
        WHERE l.me_asesor_id = a.id 
        AND l.fecha_ingreso_lead::DATE = CURRENT_DATE
    ) ASC, a.numordenasesor ASC
    LIMIT 1;
    
    RETURN supervisor_id;
END;
$BODY$;

ALTER FUNCTION public.asignar_supervisor_equitativo()
    OWNER TO postgres;


-- FUNCTION: public.buscar_lead_contacto_en_esquemas(text)

-- DROP FUNCTION IF EXISTS public.buscar_lead_contacto_en_esquemas(text);

CREATE OR REPLACE FUNCTION public.buscar_lead_contacto_en_esquemas(
	p_codigo_lead text)
    RETURNS TABLE(esquema text, tabla text, id bigint, codigo_lead text, tipo_contacto_lead text, seguimiento_lead text, fecha_contacto_lead timestamp without time zone, observaciones text, estado_contacto_lead text, fecha_cita_lead timestamp without time zone, tipo_cita_lead text, encontrado boolean) 
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
    ROWS 1000

AS $BODY$
DECLARE
    schema_rec RECORD;
    sql_query TEXT;
    result_rec RECORD;
BEGIN
    -- Recorrer todos los esquemas que empiezan con 'asesor'
    FOR schema_rec IN 
        SELECT schema_name 
        FROM information_schema.schemata 
        WHERE schema_name LIKE 'asesor%'
        ORDER BY schema_name
    LOOP
        -- Verificar que existe la tabla md_contactolead en el esquema
        IF EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = schema_rec.schema_name 
            AND table_name = 'md_contactolead'
        ) THEN
            -- Construir consulta para buscar el lead
            sql_query := format(
                'SELECT %L as esquema, 
                        ''md_contactolead'' as tabla,
                        id,
                        codigo_lead,
                        COALESCE(tipo_contacto_lead, ''sin_tipo'') as tipo_contacto_lead,
                        COALESCE(seguimiento_lead, ''sin_seguimiento'') as seguimiento_lead,
                        fecha_contacto_lead,
                        COALESCE(observaciones, ''sin_observaciones'') as observaciones,
                        COALESCE(estado_contacto_lead, ''sin_estado'') as estado_contacto_lead,
                        fecha_cita_lead,
                        COALESCE(tipo_cita_lead, ''sin_tipo_cita'') as tipo_cita_lead,
                        true as encontrado
                 FROM %I.md_contactolead 
                 WHERE codigo_lead = %L',
                schema_rec.schema_name,
                schema_rec.schema_name,
                p_codigo_lead
            );
            
            -- Ejecutar y retornar si encuentra el registro
            FOR result_rec IN EXECUTE sql_query LOOP
                RETURN QUERY SELECT 
                    result_rec.esquema::TEXT,
                    result_rec.tabla::TEXT,
                    result_rec.id::BIGINT,
                    result_rec.codigo_lead::TEXT,
                    result_rec.tipo_contacto_lead::TEXT,
                    result_rec.seguimiento_lead::TEXT,
                    result_rec.fecha_contacto_lead::TIMESTAMP,
                    result_rec.observaciones::TEXT,
                    result_rec.estado_contacto_lead::TEXT,
                    result_rec.fecha_cita_lead::TIMESTAMP,
                    result_rec.tipo_cita_lead::TEXT,
                    result_rec.encontrado::BOOLEAN;
                    
                RETURN; -- Salir después de encontrarlo
            END LOOP;
        END IF;
    END LOOP;
    
    -- Si no encuentra nada, retornar registro vacío
    RETURN QUERY SELECT 
        'no_encontrado'::TEXT,
        'md_contactolead'::TEXT,
        NULL::BIGINT,
        p_codigo_lead::TEXT,
        'sin_tipo'::TEXT,
        'sin_seguimiento'::TEXT,
        NULL::TIMESTAMP,
        'sin_observaciones'::TEXT,
        'sin_estado'::TEXT,
        NULL::TIMESTAMP,
        'sin_tipo_cita'::TEXT,
        false::BOOLEAN;
        
END;
$BODY$;

ALTER FUNCTION public.buscar_lead_contacto_en_esquemas(text)
    OWNER TO postgres;


-- FUNCTION: public.buscar_lead_en_esquemas(text)

-- DROP FUNCTION IF EXISTS public.buscar_lead_en_esquemas(text);

CREATE OR REPLACE FUNCTION public.buscar_lead_en_esquemas(
	p_codigo_lead text)
    RETURNS TABLE(esquema text, tabla text, id bigint, plataforma text, proyecto_campania text, fecha_ingreso_lead timestamp without time zone, nombre_lead text, celular_lead text, correo_lead text, city_lead text, job_lead text, estado_lead text, codigo_lead text, encontrado boolean) 
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
    ROWS 1000

AS $BODY$
DECLARE
    schema_rec RECORD;
    sql_query TEXT;
    result_rec RECORD;
    found_any BOOLEAN := false;
BEGIN
    -- Recorrer todos los esquemas que empiezan con 'asesor'
    FOR schema_rec IN 
        SELECT schema_name 
        FROM information_schema.schemata 
        WHERE schema_name LIKE 'asesor%'
        ORDER BY schema_name
    LOOP
        -- Verificar que existe la tabla md_lead en el esquema
        IF EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = schema_rec.schema_name 
            AND table_name = 'md_lead'
        ) THEN
            -- Construir consulta para buscar el lead
            sql_query := format(
                'SELECT %L as esquema, 
                        ''md_lead'' as tabla,
                        id,
                        COALESCE(plataforma, ''sin_plataforma'') as plataforma,
                        COALESCE(proyecto_campania, ''sin_proyecto'') as proyecto_campania,
                        fecha_ingreso_lead,
                        COALESCE(nombre_lead, ''sin_nombre'') as nombre_lead,
                        COALESCE(celular_lead, ''sin_celular'') as celular_lead,
                        COALESCE(correo_lead, ''sin_correo'') as correo_lead,
                        COALESCE(city_lead, ''sin_ciudad'') as city_lead,
                        COALESCE(job_lead, ''sin_trabajo'') as job_lead,
                        COALESCE(estado_lead, ''sin_estado'') as estado_lead,
                        codigo_lead,
                        true as encontrado
                 FROM %I.md_lead 
                 WHERE codigo_lead = %L',
                schema_rec.schema_name,
                schema_rec.schema_name,
                p_codigo_lead
            );
            
            -- Ejecutar y retornar TODOS los registros encontrados
            FOR result_rec IN EXECUTE sql_query LOOP
                found_any := true;
                RETURN QUERY SELECT 
                    result_rec.esquema::TEXT,
                    result_rec.tabla::TEXT,
                    result_rec.id::BIGINT,
                    result_rec.plataforma::TEXT,
                    result_rec.proyecto_campania::TEXT,
                    result_rec.fecha_ingreso_lead::TIMESTAMP,
                    result_rec.nombre_lead::TEXT,
                    result_rec.celular_lead::TEXT,
                    result_rec.correo_lead::TEXT,
                    result_rec.city_lead::TEXT,
                    result_rec.job_lead::TEXT,
                    result_rec.estado_lead::TEXT,
                    result_rec.codigo_lead::TEXT,
                    result_rec.encontrado::BOOLEAN;
            END LOOP;
        END IF;
    END LOOP;
    
    -- Si no encuentra nada en ningún esquema, retornar registro indicando que no se encontró
    IF NOT found_any THEN
        RETURN QUERY SELECT 
            'no_encontrado'::TEXT,
            'md_lead'::TEXT,
            NULL::BIGINT,
            'sin_plataforma'::TEXT,
            'sin_proyecto'::TEXT,
            NULL::TIMESTAMP,
            'sin_nombre'::TEXT,
            'sin_celular'::TEXT,
            'sin_correo'::TEXT,
            'sin_ciudad'::TEXT,
            'sin_trabajo'::TEXT,
            'sin_estado'::TEXT,
            p_codigo_lead::TEXT,
            false::BOOLEAN;
    END IF;
        
END;
$BODY$;

ALTER FUNCTION public.buscar_lead_en_esquemas(text)
    OWNER TO postgres;


	
	