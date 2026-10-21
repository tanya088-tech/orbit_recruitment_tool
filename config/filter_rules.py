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
    r"\bubs\b", r"\bcredit suisse\b", r"\bstate street\b", r"\bblackrock\b", r"\bnatwest\b", r"^nomura\b",
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
    # Gulf cities often written on Naukri without their country ("Riyadh", "Doha, Gulf")
    "riyadh", "jeddah", "dammam", "al khobar", "doha", "muscat", "abu dhabi", "sharjah", "ajman", "kuwait city", "manama",
    "gulf", "middle east",
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
    (r"\bmizuho\b", "Japan"), (r"\bmufg\b|\bmitsubishi ufj\b", "Japan"), (r"\bsmbc\b|\bsumitomo mitsui\b", "Japan"), (r"^nomura\b", "Japan"),
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
# --------------------------------------------------------------------------------------
# KNOWN GCC EMPLOYERS: multinational groups that run a Global Capability Centre (captive tech / operations / shared-services
# centre) in India: (name pattern, group headquarters country). A vacancy in India at one of these employers is tagged GCC
# from the company name alone, so postings that never say "GCC" are no longer missed. The country also counts as the
# headquarters evidence for REQUIRE_OVERSEAS_HQ. Patterns are matched against the company name (case-insensitive). Edit freely.
# --------------------------------------------------------------------------------------
KNOWN_GCC_EMPLOYERS = [
    # banks, insurers, asset managers, payments, market infrastructure
    (r"\bjp ?morgan", "United States"), (r"\bwells fargo\b", "United States"), (r"\bciti(group|bank|corp)?\b", "United States"),
    (r"\bbank of america\b", "United States"), (r"\bgoldman sachs\b", "United States"), (r"\bmorgan stanley\b", "United States"),
    (r"\bu\.?s\.? bank\b|\bu\.?s\.? bancorp\b", "United States"), (r"\bbny\b|\bbank of new york\b", "United States"),
    (r"\bstate street\b", "United States"), (r"\bnorthern trust\b", "United States"), (r"\bsynchrony\b", "United States"),
    (r"\bamerican express\b|\bamex\b", "United States"), (r"\bmastercard\b", "United States"), (r"^visa( inc\.?)?$", "United States"),
    (r"\bpaypal\b", "United States"), (r"\bvanguard\b", "United States"), (r"\bblackrock\b", "United States"),
    (r"\bfidelity (investments|international)\b|\bfmr\b", "United States"), (r"\bfiserv\b", "United States"),
    (r"\bfis global\b|\bfidelity national information\b", "United States"), (r"\bbroadridge\b", "United States"),
    (r"\bmetlife\b", "United States"), (r"\baig\b", "United States"), (r"\bprudential financial\b|\bpgim\b", "United States"),
    (r"\bprincipal (financial|global)\b", "United States"), (r"\bnasdaq\b", "United States"), (r"\bs&p global\b", "United States"),
    (r"\bmoody'?s\b", "United States"), (r"\bmsci\b", "United States"), (r"\bmorningstar\b", "United States"),
    (r"\bdtcc\b", "United States"), (r"\bintercontinental exchange\b|\bice data\b", "United States"),
    (r"\bocwen\b|\bonity\b", "United States"), (r"\bfreddie mac\b|\bfannie mae\b", "United States"),
    (r"\bhsbc\b", "United Kingdom"), (r"\bbarclays\b", "United Kingdom"), (r"\bstandard chartered\b", "United Kingdom"),
    (r"\bnatwest\b|\broyal bank of scotland\b", "United Kingdom"), (r"\blloyds (banking|bank|technology)\b", "United Kingdom"),
    (r"\blondon stock exchange\b|\blseg\b", "United Kingdom"), (r"\bschroders\b", "United Kingdom"), (r"\bphoenix group\b", "United Kingdom"),
    (r"\bdeutsche bank\b", "Germany"), (r"\ballianz\b", "Germany"), (r"\bcommerzbank\b", "Germany"), (r"\bmunich re\b", "Germany"),
    (r"\bbnp paribas\b", "France"), (r"\bsoci[eé]t[eé] g[eé]n[eé]rale\b|\bsocgen\b", "France"), (r"\baxa\b", "France"),
    (r"\bcr[eé]dit agricole\b|\bcacib\b", "France"), (r"\bnatixis\b", "France"),
    (r"\bubs\b", "Switzerland"), (r"\bchubb\b", "Switzerland"), (r"\bzurich insurance\b", "Switzerland"), (r"\bswiss re\b", "Switzerland"),
    (r"\bjulius b[aä]r\b", "Switzerland"),
    (r"\bing (bank|groep|group|hubs?|tech)\b", "Netherlands"), (r"\babn amro\b", "Netherlands"), (r"\brabobank\b", "Netherlands"),
    (r"\bdbs\b", "Singapore"), (r"\bocbc\b", "Singapore"), (r"\buob\b", "Singapore"),
    (r"\bmufg\b|\bmitsubishi ufj\b", "Japan"), (r"\bmizuho\b", "Japan"), (r"^nomura\b", "Japan"), (r"\bsmbc\b|\bsumitomo mitsui\b", "Japan"),
    (r"\banz\b", "Australia"), (r"\bmacquarie\b", "Australia"), (r"\bwestpac\b", "Australia"), (r"\bcommonwealth bank\b", "Australia"),
    (r"\bmanulife\b|\bjohn hancock\b", "Canada"), (r"\bsun life\b", "Canada"), (r"\bcibc\b", "Canada"), (r"\bscotiabank\b", "Canada"),
    (r"\broyal bank of canada\b", "Canada"), (r"\btd bank\b|\btoronto[- ]dominion\b", "Canada"),
    (r"\bemirates nbd\b", "United Arab Emirates"), (r"\bmashreq\b", "United Arab Emirates"),
    # Big Four and professional-services captives (named by their India delivery arm only, not their Indian client practices)
    (r"\bey gds\b|\bey global delivery\b", "United Kingdom"), (r"\bdeloitte (usi|us india|global)\b", "United States"),
    (r"\bkpmg global services\b|\bkpmg (resource|delivery) cent", "Netherlands"), (r"\bpwc (acceleration|service delivery)\b", "United Kingdom"),
    (r"\bgartner\b", "United States"), (r"\bmckinsey\b", "United States"), (r"\bboston consulting\b|\bbcg\b", "United States"),
    (r"\bbain & company\b|\bbain capability\b", "United States"),
    # technology and product companies
    (r"\bmicrosoft\b", "United States"), (r"\bgoogle\b|\balphabet\b", "United States"), (r"^apple( inc\.?)?$", "United States"),
    (r"\bcisco\b", "United States"), (r"\bintel\b", "United States"), (r"\bqualcomm\b", "United States"),
    (r"\btexas instruments\b", "United States"), (r"\bnvidia\b", "United States"), (r"\bamd\b|\badvanced micro devices\b", "United States"),
    (r"\bdell\b", "United States"), (r"\bhp inc\b|\bhewlett", "United States"), (r"\boracle\b", "United States"),
    (r"\badobe\b", "United States"), (r"\bsalesforce\b", "United States"), (r"\bservicenow\b", "United States"),
    (r"\bvmware\b|\bbroadcom\b", "United States"), (r"\bintuit\b", "United States"), (r"\bautodesk\b", "United States"),
    (r"\bworkday\b", "United States"), (r"\bmicron\b", "United States"), (r"\banalog devices\b", "United States"),
    (r"\bnetapp\b", "United States"), (r"\bpalo alto networks\b", "United States"), (r"\buber\b", "United States"),
    (r"\blinkedin\b", "United States"), (r"\bsap\b", "Germany"), (r"\bsiemens\b", "Germany"), (r"\bbosch\b", "Germany"),
    (r"\binfineon\b", "Germany"), (r"\bnxp\b", "Netherlands"), (r"\bericsson\b", "Sweden"), (r"\bnokia\b", "Finland"),
    (r"\bthomson reuters\b", "Canada"), (r"\bwolters kluwer\b", "Netherlands"), (r"\brelx\b|\belsevier\b|\blexisnexis\b", "United Kingdom"),
]
# Groups that ALSO run an ordinary Indian business (factories, shops, field sales, hospitals...). Their name counts as GCC
# evidence only when the job title is capability-centre work (GCC_CAPABILITY_TITLE_PATTERNS below): "Siemens - Software
# Engineer" is GCC, "Siemens - Plant Manager" is not. Same (name pattern, headquarters country) format.
KNOWN_GCC_MIXED_EMPLOYERS = [
    # retail, consumer, industrial, automotive, energy, healthcare
    (r"\bwalmart\b", "United States"), (r"^target$|\btarget (corporation|in india|india)\b", "United States"),
    (r"\blowe'?s\b", "United States"), (r"\bhome depot\b", "United States"), (r"\bbest buy\b", "United States"),
    (r"\bnike\b", "United States"), (r"\bkroger\b", "United States"), (r"\bcostco\b", "United States"), (r"\bmcdonald'?s global\b", "United States"),
    (r"\bprocter & gamble\b|\bp&g\b", "United States"), (r"\bpepsico\b", "United States"), (r"\bcoca[- ]cola\b", "United States"),
    (r"\bmondelez\b", "United States"), (r"\bkellogg\b|\bkellanova\b", "United States"), (r"^mars( inc\.?| incorporated)?$", "United States"),
    (r"\bgeneral electric\b|\bge (aerospace|vernova|healthcare)\b", "United States"), (r"\bhoneywell\b", "United States"),
    (r"\bcaterpillar\b", "United States"), (r"\bjohn deere\b|\bdeere\b", "United States"), (r"\bboeing\b", "United States"),
    (r"\bford motor\b|^ford$", "United States"), (r"\bgeneral motors\b", "United States"), (r"\bcummins\b", "United States"),
    (r"\beaton\b", "Ireland"), (r"\bemerson\b", "United States"), (r"\b3m\b", "United States"), (r"^carrier$|\bcarrier (global|corporation|technologies)\b", "United States"),
    (r"^otis$|\botis (elevator|worldwide)\b", "United States"), (r"\bjohnson controls\b", "Ireland"), (r"\brtx\b|\braytheon\b|\bpratt & whitney\b|\bcollins aerospace\b", "United States"),
    (r"\bmercedes[- ]benz\b", "Germany"), (r"\bbmw\b", "Germany"), (r"\bvolkswagen\b", "Germany"),
    (r"\bzf\b", "Germany"), (r"\bschaeffler\b", "Germany"), (r"\bbasf\b", "Germany"), (r"\bbayer\b", "Germany"),
    (r"\bvolvo\b", "Sweden"), (r"\babb\b", "Switzerland"), (r"\bschneider electric\b", "France"), (r"\bairbus\b", "France"),
    (r"\bsafran\b", "France"), (r"\bphilips\b", "Netherlands"), (r"^shell$|\bshell (india|business|technology)\b", "United Kingdom"), (r"^bp$|\bbp (india|business solutions)\b", "United Kingdom"),
    (r"\bexxon\b", "United States"), (r"\bchevron\b", "United States"), (r"\bunilever\b", "United Kingdom"),
    (r"\bnestl[eé]\b", "Switzerland"), (r"\bmaersk\b", "Denmark"), (r"\bdhl\b", "Germany"), (r"\bfedex\b", "United States"),
    (r"^ups$|\bups (india|supply chain|global)\b", "United States"), (r"\bpfizer\b", "United States"), (r"\bjohnson & johnson\b|\bj&j\b", "United States"),
    (r"\bmerck\b|\bmsd\b", "United States"), (r"\babbott\b", "United States"), (r"\beli lilly\b", "United States"),
    (r"\bamgen\b", "United States"), (r"\bmedtronic\b", "Ireland"), (r"\boptum\b|\bunitedhealth\b", "United States"),
    (r"\bcigna\b|\bevernorth\b", "United States"), (r"\belevance\b|\bcarelon\b", "United States"), (r"\bcvs health\b", "United States"),
    (r"\bnovartis\b", "Switzerland"), (r"\broche\b", "Switzerland"), (r"\bastrazeneca\b", "United Kingdom"),
    (r"\bgsk\b|\bglaxosmithkline\b", "United Kingdom"), (r"\bsanofi\b", "France"), (r"\bnovo nordisk\b", "Denmark"),
]
# Capability-centre work: technology, data, engineering design, finance / HR / procurement operations, analytics, risk.
GCC_CAPABILITY_TITLE_PATTERNS = [
    r"\bsoftware\b", r"\bdevelop(er|ment)\b", r"\bprogrammer\b", r"\bdata\b", r"\banalytics?\b", r"\banalyst\b",
    r"\barchitect\b", r"\bcloud\b", r"\bdevops\b", r"\bsre\b", r"\bcyber\b", r"\b(information )?security\b", r"\bit\b",
    r"\btechnology\b", r"\btech\b", r"\bdigital\b", r"\bmachine learning\b", r"\bai\b", r"\bml\b", r"\bscientist\b",
    r"\bproduct (manager|owner|management)\b", r"\bscrum\b", r"\bqa\b", r"\btest(ing)?\b", r"\bsap\b", r"\berp\b",
    r"\b(design|software|systems|embedded|firmware|r&d|simulation|cad|cae|validation) engineer", r"\bengineering (lead|manager)\b",
    r"\bfinance\b", r"\baccount(ing|ant|s payable|s receivable)\b", r"\bpayroll\b", r"\bprocurement\b", r"\bsourcing\b",
    r"\bsupply chain (analyst|planner|planning)\b", r"\brisk\b", r"\bcompliance\b", r"\baudit\b", r"\bcontroller\b", r"\bfp&a\b",
    r"\btax\b", r"\bhr (operations|services|shared)\b", r"\bshared services\b", r"\bglobal\b", r"\bresearch\b",
]
# Roles that are part of a group's ordinary Indian business (branches, retail banking, field sales, stores), not its capability
# centre. For these titles the company name alone does NOT make the vacancy a GCC one (it can still be BFSI).
GCC_NAME_NOT_FOR_TITLE_PATTERNS = [
    r"\bbranch\b", r"\bteller\b", r"\bcashier\b", r"\bpersonal banker\b", r"\bconsumer banking\b", r"\bretail banking\b", r"\bcasa\b",
    r"\b(premier|platinum|priority|imperia|wealth|branch|privilege) relationship manager\b", r"\bsales (officer|executive)\b",
    r"\bfield sales\b", r"\bterritory\b", r"\bmedical (representative|rep)\b", r"\barea (sales )?manager\b", r"\bstore\b",
    r"\bwarehouse\b", r"\bdelivery (associate|executive|boy)\b", r"\bfront desk\b", r"\bplant\b", r"\bproduction\b",
    r"\bshop ?floor\b", r"\btechnician\b", r"\boperator\b",
]

