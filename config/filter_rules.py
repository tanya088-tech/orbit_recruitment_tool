"""Editable rule lists for the Phase 2 filters. No code changes needed to tune them.

Every pattern is a regular expression matched case-insensitively with word boundaries
(unless noted). The classification is deliberately only *potential*: keyword evidence,
never proof that a company is a GCC or a BFSI firm.
"""

# --------------------------------------------------------------------------------------
# BFSI (Banking, Financial Services, Insurance)
# --------------------------------------------------------------------------------------
# Matched against LinkedIn's "Industries" value, e.g. "Financial Services", "Insurance".
BFSI_INDUSTRY_PATTERNS = [
    r"\bbank(s|ing)?\b", r"\bfinancial\b", r"\bfinance\b", r"\binsur\w*",
    r"\binvestment (banking|management)\b", r"\bcapital markets?\b",
    r"\bventure capital\b", r"\bprivate equity\b", r"\bcredit\b", r"\bfin-?tech\b",
    r"\bpayments?\b", r"\bwealth\b", r"\basset management\b", r"\bpension\b",
    r"\bsecurities\b", r"\bmortgage\b", r"\bloans?\b", r"\blending\b",
]

# Matched against the company name.
BFSI_COMPANY_PATTERNS = [
    r"\bbank(s|ing)?\b", r"\bfinanc(e|ial|ials)\b", r"\bfinserv\w*", r"\bfincorp\b",
    r"\binsurance\b", r"\bassurance\b", r"\binsurer\b", r"\bsecurities\b",
    r"\bcapital\b", r"\bmutual funds?\b", r"\basset management\b", r"\bwealth\b",
    r"\bpayments?\b", r"\blending\b", r"\bcredit\b", r"\bfin-?tech\b", r"\bnbfc\b",
]

# Matched against the job title.
BFSI_TITLE_PATTERNS = [
    r"\bbank(s|ing|er|ers)?\b", r"\binvestment bank\w*", r"\bwealth management\b",
    r"\basset management\b", r"\bcapital markets?\b", r"\binsurance\b",
    r"\bunderwrit\w*", r"\bactuar\w*", r"\bcredit (risk|analyst|manager|underwriter|operations)\b",
    r"\blending\b", r"\bloans?\b", r"\bmortgages?\b", r"\bnbfc\b", r"\bfin-?tech\b",
    r"\bpayments?\b", r"\btreasury\b", r"\btrade finance\b", r"\bmutual funds?\b",
    r"\bprivate equity\b", r"\bequity research\b", r"\bfixed income\b",
    r"\bfinancial (services|crime|institutions?)\b", r"\banti[- ]money laundering\b",
    r"\baml\b", r"\bkyc\b", r"\bsecurities\b", r"\b(retail|corporate|private) banking\b",
]

# Matched against the description. Weak on their own: a job passes on description
# evidence only if at least BFSI_DESCRIPTION_MIN_DISTINCT *different* phrases appear.
BFSI_DESCRIPTION_PATTERNS = [
    r"\bbank(s|ing)?\b", r"\bfinancial services\b", r"\bfinancial institutions?\b",
    r"\binsurance\b", r"\bfin-?tech\b", r"\bnbfc\b", r"\bpayments?\b", r"\blending\b",
    r"\binvestment bank(s|ing|er|ers)?\b", r"\bcapital markets?\b",
    r"\basset management\b", r"\bwealth management\b", r"\bmutual funds?\b",
    r"\bcredit (risk|cards?)\b", r"\bbrokerage\b", r"\bunderwriting\b", r"\bloans?\b",
    r"\bmortgages?\b",
]
BFSI_DESCRIPTION_MIN_DISTINCT = 3

# --------------------------------------------------------------------------------------
# GCC (Global Capability Centre / captive / shared services)
# --------------------------------------------------------------------------------------
# STRONG: explicit wording anywhere (company, title, description).
GCC_EXPLICIT_PATTERNS = [
    r"\bglobal capabilit(y|ies) cent(er|re)s?\b",
    r"\bcaptive (cent(er|re)s?|units?|operations?|facilit(y|ies)|set-?ups?|entit(y|ies))\b",
    r"\bshared services?\b",
    r"\bglobal business services\b",
    r"\bglobal in-?house cent(er|re)s?\b",
    r"\bglobal delivery cent(er|re)s?\b",
]

# "GCC" as a bare uppercase token is only counted if it is NOT near these words
# (GCC = Gulf Cooperation Council, or the GNU compiler).
GCC_TOKEN_NON_CAPABILITY_CONTEXT = (
    r"countries|region|states|council|cooperation|gulf|\buae\b|dubai|abu dhabi|saudi|"
    r"\bksa\b|qatar|kuwait|oman|bahrain|middle east|\bmena\b|"
    r"compiler|clang|\bgdb\b|toolchain|c\+\+|linux|makefile|llvm"
)

# Technology / operations / delivery centre wording. In the company name or job title this
# alone is a (weaker) signal; in the description it only counts together with a
# multinational cue below.
GCC_CENTER_PATTERNS = [
    r"\b(technology|tech|operations?|delivery|engineering|development|innovation|analytics|digital|service|support|capability) (cent(er|re)s?|hubs?)\b",
    r"\bglobal services\b",
    r"\bglobal (operations|technology|delivery|business) (cent(er|re)s?|services|hubs?)\b",
    r"\bcent(er|re)s? of excellence\b",
]

