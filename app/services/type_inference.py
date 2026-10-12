"""
Semantic Data Type Inference Engine
Infers meaningful data types from Glue/Athena metadata + column names + sample values.

Problem: Athena/Glue types are too coarse (everything is "string" or "bigint").
Solution: Classify each column into a semantic type that helps FK/PK discovery.

Semantic Types:
  - identifier      : primary key / foreign key ID (customer_id, id, pk)
  - code            : short code (cod_marque, country_code, status_code)
  - reference       : reference/lookup value (ref_dealer, num_contrat)
  - text            : free-form text (name, description, label, comment)
  - date            : date or datetime (date_creation, created_at, dat_livraison)
  - timestamp       : timestamp/epoch (updated_at, ts_event)
  - amount          : monetary amount (mnt_facture, prix_ttc, total_amount)
  - quantity         : numeric count (qty, nombre, count)
  - numeric         : generic number (score, rating, percentage)
  - boolean         : true/false flag (is_active, flag_deleted, has_email)
  - email           : email address
  - phone           : phone number
  - url             : URL/URI
  - enum            : low-cardinality categorical (status, type, category, gender)
  - unknown         : cannot determine
"""

import re
from collections import Counter

# ═══════════════════════════════════════════════════════════
# COLUMN-NAME-BASED INFERENCE (always available)
# ═══════════════════════════════════════════════════════════

# Priority-ordered patterns: first match wins
_NAME_PATTERNS = [
    # Identifiers — FK/PK
    (re.compile(r"^(id|pk|key)$", re.I), "identifier"),
    (re.compile(r"(_id|_pk|_key|_fk)$", re.I), "identifier"),
    (re.compile(r"^(fk_|pk_|id_)", re.I), "identifier"),
    (re.compile(r"^(ident_|identifiant)", re.I), "identifier"),
    (re.compile(r"_ident$", re.I), "identifier"),

    # Codes — short lookup keys
    (re.compile(r"^(cod_|code_|cd_)", re.I), "code"),
    (re.compile(r"(_code|_cod|_cd)$", re.I), "code"),
    (re.compile(r"^(country_code|currency_code|lang_code|postal_code|zip_code)$", re.I), "code"),

    # References — lookup / numbering
    (re.compile(r"^(ref_|num_|numero_|no_|nbr_)", re.I), "reference"),
    (re.compile(r"(_ref|_num|_numero|_no)$", re.I), "reference"),
    (re.compile(r"^(vin|vin_(number|num|no)|chassis|chassis_(number|num|no)|num_chassis|immatriculation|plaque|siret|siren|nir)$", re.I), "reference"),

    # Booleans — flags
    (re.compile(r"^(is_|has_|was_|can_|should_|flag_|flg_|ind_)", re.I), "boolean"),
    (re.compile(r"(_flag|_flg|_ind|_yn|_bool|_active|_enabled|_deleted)$", re.I), "boolean"),

    # Dates
    (re.compile(r"^(dat_|date_|dt_)", re.I), "date"),
    (re.compile(r"(_date|_dat|_dt)$", re.I), "date"),
    (re.compile(r"^(date|created_at|updated_at|deleted_at|start_date|end_date|"
                r"birth_date|date_naissance|date_creation|date_modification|"
                r"date_debut|date_fin|date_livraison|date_commande|"
                r"date_facture|date_immatriculation)$", re.I), "date"),

    # Timestamps
    (re.compile(r"^(ts_|timestamp_)", re.I), "timestamp"),
    (re.compile(r"(_ts|_timestamp|_time)$", re.I), "timestamp"),
    (re.compile(r"^(timestamp|created_timestamp|modified_time)$", re.I), "timestamp"),

    # Amounts — monetary
    (re.compile(r"^(mnt_|montant_|prix_|price_|amount_|amt_|cost_|total_|fee_|tax_)", re.I), "amount"),
    (re.compile(r"(_amount|_amt|_mnt|_montant|_prix|_price|_cost|_total|_fee|_tax|"
                r"_ttc|_ht|_tva)$", re.I), "amount"),

    # Quantities
    (re.compile(r"^(qty_|qte_|quantite_|nombre_|nbr_|count_|nb_)", re.I), "quantity"),
    (re.compile(r"(_qty|_qte|_quantite|_count|_nombre|_nb)$", re.I), "quantity"),

    # Text — names, labels, descriptions
    (re.compile(r"^(nom_|name_|lib_|libelle_|label_|desc_|description_|titre_|title_|"
                r"prenom_|raison_|adresse_|address_|ville_|city_|rue_|street_|"
                r"comment_|remarque_|note_)", re.I), "text"),
    (re.compile(r"(_name|_nom|_lib|_libelle|_label|_desc|_description|_title|_titre|"
                r"_prenom|_adresse|_address|_ville|_city|_comment|_remarque|_note)$", re.I), "text"),
    (re.compile(r"^(name|nom|prenom|firstname|lastname|email_address|"
                r"description|label|title|comment|note|adresse|address|"
                r"ville|city|pays|country|region)$", re.I), "text"),

    # Email
    (re.compile(r"(email|e_mail|courriel|mail_address)", re.I), "email"),

    # Phone
    (re.compile(r"(phone|telephone|tel_|mobile|fax|portable)", re.I), "phone"),

    # URL
    (re.compile(r"(url|uri|website|lien|link|href)", re.I), "url"),

    # Enums — type/status/category columns (low cardinality expected)
    (re.compile(r"^(type_|typ_|status_|statut_|state_|category_|cat_|genre_|"
                r"civilite_|mode_|canal_|channel_|segment_|class_)", re.I), "enum"),
    (re.compile(r"(_type|_typ|_status|_statut|_state|_category|_cat|_genre|"
                r"_civilite|_mode|_canal|_channel|_segment|_class)$", re.I), "enum"),
    (re.compile(r"^(type|status|statut|state|category|genre|civilite|gender|"
                r"marital_status|payment_method|source|origin)$", re.I), "enum"),
]