# --------------------------------------------------------------------------------------
# CARD TITLES NOT WORTH OPENING: job titles on a Naukri search card that are clearly not GCC / BFSI work (tele-calling, BPO voice,
# property sales, delivery, hospitality ...). The detail page is not opened, which is what makes Naukri slow. Kept deliberately
# narrow: a card from a known GCC / overseas-headquartered employer (KNOWN_GCC_EMPLOYERS, OVERSEAS_HQ_EMPLOYERS ...) is always
# opened whatever its title, and banking / insurance / finance words never appear here. Edit with care.
# --------------------------------------------------------------------------------------
CARD_TITLE_SKIP_PATTERNS = [
    r"\btele ?-?call(er|ing)\b", r"\btele ?-?sales\b", r"\b(international |domestic )?voice process\b", r"\bbpo\b",
    r"\bcall cent(er|re)\b", r"\b(property|real estate|realty) (advisor|adviser|consultant|sales|executive|manager)\b",
    r"\breal estate\b", r"\bdelivery (boy|executive|partner|associate|rider)\b", r"\bdriver\b", r"\bsecurity guard\b",
    r"\bhousekeeping\b", r"\b(chef|cook|waiter|steward|bartender)\b", r"\brestaurant\b", r"\bhotel\b", r"\bbeautician\b",
    r"\bsalon\b", r"\bnurse\b|\bnursing\b", r"\bpharmacist\b", r"\b(school|primary|pre-?primary) teacher\b",
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