# Company-NAME-only wording typical of captive/GCC entities (e.g. 'XYZ Global Tech').
GCC_COMPANY_ONLY_PATTERNS = [
    r"\bglobal tech(nology)?\b", r"\bgbs\b", r"\bglobal solutions? cent(er|re)s?\b",
]

# Cues that the employer is a multinational with an Indian centre.
GCC_MNC_CUE_PATTERNS = [
    r"\bmulti-?national\b",
    r"\bglobal (organi[sz]ation|firm|company|enterprise|leader|network|bank|footprint|presence|teams?)\b",
    r"\bheadquartered in\b", r"\bworldwide\b", r"\bfortune (100|500|1000)\b",
    r"\bparent company\b", r"\bacross the (globe|world)\b", r"\b\d{2,3}\+? countries\b",
]

# --------------------------------------------------------------------------------------
# Employment type  (LinkedIn value -> allowed output)
# --------------------------------------------------------------------------------------
EMPLOYMENT_PERMANENT = {"full time", "permanent", "regular"}
EMPLOYMENT_CONTRACT = {"contract", "contractor", "contract based", "fixed term contract"}
EMPLOYMENT_EXCLUDED = {
    "part time", "internship", "intern", "temporary", "volunteer", "other",
    "per diem", "seasonal", "apprenticeship", "casual",
}

# --------------------------------------------------------------------------------------
# India location recognition
# --------------------------------------------------------------------------------------
INDIA_CITIES = {
    # metros & NCR
    "bengaluru", "bangalore", "bengaluru rural", "hyderabad", "secunderabad", "mumbai",
    "bombay", "navi mumbai", "thane", "pune", "pimpri chinchwad", "chennai", "madras",
    "delhi", "new delhi", "delhi ncr", "ncr", "national capital region", "gurgaon",
    "gurugram", "noida", "greater noida", "ghaziabad", "faridabad", "kolkata", "calcutta",
    # other major cities
    "ahmedabad", "gandhinagar", "surat", "vadodara", "baroda", "rajkot", "jaipur", "jodhpur",
    "udaipur", "kota", "lucknow", "kanpur", "agra", "varanasi", "prayagraj", "allahabad",
    "meerut", "nagpur", "nashik", "aurangabad", "kolhapur", "solapur", "indore", "bhopal",
    "jabalpur", "gwalior", "kochi", "cochin", "ernakulam", "thiruvananthapuram",
    "trivandrum", "kozhikode", "calicut", "thrissur", "coimbatore", "madurai", "tiruchirappalli",
    "trichy", "salem", "hosur", "vellore", "mysuru", "mysore", "mangaluru", "mangalore",
    "hubli", "hubballi", "dharwad", "belagavi", "belgaum", "visakhapatnam", "vizag",
    "vijayawada", "guntur", "tirupati", "warangal", "chandigarh", "mohali", "panchkula",
    "ludhiana", "amritsar", "jalandhar", "dehradun", "haridwar", "bhubaneswar", "cuttack",
    "patna", "ranchi", "jamshedpur", "raipur", "bhilai", "guwahati", "siliguri", "imphal",
    "shillong", "panaji", "margao", "pondicherry", "puducherry", "srinagar", "jammu",
}
INDIA_STATES = {
    "karnataka", "maharashtra", "telangana", "tamil nadu", "kerala", "andhra pradesh",
    "gujarat", "rajasthan", "uttar pradesh", "haryana", "punjab", "west bengal",
    "madhya pradesh", "odisha", "orissa", "bihar", "jharkhand", "chhattisgarh",
    "uttarakhand", "himachal pradesh", "assam", "goa", "chandigarh", "puducherry",
    "jammu and kashmir", "meghalaya", "manipur", "tripura", "nagaland", "sikkim",
}

# If any of these appear (and the word "India" does not), the location is NOT India -
# this stops e.g. "Hyderabad, Sindh, Pakistan" or "Salem, Oregon" being accepted.
FOREIGN_COUNTRIES = {
    "united states", "usa", "u s a", "u s", "us", "united kingdom", "uk", "england", "scotland",
    "pakistan", "bangladesh", "sri lanka", "nepal", "bhutan", "afghanistan", "singapore",
    "united arab emirates", "uae", "dubai", "abu dhabi", "saudi arabia", "qatar", "kuwait",
    "bahrain", "oman", "canada", "australia", "new zealand", "germany", "france", "ireland",
    "netherlands", "poland", "spain", "italy", "switzerland", "sweden", "romania", "hungary",
    "czechia", "czech republic", "portugal", "belgium", "philippines", "malaysia", "indonesia",
    "thailand", "vietnam", "japan", "china", "hong kong", "taiwan", "south korea", "korea",
    "south africa", "egypt", "nigeria", "kenya", "brazil", "mexico", "argentina", "colombia",
    "chile", "israel", "turkey", "russia", "ukraine",
}
FOREIGN_PLACES = {   # foreign regions / cities that share names with Indian ones
    "sindh", "karachi", "lahore", "islamabad", "dhaka", "colombo", "kathmandu",
    "khyber pakhtunkhwa", "balochistan",
}
US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming",
}
