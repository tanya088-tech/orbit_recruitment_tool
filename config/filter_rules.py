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


# --------------------------------------------------------------------------------------
# HEADQUARTERS (the client's rule: only GCC / BFSI employers headquartered OUTSIDE India qualify, for vacancies in India)
# --------------------------------------------------------------------------------------
# Reference list of well-known employers whose group headquarters is outside India: (name pattern, headquarters country).
# It supplies the HEADQUARTERS evidence only. The employer must still show GCC or BFSI evidence of its own (its industry,
# or - for a non-BFSI group - the posting describing the India unit as a capability / captive / shared-services centre).
# A company that is not listed needs a headquarters statement in its job description (see HQ_* below). Edit freely.
OVERSEAS_HQ_EMPLOYERS = [
    # banks, insurers, asset managers, payments / market infrastructure
    (r"\bwells fargo\b", "United States"), (r"\bjp ?morgan", "United States"), (r"\bciti(group|bank)?\b", "United States"),
    (r"\bbank of america\b", "United States"), (r"\bgoldman sachs\b", "United States"), (r"\bmorgan stanley\b", "United States"),
    (r"\bu\.?s\.? bancorp\b|\bu\.?s\.? bank\b", "United States"), (r"\bbny\b|\bbank of new york\b", "United States"),
    (r"\bstate street\b", "United States"), (r"\bnorthern trust\b", "United States"), (r"\bcapital one\b", "United States"),
    (r"\bsynchrony\b", "United States"), (r"\bamerican express\b|\bamex\b", "United States"), (r"\bmastercard\b", "United States"),
    (r"\bpaypal\b", "United States"), (r"\bvanguard\b", "United States"), (r"\bblackrock\b", "United States"),
    (r"\bblackstone\b", "United States"), (r"\bjefferies\b", "United States"), (r"\bfirst citizens\b", "United States"),
    (r"\bfidelity investments\b|\bfmr\b", "United States"), (r"\bcharles schwab\b", "United States"), (r"\bpnc\b", "United States"),
    (r"\btruist\b", "United States"), (r"\bdiscover financial\b", "United States"), (r"\bfiserv\b", "United States"),
    (r"\bprudential financial\b", "United States"), (r"\bmetlife\b", "United States"), (r"\baig\b", "United States"),
    (r"\bhsbc\b", "United Kingdom"), (r"\bbarclays\b", "United Kingdom"), (r"\bstandard chartered\b", "United Kingdom"),
    (r"\bnatwest\b|\broyal bank of scotland\b", "United Kingdom"), (r"\blloyds banking\b|\blloyds bank\b", "United Kingdom"),
    (r"\brevolut\b", "United Kingdom"), (r"\boaknorth\b", "United Kingdom"), (r"\bbarclaycard\b", "United Kingdom"),
    (r"\bprudential plc\b", "United Kingdom"),
    (r"\bdeutsche bank\b", "Germany"), (r"\ballianz\b", "Germany"),
    (r"\bbnp paribas\b", "France"), (r"\bsoci[eé]t[eé] g[eé]n[eé]rale\b|\bsocgen\b", "France"), (r"\baxa\b", "France"),
    (r"\bcr[eé]dit agricole\b", "France"),
    (r"\bubs\b", "Switzerland"), (r"\bcredit suisse\b", "Switzerland"), (r"\bchubb\b", "Switzerland"), (r"\bzurich insurance\b", "Switzerland"),
    (r"\bing (bank|groep|group)\b", "Netherlands"), (r"\babn amro\b", "Netherlands"), (r"\brabobank\b", "Netherlands"),
    (r"\bsantander\b", "Spain"), (r"\bbbva\b", "Spain"),
    (r"\bdbs\b", "Singapore"), (r"\bocbc\b", "Singapore"), (r"\buob\b", "Singapore"),
    (r"\bmizuho\b", "Japan"), (r"\bmufg\b|\bmitsubishi ufj\b", "Japan"), (r"\bsmbc\b|\bsumitomo mitsui\b", "Japan"), (r"\bnomura\b", "Japan"),
    (r"\banz\b", "Australia"), (r"\bcommonwealth bank\b", "Australia"), (r"\bmacquarie\b", "Australia"),
    (r"\bnational australia bank\b|\bnab\b", "Australia"), (r"\bwestpac\b", "Australia"),
    (r"\bcibc\b", "Canada"), (r"\broyal bank of canada\b|\brbc\b", "Canada"), (r"\bscotiabank\b", "Canada"),
    (r"\btd bank\b|\btoronto[- ]dominion\b", "Canada"), (r"\bmanulife\b", "Canada"), (r"\bsun life\b", "Canada"),
    (r"\bmashreq\b", "United Arab Emirates"), (r"\bemirates (nbd|islamic)\b", "United Arab Emirates"),
    # groups outside banking that run well-known India capability centres (still need GCC evidence in the posting)
    (r"\bwalmart\b", "United States"), (r"\btarget\b", "United States"), (r"\blowe'?s\b", "United States"), (r"\bhome depot\b", "United States"),
    (r"\bbest buy\b", "United States"), (r"\bnike\b", "United States"), (r"\bgeneral electric\b|\bge (aerospace|vernova|healthcare)\b", "United States"),
    (r"\bhoneywell\b", "United States"), (r"\bford\b", "United States"), (r"\bgeneral motors\b", "United States"),
    (r"\bcaterpillar\b", "United States"), (r"\bcisco\b", "United States"), (r"\bmicrosoft\b", "United States"),
    (r"\bintel\b", "United States"), (r"\bqualcomm\b", "United States"), (r"\btexas instruments\b", "United States"),
    (r"\bdell\b", "United States"), (r"\bhp inc\b|\bhewlett", "United States"), (r"\bibm\b", "United States"),
    (r"\boracle\b", "United States"), (r"\badobe\b", "United States"), (r"\bsalesforce\b", "United States"),
    (r"\bpfizer\b", "United States"), (r"\bjohnson & johnson\b|\bj&j\b", "United States"), (r"\bmerck\b", "United States"),
    (r"\bsiemens\b", "Germany"), (r"\bbosch\b", "Germany"), (r"\bsap\b", "Germany"), (r"\bphilips\b", "Netherlands"),
    (r"\bnovartis\b", "Switzerland"), (r"\broche\b", "Switzerland"), (r"\bnestl[eé]\b", "Switzerland"),
    (r"\bgsk\b|\bglaxosmithkline\b", "United Kingdom"), (r"\bastrazeneca\b", "United Kingdom"), (r"\bunilever\b", "United Kingdom"),
    (r"\bshell\b", "United Kingdom"), (r"\bbp\b", "United Kingdom"), (r"\bairbus\b", "France"),
]
# Employers headquartered in India. They never qualify unless the posting itself names an overseas headquarters.
INDIA_HQ_EMPLOYERS = [
    r"\bhdfc\b", r"\bicici\b", r"\bkotak\b", r"\bsbi\b", r"\bstate bank of india\b", r"\bidfc\b", r"\baxis bank\b", r"\byes bank\b",
    r"\bbajaj\b", r"\bjana small\b", r"\bau small finance\b", r"\bujjivan\b", r"\bequitas\b", r"\besaf\b", r"\bdcb bank\b",
    r"\brbl bank\b", r"\bcsb bank\b", r"\bbandhan\b", r"\bindusind\b", r"\bfederal bank\b", r"\bpunjab national\b", r"\bbank of baroda\b",
    r"\bcanara\b", r"\bunion bank of india\b", r"\bindian bank\b", r"\bmuthoot\b", r"\bmanappuram\b", r"\bshriram\b", r"\bchola\w*\b",
    r"\baditya birla\b", r"\bmax life\b", r"\blic\b", r"\btata\b", r"\breliance\b", r"\bmahindra\b", r"\bsharekhan\b", r"\bedelweiss\b",
    r"\bjm financial\b", r"\bpaytm\b", r"\bphonepe\b", r"\bairtel\b", r"\bsbicap\b|\bsbi card\b|\bsbi life\b", r"\bnaukri\b", r"\bindbank\b",
]
# Statements in the job description that name where the group is headquartered. The place found is checked: an Indian place
# means India-headquartered, a foreign country / city / US state means overseas.
HQ_STATEMENT_PATTERNS = [
    r"\b(?:global |corporate |group |worldwide )?head ?quarter(?:ed|s)?\s*(?:is |are |being )?(?:located )?(?:in|at|:)\s+(?P<place>[^.;\n]{2,80})",
    r"\bparent (?:company|organi[sz]ation|group)[^.;\n]{0,80}?(?:based|headquartered|located) in\s+(?P<place>[^.;\n]{2,60})",
    r"\bheadquarters? (?:of|for) (?:the |our )?(?:group|firm|company|bank)[^.;\n]{0,40}?(?:in|at)\s+(?P<place>[^.;\n]{2,60})",
]
# "a US-based bank", "German based company": a nationality / country before based|headquartered|owned.
HQ_ADJECTIVE_PATTERN = (r"\b(?P<c>u\.?s\.?a?\.?|american|u\.?k\.?|british|german|french|swiss|dutch|japanese|singapore(?:an)?|canadian|"
                        r"australian|irish|swedish|spanish|italian|european|emirati|korean|chinese)[- ]+(?:based|headquartered|owned)\b")
HQ_FOREIGN_CITIES = {
    "new york", "san francisco", "chicago", "charlotte", "boston", "dallas", "houston", "seattle", "atlanta", "los angeles", "washington",
    "minneapolis", "san jose", "austin", "london", "manchester", "edinburgh", "paris", "frankfurt", "berlin", "munich", "zurich", "geneva",
    "amsterdam", "dublin", "madrid", "toronto", "montreal", "vancouver", "sydney", "melbourne", "tokyo", "osaka", "seoul", "shanghai",
    "singapore", "hong kong", "dubai", "abu dhabi", "doha", "riyadh", "stockholm", "copenhagen", "brussels", "milan", "luxembourg", "basel",
}
