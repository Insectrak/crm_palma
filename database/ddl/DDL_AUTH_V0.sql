-- Table: auth.users

-- DROP TABLE IF EXISTS auth.users;

CREATE TABLE IF NOT EXISTS auth.users
(
    id uuid NOT NULL DEFAULT uuid_generate_v1(),
    email character varying(255) COLLATE pg_catalog."default" NOT NULL,
    password_hash character varying(255) COLLATE pg_catalog."default" NOT NULL,
    first_name character varying(100) COLLATE pg_catalog."default",
    last_name character varying(100) COLLATE pg_catalog."default",
    avatar_url text COLLATE pg_catalog."default",
    is_active boolean DEFAULT true,
    is_verified boolean DEFAULT false,
    role character varying(50) COLLATE pg_catalog."default" DEFAULT 'user'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    last_login timestamp with time zone,
    login_count integer DEFAULT 0,
    advisor_schema character varying(20) COLLATE pg_catalog."default",
    advisor_name character varying(100) COLLATE pg_catalog."default",
    CONSTRAINT users_pkey PRIMARY KEY (id),
    CONSTRAINT users_email_key UNIQUE (email),
    CONSTRAINT users_email_check CHECK (email::text ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'::text),
    CONSTRAINT users_role_check CHECK (role::text = ANY (ARRAY['admin'::character varying::text, 'user'::character varying::text, 'moderator'::character varying::text])),
    CONSTRAINT advisor_schema_check CHECK ((advisor_schema::text = ANY (ARRAY['asesor1'::character varying, 'asesor2'::character varying, 'asesor3'::character varying, 'asesor4'::character varying]::text[])) OR advisor_schema IS NULL)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS auth.users
    OWNER to postgres;
-- Index: idx_users_active

-- DROP INDEX IF EXISTS auth.idx_users_active;

CREATE INDEX IF NOT EXISTS idx_users_active
    ON auth.users USING btree
    (is_active ASC NULLS LAST)
    WITH (fillfactor=100, deduplicate_items=True)
    TABLESPACE pg_default;
-- Index: idx_users_email

-- DROP INDEX IF EXISTS auth.idx_users_email;

CREATE INDEX IF NOT EXISTS idx_users_email
    ON auth.users USING btree
    (email COLLATE pg_catalog."default" ASC NULLS LAST)
    WITH (fillfactor=100, deduplicate_items=True)
    TABLESPACE pg_default;
	
-- Table: auth.password_resets

-- DROP TABLE IF EXISTS auth.password_resets;

CREATE TABLE IF NOT EXISTS auth.password_resets
(
    id uuid NOT NULL DEFAULT uuid_generate_v1(),
    user_id uuid NOT NULL,
    token character varying(255) COLLATE pg_catalog."default" NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT password_resets_pkey PRIMARY KEY (id),
    CONSTRAINT password_resets_token_key UNIQUE (token),
    CONSTRAINT password_resets_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES auth.users (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS auth.password_resets
    OWNER to postgres;
	
-- Table: auth.password_resets

-- DROP TABLE IF EXISTS auth.password_resets;

CREATE TABLE IF NOT EXISTS auth.password_resets
(
    id uuid NOT NULL DEFAULT uuid_generate_v1(),
    user_id uuid NOT NULL,
    token character varying(255) COLLATE pg_catalog."default" NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT password_resets_pkey PRIMARY KEY (id),
    CONSTRAINT password_resets_token_key UNIQUE (token),
    CONSTRAINT password_resets_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES auth.users (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS auth.password_resets
    OWNER to postgres;	
	
	
-- Table: auth.user_sessions

-- DROP TABLE IF EXISTS auth.user_sessions;

CREATE TABLE IF NOT EXISTS auth.user_sessions
(
    id uuid NOT NULL DEFAULT uuid_generate_v1(),
    user_id uuid NOT NULL,
    token character varying(255) COLLATE pg_catalog."default" NOT NULL,
    refresh_token character varying(255) COLLATE pg_catalog."default",
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    ip_address inet,
    user_agent text COLLATE pg_catalog."default",
    is_active boolean DEFAULT true,
    CONSTRAINT user_sessions_pkey PRIMARY KEY (id),
    CONSTRAINT user_sessions_refresh_token_key UNIQUE (refresh_token),
    CONSTRAINT user_sessions_token_key UNIQUE (token),
    CONSTRAINT user_sessions_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES auth.users (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE CASCADE
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS auth.user_sessions
    OWNER to postgres;
-- Index: idx_sessions_active

-- DROP INDEX IF EXISTS auth.idx_sessions_active;

CREATE INDEX IF NOT EXISTS idx_sessions_active
    ON auth.user_sessions USING btree
    (is_active ASC NULLS LAST)
    WITH (fillfactor=100, deduplicate_items=True)
    TABLESPACE pg_default;
-- Index: idx_sessions_token

-- DROP INDEX IF EXISTS auth.idx_sessions_token;

CREATE INDEX IF NOT EXISTS idx_sessions_token
    ON auth.user_sessions USING btree
    (token COLLATE pg_catalog."default" ASC NULLS LAST)
    WITH (fillfactor=100, deduplicate_items=True)
    TABLESPACE pg_default;
-- Index: idx_sessions_user_id

-- DROP INDEX IF EXISTS auth.idx_sessions_user_id;

CREATE INDEX IF NOT EXISTS idx_sessions_user_id
    ON auth.user_sessions USING btree
    (user_id ASC NULLS LAST)
    WITH (fillfactor=100, deduplicate_items=True)
    TABLESPACE pg_default;	
	
	
	
	-- FUNCTION: auth.create_user(text, text, text, text)

-- DROP FUNCTION IF EXISTS auth.create_user(text, text, text, text);

CREATE OR REPLACE FUNCTION auth.create_user(
	p_email text,
	p_password text,
	p_first_name text DEFAULT NULL::text,
	p_last_name text DEFAULT NULL::text)
    RETURNS json
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
DECLARE
    v_user_id UUID;
    v_password_hash TEXT;
    v_result JSON;
BEGIN
    -- Verificar si el email ya existe
    IF EXISTS (SELECT 1 FROM auth.users WHERE email = p_email) THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Email already exists',
            'error_code', 'EMAIL_EXISTS'
        );
    END IF;

    -- Hashear contraseña
    v_password_hash := auth.hash_password(p_password);
    
    -- Insertar usuario
    INSERT INTO auth.users (email, password_hash, first_name, last_name)
    VALUES (p_email, v_password_hash, p_first_name, p_last_name)
    RETURNING id INTO v_user_id;
    
    -- Retornar resultado exitoso
    SELECT json_build_object(
        'success', true,
        'message', 'User created successfully',
        'user', json_build_object(
            'id', u.id,
            'email', u.email,
            'first_name', u.first_name,
            'last_name', u.last_name,
            'created_at', u.created_at
        )
    ) INTO v_result
    FROM auth.users u WHERE u.id = v_user_id;
    
    RETURN v_result;
END;
$BODY$;

ALTER FUNCTION auth.create_user(text, text, text, text)
    OWNER TO postgres;


-- FUNCTION: auth.generate_token(integer)

-- DROP FUNCTION IF EXISTS auth.generate_token(integer);

CREATE OR REPLACE FUNCTION auth.generate_token(
	length integer DEFAULT 32)
    RETURNS text
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
AS $BODY$
BEGIN
    RETURN encode(gen_random_bytes(length), 'hex');
END;
$BODY$;

ALTER FUNCTION auth.generate_token(integer)
    OWNER TO postgres;
-- FUNCTION: auth.get_user_by_token(character varying)

-- DROP FUNCTION IF EXISTS auth.get_user_by_token(character varying);

CREATE OR REPLACE FUNCTION auth.get_user_by_token(
	p_token character varying)
    RETURNS json
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
DECLARE
    v_user_record RECORD;
    v_session_record RECORD;
BEGIN
    -- Buscar sesión activa y datos del usuario
    SELECT 
        u.id, u.email, u.first_name, u.last_name, u.role, 
        u.advisor_schema, u.advisor_name, u.is_active, u.is_verified,
        s.expires_at, s.created_at as session_created
    INTO v_user_record
    FROM auth.user_sessions s
    JOIN auth.users u ON u.id = s.user_id
    WHERE s.token = p_token 
      AND s.is_active = true 
      AND s.expires_at > now()
      AND u.is_active = true;

    IF v_user_record.id IS NULL THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Sesión no válida'
        );
    END IF;

    RETURN json_build_object(
        'success', true,
        'user', json_build_object(
            'id', v_user_record.id,
            'email', v_user_record.email,
            'first_name', v_user_record.first_name,
            'last_name', v_user_record.last_name,
            'role', v_user_record.role,
            'advisor_schema', v_user_record.advisor_schema,
            'advisor_name', v_user_record.advisor_name,
            'session_expires', v_user_record.expires_at,
            'session_created', v_user_record.session_created
        )
    );

EXCEPTION
    WHEN OTHERS THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Error interno del servidor'
        );
END;
$BODY$;

ALTER FUNCTION auth.get_user_by_token(character varying)
    OWNER TO postgres;
-- FUNCTION: auth.hash_password(text)

-- DROP FUNCTION IF EXISTS auth.hash_password(text);

CREATE OR REPLACE FUNCTION auth.hash_password(
	password text)
    RETURNS text
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
BEGIN
    RETURN crypt(password, gen_salt('bf', 12));
END;
$BODY$;

ALTER FUNCTION auth.hash_password(text)
    OWNER TO postgres;


-- FUNCTION: auth.login_user(character varying, character varying, inet, text)

-- DROP FUNCTION IF EXISTS auth.login_user(character varying, character varying, inet, text);

CREATE OR REPLACE FUNCTION auth.login_user(
	p_email character varying,
	p_password character varying,
	p_ip_address inet DEFAULT '127.0.0.1'::inet,
	p_user_agent text DEFAULT 'Unknown'::text)
    RETURNS json
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
DECLARE
    v_user_id UUID;
    v_password_hash VARCHAR;
    v_user_record RECORD;
    v_session_token VARCHAR;
    v_refresh_token VARCHAR;
    v_expires_at TIMESTAMPTZ;
    v_result JSON;
BEGIN
    -- Log del intento de login
    INSERT INTO auth.login_attempts (email, ip_address, success, attempted_at, error_message)
    VALUES (p_email, p_ip_address, false, now(), 'Login attempt started');

    -- Buscar usuario por email
    SELECT 
        id, password_hash, email, first_name, last_name, 
        role, advisor_schema, advisor_name, is_active, is_verified
    INTO v_user_record
    FROM auth.users 
    WHERE email = p_email AND is_active = true;

    -- Verificar si el usuario existe
    IF v_user_record.id IS NULL THEN
        -- Actualizar intento fallido
        UPDATE auth.login_attempts 
        SET error_message = 'User not found', success = false
        WHERE email = p_email AND attempted_at = (
            SELECT MAX(attempted_at) FROM auth.login_attempts WHERE email = p_email
        );
        
        RETURN json_build_object(
            'success', false,
            'message', 'Credenciales inválidas'
        );
    END IF;

    -- Verificar contraseña
    IF v_user_record.password_hash != crypt(p_password, v_user_record.password_hash) THEN
        -- Actualizar intento fallido
        UPDATE auth.login_attempts 
        SET error_message = 'Invalid password', success = false
        WHERE email = p_email AND attempted_at = (
            SELECT MAX(attempted_at) FROM auth.login_attempts WHERE email = p_email
        );
        
        RETURN json_build_object(
            'success', false,
            'message', 'Credenciales inválidas'
        );
    END IF;

    -- Verificar que el usuario esté verificado
    IF NOT v_user_record.is_verified THEN
        UPDATE auth.login_attempts 
        SET error_message = 'User not verified', success = false
        WHERE email = p_email AND attempted_at = (
            SELECT MAX(attempted_at) FROM auth.login_attempts WHERE email = p_email
        );
        
        RETURN json_build_object(
            'success', false,
            'message', 'Usuario no verificado'
        );
    END IF;

    -- Generar tokens de sesión
    v_session_token := encode(gen_random_bytes(32), 'base64');
    v_refresh_token := encode(gen_random_bytes(32), 'base64');
    v_expires_at := now() + interval '8 hours';

    -- Invalidar sesiones anteriores del usuario
    UPDATE auth.user_sessions 
    SET is_active = false 
    WHERE user_id = v_user_record.id AND is_active = true;

    -- Crear nueva sesión
    INSERT INTO auth.user_sessions (
        user_id, token, refresh_token, expires_at, 
        ip_address, user_agent, is_active
    ) VALUES (
        v_user_record.id, v_session_token, v_refresh_token, v_expires_at,
        p_ip_address, p_user_agent, true
    );

    -- Actualizar información del usuario
    UPDATE auth.users 
    SET 
        last_login = now(), 
        login_count = COALESCE(login_count, 0) + 1,
        updated_at = now()
    WHERE id = v_user_record.id;

    -- Marcar intento como exitoso
    UPDATE auth.login_attempts 
    SET success = true, error_message = 'Login successful'
    WHERE email = p_email AND attempted_at = (
        SELECT MAX(attempted_at) FROM auth.login_attempts WHERE email = p_email
    );

    -- Construir respuesta exitosa
    v_result := json_build_object(
        'success', true,
        'access_token', v_session_token,
        'refresh_token', v_refresh_token,
        'expires_at', v_expires_at,
        'user', json_build_object(
            'id', v_user_record.id,
            'email', v_user_record.email,
            'first_name', v_user_record.first_name,
            'last_name', v_user_record.last_name,
            'role', v_user_record.role,
            'advisor_schema', v_user_record.advisor_schema,
            'advisor_name', v_user_record.advisor_name
        )
    );

    RETURN v_result;

EXCEPTION
    WHEN OTHERS THEN
        -- Log error en caso de excepción
        UPDATE auth.login_attempts 
        SET success = false, error_message = SQLERRM
        WHERE email = p_email AND attempted_at = (
            SELECT MAX(attempted_at) FROM auth.login_attempts WHERE email = p_email
        );
        
        RETURN json_build_object(
            'success', false,
            'message', 'Error interno del servidor'
        );
END;
$BODY$;

ALTER FUNCTION auth.login_user(character varying, character varying, inet, text)
    OWNER TO postgres;


-- FUNCTION: auth.login_user(text, text, text, text)

-- DROP FUNCTION IF EXISTS auth.login_user(text, text, text, text);

CREATE OR REPLACE FUNCTION auth.login_user(
	p_email text,
	p_password text,
	p_ip_address text DEFAULT NULL::text,
	p_user_agent text DEFAULT NULL::text)
    RETURNS json
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
DECLARE
    v_user RECORD;
    v_token TEXT;
    v_refresh_token TEXT;
    v_session_id UUID;
    v_result JSON;
BEGIN
    -- Buscar usuario
    SELECT id, email, password_hash, first_name, last_name, is_active, is_verified, role
    INTO v_user
    FROM auth.users 
    WHERE email = p_email;
    
    -- Registrar intento de login
    INSERT INTO auth.login_attempts (email, ip_address, success)
    VALUES (p_email, p_ip_address::INET, false);
    
    -- Verificar si el usuario existe
    IF v_user.id IS NULL THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Invalid email or password',
            'error_code', 'INVALID_CREDENTIALS'
        );
    END IF;
    
    -- Verificar si el usuario está activo
    IF NOT v_user.is_active THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Account is deactivated',
            'error_code', 'ACCOUNT_DEACTIVATED'
        );
    END IF;
    
    -- Verificar contraseña
    IF NOT auth.verify_password(p_password, v_user.password_hash) THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Invalid email or password',
            'error_code', 'INVALID_CREDENTIALS'
        );
    END IF;
    
    -- Generar tokens
    v_token := auth.generate_token(32);
    v_refresh_token := auth.generate_token(32);
    
    -- Crear sesión
    INSERT INTO auth.user_sessions (user_id, token, refresh_token, expires_at, ip_address, user_agent)
    VALUES (
        v_user.id, 
        v_token, 
        v_refresh_token, 
        NOW() + INTERVAL '7 days',
        p_ip_address::INET,
        p_user_agent
    )
    RETURNING id INTO v_session_id;
    
    -- Actualizar último login
    UPDATE auth.users 
    SET last_login = NOW(), login_count = login_count + 1
    WHERE id = v_user.id;
    
    -- Actualizar intento de login como exitoso
    UPDATE auth.login_attempts 
    SET success = true 
    WHERE email = p_email 
    AND attempted_at = (
        SELECT MAX(attempted_at) 
        FROM auth.login_attempts 
        WHERE email = p_email
    );
    
    -- Retornar resultado exitoso
    RETURN json_build_object(
        'success', true,
        'message', 'Login successful',
        'token', v_token,
        'refresh_token', v_refresh_token,
        'expires_at', NOW() + INTERVAL '7 days',
        'user', json_build_object(
            'id', v_user.id,
            'email', v_user.email,
            'first_name', v_user.first_name,
            'last_name', v_user.last_name,
            'role', v_user.role,
            'is_verified', v_user.is_verified
        )
    );
END;
$BODY$;

ALTER FUNCTION auth.login_user(text, text, text, text)
    OWNER TO postgres;
-- FUNCTION: auth.logout_user(character varying)

-- DROP FUNCTION IF EXISTS auth.logout_user(character varying);

CREATE OR REPLACE FUNCTION auth.logout_user(
	p_token character varying)
    RETURNS json
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
BEGIN
    -- Invalidar la sesión
    UPDATE auth.user_sessions 
    SET is_active = false, updated_at = now()
    WHERE token = p_token;

    IF FOUND THEN
        RETURN json_build_object(
            'success', true,
            'message', 'Logout exitoso'
        );
    ELSE
        RETURN json_build_object(
            'success', false,
            'message', 'Sesión no encontrada'
        );
    END IF;
END;
$BODY$;

ALTER FUNCTION auth.logout_user(character varying)
    OWNER TO postgres;
-- FUNCTION: auth.logout_user(text)

-- DROP FUNCTION IF EXISTS auth.logout_user(text);

CREATE OR REPLACE FUNCTION auth.logout_user(
	p_token text)
    RETURNS json
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
BEGIN
    -- Desactivar sesión
    UPDATE auth.user_sessions 
    SET is_active = false, updated_at = NOW()
    WHERE token = p_token;
    
    IF FOUND THEN
        RETURN json_build_object(
            'success', true,
            'message', 'Logout successful'
        );
    ELSE
        RETURN json_build_object(
            'success', false,
            'message', 'Session not found',
            'error_code', 'SESSION_NOT_FOUND'
        );
    END IF;
END;
$BODY$;

ALTER FUNCTION auth.logout_user(text)
    OWNER TO postgres;
-- FUNCTION: auth.refresh_token(text)

-- DROP FUNCTION IF EXISTS auth.refresh_token(text);

CREATE OR REPLACE FUNCTION auth.refresh_token(
	p_refresh_token text)
    RETURNS json
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
DECLARE
    v_session RECORD;
    v_new_token TEXT;
    v_new_refresh_token TEXT;
BEGIN
    -- Buscar sesión por refresh token
    SELECT id, user_id, expires_at
    INTO v_session
    FROM auth.user_sessions
    WHERE refresh_token = p_refresh_token 
    AND is_active = true 
    AND expires_at > NOW();
    
    IF v_session.id IS NULL THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Invalid refresh token',
            'error_code', 'INVALID_REFRESH_TOKEN'
        );
    END IF;
    
    -- Generar nuevos tokens
    v_new_token := auth.generate_token(32);
    v_new_refresh_token := auth.generate_token(32);
    
    -- Actualizar sesión
    UPDATE auth.user_sessions
    SET token = v_new_token,
        refresh_token = v_new_refresh_token,
        expires_at = NOW() + INTERVAL '7 days',
        updated_at = NOW()
    WHERE id = v_session.id;
    
    RETURN json_build_object(
        'success', true,
        'token', v_new_token,
        'refresh_token', v_new_refresh_token,
        'expires_at', NOW() + INTERVAL '7 days'
    );
END;
$BODY$;

ALTER FUNCTION auth.refresh_token(text)
    OWNER TO postgres;
-- FUNCTION: auth.validate_session_token(character varying)

-- DROP FUNCTION IF EXISTS auth.validate_session_token(character varying);

CREATE OR REPLACE FUNCTION auth.validate_session_token(
	p_token character varying)
    RETURNS json
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
DECLARE
    v_session_record RECORD;
    v_user_record RECORD;
BEGIN
    -- Buscar sesión activa
    SELECT s.user_id, s.expires_at, s.is_active
    INTO v_session_record
    FROM auth.user_sessions s
    WHERE s.token = p_token AND s.is_active = true;

    -- Verificar si la sesión existe
    IF v_session_record.user_id IS NULL THEN
        RETURN json_build_object(
            'valid', false,
            'message', 'Sesión no encontrada'
        );
    END IF;

    -- Verificar si la sesión no ha expirado
    IF v_session_record.expires_at < now() THEN
        -- Marcar sesión como inactiva
        UPDATE auth.user_sessions 
        SET is_active = false 
        WHERE token = p_token;
        
        RETURN json_build_object(
            'valid', false,
            'message', 'Sesión expirada'
        );
    END IF;

    -- Obtener datos del usuario
    SELECT id, email, first_name, last_name, role, advisor_schema, advisor_name
    INTO v_user_record
    FROM auth.users 
    WHERE id = v_session_record.user_id AND is_active = true;

    IF v_user_record.id IS NULL THEN
        RETURN json_build_object(
            'valid', false,
            'message', 'Usuario inactivo'
        );
    END IF;

    -- Actualizar última actividad
    UPDATE auth.user_sessions 
    SET updated_at = now() 
    WHERE token = p_token;

    RETURN json_build_object(
        'valid', true,
        'user', json_build_object(
            'id', v_user_record.id,
            'email', v_user_record.email,
            'first_name', v_user_record.first_name,
            'last_name', v_user_record.last_name,
            'role', v_user_record.role,
            'advisor_schema', v_user_record.advisor_schema,
            'advisor_name', v_user_record.advisor_name
        )
    );

EXCEPTION
    WHEN OTHERS THEN
        RETURN json_build_object(
            'valid', false,
            'message', 'Error interno del servidor'
        );
END;
$BODY$;

ALTER FUNCTION auth.validate_session_token(character varying)
    OWNER TO postgres;
-- FUNCTION: auth.validate_token(text)

-- DROP FUNCTION IF EXISTS auth.validate_token(text);

CREATE OR REPLACE FUNCTION auth.validate_token(
	p_token text)
    RETURNS json
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
DECLARE
    v_session RECORD;
    v_user RECORD;
BEGIN
    -- Buscar sesión activa
    SELECT s.id, s.user_id, s.expires_at, s.is_active
    INTO v_session
    FROM auth.user_sessions s
    WHERE s.token = p_token 
    AND s.is_active = true 
    AND s.expires_at > NOW();
    
    -- Verificar si la sesión existe y es válida
    IF v_session.id IS NULL THEN
        RETURN json_build_object(
            'valid', false,
            'message', 'Invalid or expired token',
            'error_code', 'INVALID_TOKEN'
        );
    END IF;
    
    -- Obtener datos del usuario
    SELECT id, email, first_name, last_name, role, is_active
    INTO v_user
    FROM auth.users
    WHERE id = v_session.user_id AND is_active = true;
    
    IF v_user.id IS NULL THEN
        RETURN json_build_object(
            'valid', false,
            'message', 'User not found or deactivated',
            'error_code', 'USER_NOT_FOUND'
        );
    END IF;
    
    -- Retornar usuario válido
    RETURN json_build_object(
        'valid', true,
        'user', json_build_object(
            'id', v_user.id,
            'email', v_user.email,
            'first_name', v_user.first_name,
            'last_name', v_user.last_name,
            'role', v_user.role
        ),
        'session_expires', v_session.expires_at
    );
END;
$BODY$;

ALTER FUNCTION auth.validate_token(text)
    OWNER TO postgres;
-- FUNCTION: auth.verify_password(text, text)

-- DROP FUNCTION IF EXISTS auth.verify_password(text, text);

CREATE OR REPLACE FUNCTION auth.verify_password(
	password text,
	hash text)
    RETURNS boolean
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE SECURITY DEFINER PARALLEL UNSAFE
AS $BODY$
BEGIN
    RETURN (crypt(password, hash) = hash);
END;
$BODY$;

ALTER FUNCTION auth.verify_password(text, text)
    OWNER TO postgres;
-- View: auth.active_sessions

-- DROP VIEW auth.active_sessions;

CREATE OR REPLACE VIEW auth.active_sessions
 AS
 SELECT u.email,
    u.first_name,
    u.last_name,
    u.advisor_name,
    s.created_at AS login_time,
    s.expires_at,
    s.ip_address,
    s.user_agent,
    EXTRACT(epoch FROM s.expires_at - now()) / 3600::numeric AS hours_remaining
   FROM auth.user_sessions s
     JOIN auth.users u ON u.id = s.user_id
  WHERE s.is_active = true AND s.expires_at > now()
  ORDER BY s.created_at DESC;

ALTER TABLE auth.active_sessions
    OWNER TO postgres;



