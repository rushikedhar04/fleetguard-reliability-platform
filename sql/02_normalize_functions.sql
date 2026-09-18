-- Normalization functions used to reconcile the three different ID schemes
-- against the asset registry. Each transactional system formats the same
-- underlying identifier differently (case, prefixes, dashes); these functions
-- collapse that noise into one canonical key per ID type so a join is
-- possible. This is the "trickiest matching logic" piece: the registry does
-- not hand out a plain join key, one has to be derived.

CREATE OR REPLACE FUNCTION normalize_vin_or_unit(raw TEXT) RETURNS TEXT AS $$
DECLARE
    cleaned TEXT;
BEGIN
    IF raw IS NULL THEN RETURN NULL; END IF;
    cleaned := upper(trim(raw));
    IF cleaned LIKE 'UNIT%' THEN
        -- normalize "unit1652" / "UNIT-1652" / "unit-1652" -> "UNIT-1652"
        RETURN 'UNIT-' || regexp_replace(cleaned, '[^0-9]', '', 'g');
    END IF;
    -- strip an optional VIN- prefix, leaving the bare 17-char VIN
    RETURN regexp_replace(cleaned, '^VIN-', '');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION normalize_device_id(raw TEXT) RETURNS TEXT AS $$
DECLARE
    digits TEXT;
BEGIN
    IF raw IS NULL THEN RETURN NULL; END IF;
    digits := regexp_replace(upper(trim(raw)), '[^0-9]', '', 'g');
    IF digits = '' THEN RETURN NULL; END IF;
    RETURN 'DEV-' || lpad(digits, 6, '0');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION normalize_asset_serial(raw TEXT) RETURNS TEXT AS $$
DECLARE
    cleaned TEXT;
BEGIN
    IF raw IS NULL THEN RETURN NULL; END IF;
    cleaned := upper(trim(raw));
    IF cleaned LIKE 'SN-%' THEN RETURN cleaned; END IF;
    RETURN 'SN-' || cleaned;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