def infer_type_from_name(col_name: str) -> str:
    """Infer semantic data type from column name alone. Always available."""
    cn = col_name.strip()
    for pattern, sem_type in _NAME_PATTERNS:
        if pattern.search(cn):
            return sem_type
    return "unknown"


# ═══════════════════════════════════════════════════════════
# GLUE/ATHENA DDL TYPE MAPPING
# ═══════════════════════════════════════════════════════════

_DDL_TYPE_MAP = {
    # Integers → likely identifiers or quantities
    "int": "numeric",
    "integer": "numeric",
    "bigint": "numeric",
    "smallint": "numeric",
    "tinyint": "numeric",

    # Floats → likely amounts or metrics
    "float": "numeric",
    "double": "numeric",
    "decimal": "numeric",
    "real": "numeric",

    # Booleans
    "boolean": "boolean",
    "bool": "boolean",

    # Dates & timestamps
    "date": "date",
    "timestamp": "timestamp",
    "datetime": "timestamp",

    # Strings → unknown (need further analysis)
    "string": "unknown",
    "varchar": "unknown",
    "char": "unknown",

    # Complex types
    "array": "unknown",
    "map": "unknown",
    "struct": "unknown",
    "binary": "unknown",
}


def _map_ddl_type(ddl_type: str) -> str:
    """Map a Glue/Athena DDL type to a coarse semantic category."""
    dt = ddl_type.lower().strip()
    # Handle parameterized types: decimal(10,2), varchar(255)
    base = dt.split("(")[0].strip()
    return _DDL_TYPE_MAP.get(base, "unknown")


# ═══════════════════════════════════════════════════════════
# SAMPLE-VALUE-BASED INFERENCE (when sample data available)
# ═══════════════════════════════════════════════════════════

_DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),                    # 2024-01-15
    re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"),     # 2024-01-15 10:30:00
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),                    # 15/01/2024 or 01/15/2024
    re.compile(r"^\d{2}-\d{2}-\d{4}$"),                    # 15-01-2024
    re.compile(r"^\d{8}$"),                                 # 20240115
]

