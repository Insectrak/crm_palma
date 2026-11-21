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


-- FUNCTION: public.uuid_generate_v1mc()

-- DROP FUNCTION IF EXISTS public.uuid_generate_v1mc();

CREATE OR REPLACE FUNCTION public.uuid_generate_v1mc(
	)
    RETURNS uuid
    LANGUAGE 'c'
    COST 1
    VOLATILE STRICT PARALLEL SAFE 
AS '$libdir/uuid-ossp', 'uuid_generate_v1mc'
;

ALTER FUNCTION public.uuid_generate_v1mc()
    OWNER TO postgres;


-- FUNCTION: public.uuid_generate_v3(uuid, text)

-- DROP FUNCTION IF EXISTS public.uuid_generate_v3(uuid, text);

CREATE OR REPLACE FUNCTION public.uuid_generate_v3(
	namespace uuid,
	name text)
    RETURNS uuid
    LANGUAGE 'c'
    COST 1
    IMMUTABLE STRICT PARALLEL SAFE 
AS '$libdir/uuid-ossp', 'uuid_generate_v3'
;

ALTER FUNCTION public.uuid_generate_v3(uuid, text)
    OWNER TO postgres;


-- FUNCTION: public.uuid_generate_v4()

-- DROP FUNCTION IF EXISTS public.uuid_generate_v4();

CREATE OR REPLACE FUNCTION public.uuid_generate_v4(
	)
    RETURNS uuid
    LANGUAGE 'c'
    COST 1
    VOLATILE STRICT PARALLEL SAFE 
AS '$libdir/uuid-ossp', 'uuid_generate_v4'
;

ALTER FUNCTION public.uuid_generate_v4()
    OWNER TO postgres;


-- FUNCTION: public.uuid_generate_v5(uuid, text)

-- DROP FUNCTION IF EXISTS public.uuid_generate_v5(uuid, text);

CREATE OR REPLACE FUNCTION public.uuid_generate_v5(
	namespace uuid,
	name text)
    RETURNS uuid
    LANGUAGE 'c'
    COST 1
    IMMUTABLE STRICT PARALLEL SAFE 
AS '$libdir/uuid-ossp', 'uuid_generate_v5'
;

ALTER FUNCTION public.uuid_generate_v5(uuid, text)
    OWNER TO postgres;
