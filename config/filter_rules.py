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
# STRICT eligibility rules (used by processing/classifier.py)
# --------------------------------------------------------------------------------------
# A job is kept only when the EMPLOYER (or, for BFSI, the job itself) clearly qualifies.
# A generic word in the job title (HR, recruiter, talent acquisition, manager, analyst,
# operations, technology, finance ...) is never evidence on its own.

# Employer is a recruitment / staffing business -> never an eligible employer.
STAFFING_INDUSTRY_PATTERNS = [
    r"\bstaffing\b", r"\brecruit\w*", r"\bexecutive search\b", r"\bhuman resources?\b",
    r"\bmanpower\b", r"\bplacement\b",
]
STAFFING_COMPANY_PATTERNS = [
    r"\bstaffing\b", r"\brecruit\w*", r"\bmanpower\b", r"\bplacements?\b", r"\bheadhunt\w*",
    r"\bexecutive search\b", r"\bresourcing\b", r"\b(hr|human resources?|human capital) (solutions?|services|consult\w*|partners|advisors?)\b",
    r"\btalent (solutions?|acquisition|partners?|management|hub|search|connect)\b", r"\bconsultants\b",
]
# Description wording of an agency hiring for somebody else (the real employer is not stated).
HIRING_FOR_CLIENT_PATTERNS = [
    r"\bhiring for (a|an|our|one of our)\b[^.\n]{0,40}\bclient\b", r"\brecruiting for (a|an|our)\b[^.\n]{0,40}\bclient\b",
    r"\bon behalf of (a|an|our)\b[^.\n]{0,40}\bclient\b", r"\bour client\b(?=[^.\n]{0,30}\b(is|are|a|an)\b)",
    r"\bconfidential client\b", r"\bleading (mnc|gcc|bank) client\b",
]
# The company name says nothing about the employer.
UNCLEAR_COMPANY_NAMES = {"confidential", "confidential company", "undisclosed", "not disclosed", "anonymous", "hidden"}
# Generic placeholders used instead of a company name ("MNC", "Leading MNC"): the employer is unknown, so these are never
# eligible, whatever industry the listing states.
PLACEHOLDER_COMPANY_NAMES = {"mnc", "leading mnc", "top mnc", "reputed mnc", "well known mnc", "global mnc", "mnc company",
                             "mnc client", "multinational company", "leading company", "reputed company", "reputed client"}