_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_PHONE_PATTERN = re.compile(r"^[\+]?[\d\s\-\.\(\)]{7,20}$")
_URL_PATTERN = re.compile(r"^https?://", re.I)
_BOOL_VALUES = {"true", "false", "yes", "no", "y", "n", "0", "1", "oui", "non", "t", "f"}
_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def infer_type_from_values(values: list[str]) -> str:
    """Infer semantic data type from sample values.

    Args:
        values: list of non-null string values from sample rows
    Returns:
        semantic type string
    """
    if not values:
        return "unknown"

    # Filter out empty/null-like values
    clean = [v.strip() for v in values if v and str(v).strip()
             and str(v).strip().lower() not in ("none", "null", "nan", "")]
    if not clean:
        return "unknown"

    n = len(clean)
    votes = Counter()

    for v in clean:
        sv = str(v)

        # UUID → identifier
        if _UUID_PATTERN.match(sv):
            votes["identifier"] += 1
            continue

        # Boolean
        if sv.lower() in _BOOL_VALUES:
            votes["boolean"] += 1
            continue

        # Email
        if _EMAIL_PATTERN.match(sv):
            votes["email"] += 1
            continue

        # URL
        if _URL_PATTERN.match(sv):
            votes["url"] += 1
            continue

        # Phone
        if _PHONE_PATTERN.match(sv) and not sv.replace(".", "").replace("-", "").replace(" ", "").isdigit():
            votes["phone"] += 1
            continue

        # Date
        if any(p.match(sv) for p in _DATE_PATTERNS):
            votes["date"] += 1
            continue

        # Numeric (integer)
        try:
            int_val = int(sv)
            votes["numeric"] += 1
            continue
        except (ValueError, OverflowError):
            pass

        # Numeric (float/decimal)
        try:
            float_val = float(sv.replace(",", "."))
            votes["numeric"] += 1
            continue
        except (ValueError, OverflowError):
            pass

        # Text (long or contains spaces)
        if len(sv) > 50 or " " in sv:
            votes["text"] += 1
            continue

        # Short alphanumeric → code or enum
        if len(sv) <= 10 and sv.isalnum():
            votes["code"] += 1
        else:
            votes["text"] += 1

    if not votes:
        return "unknown"

    # Return the most common type (majority vote)
    best_type, best_count = votes.most_common(1)[0]

    # Additional heuristic: low distinct-count strings → enum
    if best_type in ("code", "text") and len(set(clean)) <= max(3, n * 0.3):
        return "enum"

    return best_type


# ═══════════════════════════════════════════════════════════
# COMBINED INFERENCE — merge all signals
# ═══════════════════════════════════════════════════════════

# Priority when signals disagree: name > values > ddl
# (column naming conventions in enterprise systems are very reliable)

def infer_semantic_type(col_name: str, ddl_type: str = "string",
                        sample_values: list[str] = None) -> str:
    """
    Combine all signals to infer the best semantic data type.

    Args:
        col_name: column name (e.g. "customer_id", "dat_livraison")
        ddl_type: Glue/Athena DDL type (e.g. "string", "bigint")
        sample_values: optional list of sample value strings

    Returns:
        semantic type string
    """
    name_type = infer_type_from_name(col_name)
    ddl_sem = _map_ddl_type(ddl_type)
    val_type = infer_type_from_values(sample_values) if sample_values else "unknown"

    # If name gives a strong signal, trust it
    if name_type != "unknown":
        # Cross-validate: if DDL says boolean but name says identifier, trust name
        # Exception: if name says "numeric" but values clearly show dates, trust values
        if name_type == "numeric" and val_type == "date":
            return "date"
        return name_type

    # If values give a signal, use it
    if val_type != "unknown":
        # Refine: if values are numeric and DDL is bigint → could be identifier
        if val_type == "numeric" and ddl_sem == "numeric":
            # Check if the column name hints at being an ID even if not caught above
            cn = col_name.lower()
            if any(cn.endswith(s) for s in ("_id", "_pk", "_key", "_fk")):
                return "identifier"
        return val_type

    # Fall back to DDL type
    if ddl_sem != "unknown":
        return ddl_sem

    return "unknown"


