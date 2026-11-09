"""Everything the matcher needs to know about what Peter is looking for.

Edit this file, not the code. Keywords are scored by substring match against the
job title and category, case-insensitive.
"""

# Which posting seasons count. Ordered by preference.
SEASONS = {
    "Summer 2027": 25,
    "Winter 2027": 10,
    "Fall 2026": 8,
}

# Category weights (Simplify's own taxonomy).
CATEGORIES = {
    "Hardware": 20,
    "AI/ML/Data": 18,
    "Software": 15,
    "Quant": 12,
    "Software Engineering": 12,
    "Data Science, AI & Machine Learning": 15,
    "Quantitative Finance": 12,
    "Product": 6,
}

# Strong signal in the title -> big boost. These are the things he can defend.
TITLE_KEYWORDS = {
    "fpga": 18, "asic": 18, "rtl": 18, "verilog": 18, "soc": 14,
    "embedded": 16, "firmware": 16, "electronics": 14, "analog": 14,
    "rf ": 14, "dsp": 14, "signal processing": 14, "circuit": 14,
    "hardware": 12, "electrical": 12, "validation": 8, "silicon": 14,
    "machine learning": 14, "ml ": 10, "research": 10, "simulation": 12,
    "scientific": 12, "computational": 12, "linux": 10, "cuda": 12,
    "physics": 10, "data": 6, "software": 6, "systems": 6,
}

# Negative signal. Any hit is subtracted and shown to the reader.
TITLE_PENALTIES = {
    "phd": 25, "doctoral": 25, "mba": 25, "senior": 15, "principal": 15,
    "sales": 20, "marketing": 20, "recruiting": 20, "hr ": 15,
    "unpaid": 30,
}

# Where he can actually work. Everything else is flagged, not hidden.
PREFERRED_LOCATIONS = ["medford", "boston", "cambridge", "somerville", "remote"]
US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR",
}

# If any of these words appear, the posting is definitely not US-based.
NON_US_WORDS = {
    "canada","united kingdom","germany","france","india","singapore","australia",
    "china","japan","israel","ireland","netherlands","switzerland","brazil",
    "mexico","poland","romania","spain","sweden","taiwan","korea","hong kong",
    "belgium","denmark","norway","finland","portugal","italy","austria","czech",
    "hungary","turkey","south africa","nigeria","kenya","russia","ukraine",
    "vietnam","philippines","indonesia","malaysia","thailand","uae","dubai",
    "qatar","saudi","colombia","argentina","chile","peru","egypt","morocco",
    "pakistan","bangladesh","sri lanka","new zealand","luxembourg","estonia",
    "lithuania","latvia","bulgaria","croatia","serbia","slovakia","slovenia",
    "greece","iceland","monaco","cayman","bermuda",
}

# Bare city shorthand that means a US location without a state code.
US_CITY_WORDS = {"sf", "nyc", "usa", "u.s.", "bay area", "silicon valley"}

# Degree filter: he's a BS. Postings requiring only Master's/PhD are downranked.
ACCEPTED_DEGREES = ["bachelor's", "bachelors"]

# Only show jobs scoring at or above this.
MIN_FIT = 70

# Cap how many jobs land in the database per run, highest fit first.
MAX_JOBS = 400

# Short profiles for companies he already knows he wants to work at.
# Everything else gets an auto-generated stub he can edit in the UI.
COMPANY_PROFILES = {
    "Analog Devices": "Analog/mixed-signal semiconductor company (Wilmington, MA). Makes data converters, amplifiers, RF and power ICs. Strong Tufts recruiting presence, large Boston-area intern class. Best fit for his EE core: analog, RF, DSP, embedded.",
    "Arm": "UK semiconductor IP company (Cambridge, UK; Austin and San Jose in the US). Licenses CPU/GPU core designs to chipmakers. Known for low-level software, driver and emulation work. He already spoke with an Arm engineer about USB device modelling in Linux.",
    "MathWorks": "Makes MATLAB and Simulink (Natick, MA). Engineering Development Group interns build and test the simulation tooling itself. Direct overlap with his dynamical-systems simulation work.",
    "Raytheon": "Defense contractor (RTX). Missile systems, radar, RF. **ITAR: most internships require US person status.** Verify eligibility before applying.",
    "Texas Instruments": "Analog and embedded semiconductor company. Strong internship pipeline, deep analog/RF/embedded work.",
    "NVIDIA": "GPUs and accelerated computing. Relevant for CUDA, simulation acceleration and ML systems work.",
    "Qualcomm": "Wireless and mobile SoCs. Modem, RF and DSP heavy.",
    "Apple": "Consumer hardware with silicon, embedded firmware and systems teams. Hard to get into but values exactly this profile.",
    "Boston Dynamics": "Robotics (Waltham, MA). Controls, embedded systems, simulation.",
    "Draper": "Nonprofit R&D lab (Cambridge, MA). Hardware, sensing, autonomy. Often requires US person status.",
    "MIT Lincoln Laboratory": "Federally funded R&D lab (Lexington, MA). Radar, signal processing, embedded. **Requires US citizenship.**",
    "West Monroe": "Technology and management consulting (Chicago/NY). He already wrote an AI-concentration software engineering application.",
    "Formlabs": "3D printing hardware (Somerville, MA). Embedded, firmware, mechanical/electrical.",
    "iRobot": "Consumer robotics (Bedford, MA). Embedded and hardware test.",
}

# ---------------------------------------------------------------------------
# Evidence gaps. The matcher scores keywords; these flags say where you would
# have to defend something you cannot currently prove.
# ---------------------------------------------------------------------------
GAP_WARNINGS = {
    "asic": "RTL/ASIC role. Expects a Verilog project you can show — you have none on file.",
    "rtl": "RTL role. Expects a Verilog/SystemVerilog project — none on file.",
    "verilog": "Expects Verilog evidence — this is the weakest claim in your packet.",
    "fpga": "Expects an FPGA project — none on file. This is the Track B blocker.",
    "dft": "DFT/scan-test work expects digital design coursework beyond what is on the resume.",
    "physical design": "Physical design expects layout/EDA tool experience you have not claimed.",
    "analog": "Analog role. Expects the analog circuit sequence plus lab bench work — confirm.",
    "mixed-signal": "Mixed-signal expects SPICE and layout experience — confirm.",
    "circuit": "Circuit design role. Confirm you have the analog/digital coursework to defend it.",
    "spice": "Expects SPICE simulation experience — not on file.",
    "rf": "RF role. Expects microwave/EM coursework and bench experience — confirm.",
    "mechanical": "Mechanical-adjacent. Outside your evidence base.",
    "thermal": "Thermal/packaging work. Outside your evidence base.",
    "phd": "Requires a PhD. Probably out of scope.",
    "clearance": "Requires security clearance or US person status. Verify eligibility first.",
    "itar": "ITAR-restricted. Requires US person status. Verify eligibility first.",
    "sales": "Sales-adjacent role. Low overlap with your evidence.",
}