# Industry labels (LinkedIn "Industries" / Naukri "Industry Type") that clearly mean BFSI.
BFSI_STRICT_INDUSTRY_PATTERNS = [
    r"\bbank(s|ing)?\b", r"\bfinancial (services?|institutions?)\b", r"\binsur\w*",
    r"\binvestment (banking|management)\b", r"\bcapital markets?\b", r"\bventure capital\b",
    r"\bprivate equity\b", r"\bcredit (intermediation|cards?)\b", r"\bfin-?tech\b", r"\bpayments?\b",
    r"\bwealth\b", r"\basset management\b", r"\bpension\b", r"\bsecurities\b", r"\bmortgage\b",
    r"\bloans?\b", r"\blending\b", r"\bnbfc\b", r"\bmutual funds?\b", r"\bbrokerage\b",
]
# Company-name words that clearly mean a BFSI business.
BFSI_STRICT_COMPANY_PATTERNS = [
    r"\bbank(s|ing)?\b", r"\bfinancial\b", r"\bfinserv\w*", r"\bfincorp\b", r"\bfinance (ltd|limited|corp\w*|company|india|services)\b",
    r"\binsurance\b", r"\bassurance\b", r"\binsurer\b", r"\bsecurities\b", r"\bmutual funds?\b",
    r"\basset management\b", r"\bwealth\b", r"\bfin-?tech\b", r"\bnbfc\b", r"\bhousing finance\b",
]
# "Capital" in a name is ambiguous (Capital Hospital) -> counts only when no other industry is known.
BFSI_AMBIGUOUS_COMPANY_PATTERNS = [r"\bcapital\b", r"\bpayments?\b", r"\bcredit\b", r"\blending\b"]
# Unmistakable BFSI names (used only when the source gives no industry or a BFSI one).
KNOWN_BFSI_EMPLOYERS = [
    r"\bhdfc\b", r"\bicici\b", r"\bkotak\b", r"\bsbi\b", r"\bidfc\b", r"\bjp ?morgan\b", r"\bgoldman sachs\b",
    r"\bmorgan stanley\b", r"\bciti(group|bank)?\b", r"\bhsbc\b", r"\bbarclays\b", r"\bstandard chartered\b",
    r"\bwells fargo\b", r"\bamerican express\b", r"\bmastercard\b", r"\bpaypal\b", r"\bbnp paribas\b",
    r"\bubs\b", r"\bcredit suisse\b", r"\bstate street\b", r"\bblackrock\b", r"\bnatwest\b", r"\bnomura\b",
    r"\bbajaj (finance|finserv|allianz)\b", r"\bmax life\b", r"\blic of india\b", r"\ballianz\b", r"\baxa\b",
]
# LinkedIn company-page address (/company/<slug>) containing a BFSI word. Counts as employer evidence only together with BFSI
# wording in the description, and not when the stated industry is one of the tech / services industries below.
BFSI_PAGE_SLUG_PATTERNS = [
    r"bank", r"insur", r"assurance", r"financ", r"finserv", r"fincorp", r"securities", r"mutual-?fund", r"wealth", r"nbfc",
]
BFSI_PAGE_SLUG_MIN_DESCRIPTION_PHRASES = 1
PAGE_SLUG_BLOCKING_INDUSTRY_PATTERNS = [
    r"software", r"information technology", r"\bit services\b", r"technology", r"consulting", r"education", r"training",
    r"staffing", r"recruit", r"human resources", r"internet",
]
# Employers whose stated industry is clearly healthcare / pharma. A BFSI-sounding job title (underwriter, claims, mortgage ...)
# plus wording in the posting is NOT enough to treat such an employer's opening as BFSI - the employer itself must show BFSI/GCC evidence.
TITLE_ROUTE_BLOCKING_INDUSTRY_PATTERNS = [
    r"health\w*", r"pharma\w*", r"medical", r"hospital", r"life sciences?", r"biotech\w*", r"clinical", r"diagnostic\w*", r"medicine",
    r"nursing", r"wellness",
]
# Job-title terms that are specific to BFSI work. Generic words (bank, payments, treasury, finance) are
# deliberately absent. They count only for non-HR titles and only when the employer is not clearly another industry.
BFSI_STRICT_TITLE_PATTERNS = [
    r"\bunderwrit\w*", r"\bactuar\w*", r"\binvestment bank\w*", r"\bwealth management\b", r"\basset management\b",
    r"\bcapital markets?\b", r"\bcredit (risk|analyst|underwriter|operations)\b", r"\bmortgages?\b",
    r"\bloan (officer|processing|operations|origination)\b", r"\bnbfc\b", r"\btrade finance\b", r"\bmutual funds?\b",
    r"\bprivate equity\b", r"\bequity research\b", r"\bfixed income\b", r"\bfinancial crime\b",
    r"\banti[- ]money laundering\b", r"\baml\b", r"\bkyc\b", r"\b(retail|corporate|private) banking\b",
    r"\binsurance (claims?|operations|sales|advisor)\b", r"\bclaims (adjuster|processing)\b", r"\bsecurities\b",
]
# Titles of HR / recruiting work: these never qualify a job through the title.
HR_TITLE_PATTERNS = [
    r"\brecruit\w*", r"\btalent acquisition\b", r"\btalent partner\b", r"\bsourcer\b", r"\bheadhunt\w*",
    r"\bhuman resources?\b", r"\bhr\b", r"\bpeople (partner|operations|business partner)\b", r"\bstaffing\b",
    r"\bonboarding\b", r"\bpayroll\b", r"\bhrbp\b",
]
# When the source lists a different, known industry, a title term alone is not enough.
OTHER_INDUSTRY_NEEDS_DESCRIPTION_PHRASES = 3
# A BFSI word in the company name (Bank, Finance, Insurance ...) or a BFSI-specific job title is NOT enough by itself.
# With no industry stated, it counts only when the description also uses this many DIFFERENT BFSI phrases.
BFSI_NAME_NEEDS_DESCRIPTION_PHRASES = 2
BFSI_TITLE_NEEDS_DESCRIPTION_PHRASES = 2

# GCC: wording in which the EMPLOYER describes itself as a capability / captive / in-house / shared-services centre.
GCC_SELF_DESCRIPTION_PATTERNS = [
    r"\bglobal capabilit(y|ies) cent(er|re)s?\b",
    r"\bcaptive (cent(er|re)s?|units?|operations?|facilit(y|ies)|set-?ups?|entit(y|ies))\b",
    r"\bshared services? (cent(er|re)s?|hub|organi[sz]ation)\b",
    r"\bglobal business services\b",
    r"\bglobal in-?house cent(er|re)s?\b",
    r"\bglobal delivery cent(er|re)s?\b",
]
# Words that show the sentence is about the employer itself (not a client, not a candidate's past experience).
GCC_EMPLOYER_CUE = r"\b(our|we are|we're|we run|we operate|join|joining|part of|the india|india-based|extension of)\b"

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