# ═══════════════════════════════════════════════════════════
# BATCH ENRICHMENT — enrich all columns in a dictionary
# ═══════════════════════════════════════════════════════════

def enrich_dictionary_types(dictionary: dict, sample_data: dict = None) -> dict:
    """
    Enrich every column in the data dictionary with a `semantic_type` field.

    Args:
        dictionary: {db: {table: {columns: [{name, type, ...}]}}}
        sample_data: optional {db.table: {columns: [...], rows: [...]}}

    Returns:
        The same dictionary with `semantic_type` added to each column.
    """
    sample_data = sample_data or {}

    for db, tables in dictionary.items():
        for tbl_name, tbl_info in tables.items():
            tbl_key = f"{db}.{tbl_name}"
            tbl_sample = sample_data.get(tbl_key, {})
            sample_rows = tbl_sample.get("rows", [])

            for col in tbl_info.get("columns", []):
                col_name = col.get("name", "")
                if not col_name:
                    continue  # Skip corrupt entries without a name
                ddl_type = col.get("type", "string")

                # Extract sample values for this column
                col_values = []
                for row in sample_rows:
                    v = row.get(col_name)
                    if v is not None:
                        col_values.append(str(v))

                sem_type = infer_semantic_type(col_name, ddl_type, col_values or None)
                col["semantic_type"] = sem_type

    return dictionary


# ═══════════════════════════════════════════════════════════
# TYPE COMPATIBILITY CHECK — for FK matching
# ═══════════════════════════════════════════════════════════

# Types that can form FK relationships (referential types)
_REFERENTIAL_TYPES = {"identifier", "code", "reference", "numeric"}

# Types that should NOT match as FKs
_NON_FK_TYPES = {"text", "date", "timestamp", "amount", "boolean", "email",
                  "phone", "url", "quantity"}


def are_types_fk_compatible(type_a: str, type_b: str) -> bool:
    """
    Check if two semantic types are compatible for a FK relationship.

    E.g. identifier ↔ identifier = True
         code ↔ code = True
         text ↔ text = False (two name columns aren't FKs)
         date ↔ date = False (two date columns aren't FKs)
    """
    # Both must be referential types
    if type_a in _NON_FK_TYPES or type_b in _NON_FK_TYPES:
        return False

    # At least one must be clearly referential
    if type_a in _REFERENTIAL_TYPES or type_b in _REFERENTIAL_TYPES:
        return True

    # Both unknown → allow (no signal to block)
    if type_a == "unknown" and type_b == "unknown":
        return True

    # Enum ↔ referential is OK (e.g. status code as FK)
    if (type_a == "enum" and type_b in _REFERENTIAL_TYPES) or \
       (type_b == "enum" and type_a in _REFERENTIAL_TYPES):
        return True

    return False


def get_type_confidence_boost(type_a: str, type_b: str) -> float:
    """
    Return a confidence boost/penalty based on type compatibility.

    Returns:
        +0.15 if types are perfectly compatible (id ↔ id)
        +0.05 if types are loosely compatible (code ↔ reference)
        -0.20 if types are incompatible (text ↔ text, date ↔ date)
         0.00 if unknown
    """
    if type_a == type_b:
        if type_a in ("identifier", "code", "reference"):
            return 0.15  # Strong: same referential type
        if type_a in _NON_FK_TYPES:
            return -0.20  # Penalty: matching text/date/amount is NOT an FK
        return 0.0

    if are_types_fk_compatible(type_a, type_b):
        return 0.05  # Mild boost for compatible types

    if type_a in _NON_FK_TYPES or type_b in _NON_FK_TYPES:
        return -0.20  # Penalty: non-referential type

    return 0.0
